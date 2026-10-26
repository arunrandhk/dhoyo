import json
import os
import smtplib
import sys
import base64
from email import message_from_bytes
from unittest.mock import Mock
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from app import app
from auth import digest
import password_reset
from social import raw_state


HEADERS = {'X-Dhoyo-Request': '1'}
PASSWORD = 'my-long-password'


@pytest.fixture
def reset_clients(tmp_path, monkeypatch):
    monkeypatch.setenv('SPORTSPACE_SOCIAL_DB', str(tmp_path / 'reset.sqlite'))
    monkeypatch.setitem(app.config, 'AUTH_TEST_DEMO', False)
    for name, value in {
        'SMTP_HOST': 'smtp.example.com', 'SMTP_PORT': '587',
        'SMTP_FROM': 'accounts@example.com', 'SMTP_USERNAME': '', 'SMTP_PASSWORD': '',
        'SMTP_USE_TLS': 'true',
        'RESEND_API_KEY': '', 'PASSWORD_RESET_FROM': '',
        'GMAIL_CLIENT_ID': '', 'GMAIL_CLIENT_SECRET': '', 'GMAIL_REFRESH_TOKEN': '',
        'PASSWORD_RESET_BASE_URL': 'https://dhoyo.example/static/sportspace/index.html',
    }.items():
        monkeypatch.setitem(app.config, name, value)
    deliveries = []

    def deliver(settings, recipient, token):
        # A second database transaction succeeds while delivery is running.
        with raw_state() as data:
            data['mailCheckedOutsideTransaction'] = True
        deliveries.append((settings, recipient, token))
        return True, recipient is not None

    monkeypatch.setattr(password_reset, 'deliver_password_reset', deliver)
    return app.test_client(), app.test_client(), deliveries


def register(client, email='alex@example.com'):
    return client.post('/api/auth/register', json=dict(
        name='Alex', email=email, password=PASSWORD, sport='Football',
        city='Delhi', state='Delhi', country='India'), headers=HEADERS)


def forgot(client, email='alex@example.com', **kwargs):
    kwargs.setdefault('base_url', 'https://localhost')
    return client.post('/api/auth/forgot-password', json={'email': email}, headers=HEADERS, **kwargs)


def reset(client, token, password='a-new-password', **kwargs):
    kwargs.setdefault('base_url', 'https://localhost')
    return client.post('/api/auth/reset-password', json={'token': token, 'password': password}, headers=HEADERS, **kwargs)


def login(client, password=PASSWORD, **kwargs):
    kwargs.setdefault('base_url', 'https://localhost')
    return client.post('/api/auth/login', json={'email': 'alex@example.com', 'password': password}, headers=HEADERS, **kwargs)


def test_request_is_generic_and_stores_only_digest(reset_clients):
    a, b, deliveries = reset_clients
    assert register(a).status_code == 201
    known = forgot(a, '  ALEX@EXAMPLE.COM  ')
    unknown = forgot(b, 'unknown@example.com')
    assert known.status_code == unknown.status_code == 200
    assert known.json == unknown.json == {'message': password_reset.REQUEST_MESSAGE}
    _, recipient, token = deliveries[0]
    assert recipient == 'alex@example.com'
    assert len(token) == 43 and token not in known.get_data(as_text=True)
    assert deliveries[1][1:] == (None, None)
    with raw_state() as data:
        assert token not in str(data)
        assert set(data['passwordResetTokens']) == {digest(token)}
        assert data['passwordResetTokens'][digest(token)]['active']
        assert data['mailCheckedOutsideTransaction']


def test_reset_revokes_sessions_rejects_old_password_and_is_single_use(reset_clients):
    a, b, deliveries = reset_clients
    assert register(a).status_code == 201
    assert login(b).status_code == 200
    assert forgot(a).status_code == 200
    token = deliveries[-1][2]
    new_password = '  New password ☃  '
    response = reset(a, token, new_password)
    assert response.status_code == 200
    assert a.get_cookie('dhoyo_session') is None
    assert a.get('/api/arena').status_code == b.get('/api/arena').status_code == 401
    assert a.get('/api/auth/me').json['userId'] is None
    assert login(a).status_code == 401
    assert login(a, new_password.strip()).status_code == 401
    assert login(a, new_password).status_code == 200
    assert reset(b, token).status_code == 400
    with raw_state() as data:
        assert not data['passwordResetTokens']
        assert new_password not in str(data)
        assert data['accounts']['alex@example.com']['password_hash'].startswith('scrypt:')


def test_expiry_and_password_policy_leave_active_token_usable(reset_clients):
    a, _, deliveries = reset_clients
    register(a)
    forgot(a)
    token = deliveries[-1][2]
    assert reset(a, token, 'short').status_code == 400
    assert reset(a, token, 'x' * 129).status_code == 400
    with raw_state() as data:
        assert digest(token) in data['passwordResetTokens']
        data['passwordResetTokens'][digest(token)]['expires'] = 0
    response = reset(a, token)
    assert response.status_code == 400
    assert response.json['error'] == password_reset.INVALID_TOKEN_MESSAGE
    with raw_state() as data:
        assert not data['passwordResetTokens']


def test_missing_or_invalid_mail_config_is_uniform_and_never_uses_host(reset_clients, monkeypatch):
    a, b, deliveries = reset_clients
    register(a)
    monkeypatch.setitem(app.config, 'SMTP_HOST', '')
    known, unknown = forgot(a), forgot(b, 'unknown@example.com')
    assert known.status_code == unknown.status_code == 503
    assert known.json == unknown.json
    assert not deliveries
    monkeypatch.setitem(app.config, 'SMTP_HOST', 'smtp.example.com')
    monkeypatch.setitem(app.config, 'PASSWORD_RESET_BASE_URL', 'http://untrusted.example/reset')
    assert forgot(a).status_code == 503
    monkeypatch.setitem(app.config, 'PASSWORD_RESET_BASE_URL', 'https://trusted.example/index.html')
    assert forgot(a, base_url='https://attacker.example').status_code == 200
    assert deliveries[-1][0]['base_url'] == 'https://trusted.example/index.html'


def test_unavailable_provider_discards_pending_token_uniformly(reset_clients, monkeypatch):
    a, b, _ = reset_clients
    register(a)
    monkeypatch.setattr(password_reset, 'deliver_password_reset', lambda *args: (False, False))
    known, unknown = forgot(a), forgot(b, 'unknown@example.com')
    assert known.status_code == unknown.status_code == 503
    assert known.json == unknown.json
    with raw_state() as data:
        assert not data['passwordResetTokens']


def test_delivery_failure_preserves_old_link_and_success_replaces_it(reset_clients, monkeypatch):
    a, _, deliveries = reset_clients
    register(a)
    forgot(a)
    old_token = deliveries[-1][2]
    delivery = password_reset.deliver_password_reset
    monkeypatch.setattr(password_reset, 'deliver_password_reset', lambda *args: (True, False))
    assert forgot(a).status_code == 200
    with raw_state() as data:
        assert set(data['passwordResetTokens']) == {digest(old_token)}
    monkeypatch.setattr(password_reset, 'deliver_password_reset', delivery)
    assert forgot(a).status_code == 200
    new_token = deliveries[-1][2]
    assert reset(a, old_token).status_code == 400
    assert reset(a, new_token).status_code == 200


def test_shared_email_and_address_limits_are_bounded_and_expire(reset_clients):
    a, b, deliveries = reset_clients
    for index in range(3):
        assert forgot(a, 'unknown@example.com').status_code == 200
    response = forgot(b, 'UNKNOWN@example.com')
    assert response.status_code == 429
    assert response.headers['Retry-After'] == '900'
    assert len(deliveries) == 3
    for index in range(17):
        assert forgot(a, f'unknown-{index}@example.com').status_code == 200
    assert forgot(b, 'another@example.com').status_code == 429
    with raw_state() as data:
        for entry in data['passwordResetRateLimits'].values():
            entry['until'] = 0
    assert forgot(b, 'unknown@example.com').status_code == 200
    with raw_state() as data:
        data['passwordResetRateLimits'] = {
            str(index): {'count': 1, 'until': 1e12}
            for index in range(password_reset.MAX_RATE_ENTRIES)
        }
    assert forgot(a, 'new-email@example.com').status_code == 429
    with raw_state() as data:
        assert len(data['passwordResetRateLimits']) == password_reset.MAX_RATE_ENTRIES


def test_invalid_reset_attempts_are_shared_and_limited(reset_clients):
    a, b, _ = reset_clients
    for index in range(10):
        assert reset(a, 'invalid-token').status_code == 400
    assert reset(b, 'invalid-token').status_code == 429


def test_reset_clears_account_login_lockouts_across_addresses(reset_clients):
    a, b, deliveries = reset_clients
    register(a)
    for address in ('127.0.0.1', '192.0.2.10'):
        for index in range(10):
            assert login(b, 'incorrect', environ_overrides={'REMOTE_ADDR': address}).status_code == 401
        assert login(b, environ_overrides={'REMOTE_ADDR': address}).status_code == 429
    forgot(a)
    assert reset(a, deliveries[-1][2]).status_code == 200
    for address in ('127.0.0.1', '192.0.2.10'):
        assert login(b, 'a-new-password', environ_overrides={'REMOTE_ADDR': address}).status_code == 200


def test_validation_and_csrf_do_not_change_password(reset_clients):
    a, _, _ = reset_clients
    register(a)
    assert forgot(a, 'invalid').status_code == 400
    assert forgot(a, 'alex@exa\nmple.com').status_code == 400
    assert a.post('/api/auth/forgot-password', json={'email': 'alex@example.com'}).status_code == 403
    assert a.post('/api/auth/reset-password', json={'token': 'x' * 43, 'password': 'a-new-password'}).status_code == 403
    assert login(a).status_code == 200


def test_smtp_uses_tls_and_link_fragment_without_logging_token(reset_clients, monkeypatch, caplog):
    _, _, _ = reset_clients
    smtp = Mock()
    constructor = Mock(return_value=smtp)
    monkeypatch.setattr(smtplib, 'SMTP', constructor)
    with app.app_context():
        settings = password_reset.mail_settings()
        settings.update(username='smtp-user', password='smtp-password')
        # Exercise the actual mail sender rather than the fixture's stub.
        assert REAL_DELIVER(settings, 'alex@example.com', 'opaque-reset-token') == (True, True)
        assert REAL_DELIVER(settings, None, None) == (True, False)
    constructor.assert_called_with('smtp.example.com', 587, timeout=10)
    assert smtp.starttls.call_count == 2
    assert smtp.starttls.call_args.kwargs['context'].check_hostname
    smtp.login.assert_called_with('smtp-user', 'smtp-password')
    message = smtp.send_message.call_args.args[0]
    assert message['To'] == 'alex@example.com'
    assert 'https://dhoyo.example/static/sportspace/index.html#reset-token=opaque-reset-token' in message.get_content()
    assert smtp.send_message.call_count == 1
    assert 'opaque-reset-token' not in caplog.text


REAL_DELIVER = password_reset.deliver_password_reset


def test_smtp_connection_and_recipient_failures_return_distinct_internal_results(reset_clients, monkeypatch, caplog):
    _, _, _ = reset_clients
    smtp = Mock()
    monkeypatch.setattr(smtplib, 'SMTP', Mock(side_effect=smtplib.SMTPConnectError(421, 'private-smtp-password')))
    with app.app_context():
        settings = password_reset.mail_settings()
        assert REAL_DELIVER(settings, 'alex@example.com', 'private-token') == (False, False)
        assert REAL_DELIVER(settings, None, None) == (False, False)
        monkeypatch.setattr(smtplib, 'SMTP', Mock(return_value=smtp))
        smtp.send_message.side_effect = smtplib.SMTPRecipientsRefused({'alex@example.com': (550, 'private-code-001234')})
        assert REAL_DELIVER(settings, 'alex@example.com', 'private-token') == (True, False)
        assert REAL_DELIVER(settings, None, None) == (True, False)
    assert 'provider=smtp stage=connect smtp_error=SMTPConnectError' in caplog.text
    assert 'provider=smtp stage=send smtp_error=SMTPRecipientsRefused' in caplog.text
    for private_value in ('alex@example.com', 'private-token', 'private-smtp-password', 'private-code-001234'):
        assert private_value not in caplog.text


def test_resend_is_preferred_and_posts_to_fixed_https_endpoint(reset_clients, monkeypatch, caplog):
    _, _, _ = reset_clients
    monkeypatch.setitem(app.config, 'RESEND_API_KEY', 'private-api-key')
    monkeypatch.setitem(app.config, 'PASSWORD_RESET_FROM', 'accounts@dhoyo.example')
    response = Mock(status=200)
    response.read.return_value = b'{"id":"message-id"}'
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    open_request = Mock(return_value=response)
    monkeypatch.setattr(password_reset, 'urlopen', open_request)
    with app.app_context():
        settings = password_reset.mail_settings()
        assert settings['provider'] == 'resend'
        assert REAL_DELIVER(settings, 'alex@example.com', 'private-token') == (True, True)
        assert REAL_DELIVER(settings, None, None) == (True, False)
    assert open_request.call_count == 1
    send_request = open_request.call_args.args[0]
    assert send_request.full_url == 'https://api.resend.com/emails'
    assert send_request.get_method() == 'POST'
    assert send_request.get_header('Authorization') == 'Bearer private-api-key'
    assert open_request.call_args.kwargs == {'timeout': 10}
    payload = json.loads(send_request.data)
    assert payload['from'] == 'accounts@dhoyo.example'
    assert payload['to'] == ['alex@example.com']
    assert '#reset-token=private-token' in payload['text']
    assert 'private-token' not in caplog.text and 'private-api-key' not in caplog.text


@pytest.mark.parametrize('failure', ['http', 'network', 'malformed', 'missing-id', 'non-200'])
def test_resend_failures_are_generic_without_logging_secrets(reset_clients, monkeypatch, caplog, failure):
    _, _, _ = reset_clients
    monkeypatch.setitem(app.config, 'RESEND_API_KEY', 'private-api-key')
    monkeypatch.setitem(app.config, 'PASSWORD_RESET_FROM', 'accounts@dhoyo.example')
    response = Mock(status=503 if failure == 'non-200' else 200)
    response.read.return_value = b'invalid-json' if failure == 'malformed' else b'{}'
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    open_request = Mock(return_value=response)
    if failure == 'http':
        open_request.side_effect = HTTPError('https://api.resend.com/emails', 401, 'private-api-key', {}, None)
    elif failure == 'network':
        open_request.side_effect = URLError('private-token')
    monkeypatch.setattr(password_reset, 'urlopen', open_request)
    with app.app_context():
        settings = password_reset.mail_settings()
        assert REAL_DELIVER(settings, 'alex@example.com', 'private-token') == (True, False)
        assert REAL_DELIVER(settings, None, None) == (True, False)
    assert 'provider=resend stage=send' in caplog.text
    if failure == 'http':
        assert 'http_status=401' in caplog.text
    assert 'private-token' not in caplog.text and 'private-api-key' not in caplog.text
    assert 'alex@example.com' not in caplog.text and 'accounts@dhoyo.example' not in caplog.text


def gmail_settings(monkeypatch):
    for name, value in {
        'GMAIL_CLIENT_ID': 'test-client-id', 'GMAIL_CLIENT_SECRET': 'private-client-secret',
        'GMAIL_REFRESH_TOKEN': 'private-refresh-token', 'PASSWORD_RESET_FROM': 'sender@gmail.com',
    }.items():
        monkeypatch.setitem(app.config, name, value)


def response_mock(content, status=200):
    response = Mock(status=status)
    response.read.return_value = content
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    return response


def test_gmail_takes_precedence_and_partial_configuration_is_uniform(reset_clients, monkeypatch):
    a, b, _ = reset_clients
    register(a)
    monkeypatch.setitem(app.config, 'GMAIL_CLIENT_ID', 'test-client-id')
    assert forgot(a).status_code == forgot(b, 'unknown@example.com').status_code == 503
    gmail_settings(monkeypatch)
    monkeypatch.setitem(app.config, 'RESEND_API_KEY', 'alternate-provider-key')
    with app.app_context():
        assert password_reset.mail_settings()['provider'] == 'gmail'


def test_gmail_refreshes_for_all_requests_and_sends_valid_encoded_message(reset_clients, monkeypatch, caplog):
    _, _, _ = reset_clients
    gmail_settings(monkeypatch)
    open_request = Mock(side_effect=[
        response_mock(b'{"access_token":"private-access-token"}'),
        response_mock(b'{"id":"gmail-message-id"}'),
        response_mock(b'{"access_token":"private-access-token"}'),
    ])
    monkeypatch.setattr(password_reset, 'urlopen', open_request)
    with app.app_context():
        settings = password_reset.mail_settings()
        assert REAL_DELIVER(settings, 'alex@example.com', 'private-token') == (True, True)
        assert REAL_DELIVER(settings, None, None) == (True, False)
    assert open_request.call_count == 3
    refresh_request, send_request, unknown_refresh = [call.args[0] for call in open_request.call_args_list]
    assert refresh_request.full_url == unknown_refresh.full_url == 'https://oauth2.googleapis.com/token'
    assert parse_qs(refresh_request.data.decode()) == {
        'client_id': ['test-client-id'], 'client_secret': ['private-client-secret'],
        'refresh_token': ['private-refresh-token'], 'grant_type': ['refresh_token'],
    }
    assert send_request.full_url == 'https://gmail.googleapis.com/gmail/v1/users/me/messages/send'
    assert send_request.get_header('Authorization') == 'Bearer private-access-token'
    message = message_from_bytes(base64.urlsafe_b64decode(json.loads(send_request.data)['raw']))
    assert message['From'] == 'sender@gmail.com' and message['To'] == 'alex@example.com'
    assert '#reset-token=private-token' in message.get_payload(decode=True).decode()
    for secret in ('private-access-token', 'private-refresh-token', 'private-client-secret', 'private-token'):
        assert secret not in caplog.text


@pytest.mark.parametrize('failure', ['http', 'network', 'malformed', 'missing-token', 'non-200'])
def test_gmail_refresh_failures_are_uniform_and_keep_secrets_out_of_logs(reset_clients, monkeypatch, caplog, failure):
    a, b, _ = reset_clients
    register(a)
    gmail_settings(monkeypatch)
    monkeypatch.setattr(password_reset, 'deliver_password_reset', REAL_DELIVER)
    response = response_mock(b'invalid-json' if failure == 'malformed' else b'{}', 503 if failure == 'non-200' else 200)
    open_request = Mock(return_value=response)
    if failure == 'http':
        open_request.side_effect = HTTPError('https://oauth2.googleapis.com/token', 401, 'private-refresh-token', {}, None)
    elif failure == 'network':
        open_request.side_effect = URLError('private-client-secret')
    monkeypatch.setattr(password_reset, 'urlopen', open_request)
    known, unknown = forgot(a), forgot(b, 'unknown@example.com')
    assert known.status_code == unknown.status_code == 503
    assert known.json == unknown.json
    assert open_request.call_count == 2
    with raw_state() as data:
        assert not data['passwordResetTokens']
    assert 'provider=gmail stage=oauth' in caplog.text
    if failure == 'http':
        assert 'http_status=401' in caplog.text
    for secret in ('private-refresh-token', 'private-client-secret', 'private-token'):
        assert secret not in caplog.text
    assert 'alex@example.com' not in caplog.text and 'sender@gmail.com' not in caplog.text


def test_gmail_send_failure_is_generic_and_preserves_previous_reset_link(reset_clients, monkeypatch, caplog):
    a, b, deliveries = reset_clients
    register(a)
    forgot(a)
    old_token = deliveries[-1][2]
    gmail_settings(monkeypatch)
    monkeypatch.setattr(password_reset, 'deliver_password_reset', REAL_DELIVER)
    open_request = Mock(side_effect=[
        response_mock(b'{"access_token":"private-access-token"}'),
        HTTPError('https://gmail.googleapis.com/gmail/v1/users/me/messages/send', 403, 'private-token', {}, None),
        response_mock(b'{"access_token":"private-access-token"}'),
    ])
    monkeypatch.setattr(password_reset, 'urlopen', open_request)
    known, unknown = forgot(a), forgot(b, 'unknown@example.com')
    assert known.status_code == unknown.status_code == 200
    assert known.json == unknown.json
    with raw_state() as data:
        assert set(data['passwordResetTokens']) == {digest(old_token)}
    assert 'provider=gmail stage=send http_status=403' in caplog.text
    assert 'private-token' not in caplog.text and 'private-access-token' not in caplog.text
    assert 'alex@example.com' not in caplog.text and 'sender@gmail.com' not in caplog.text


@pytest.mark.parametrize('route', ['forgot-password', 'request-password-code'])
@pytest.mark.parametrize('provider', ['gmail', 'resend', 'smtp'])
def test_invalid_sender_configuration_logs_only_setting_names_and_stage(reset_clients, monkeypatch, caplog, route, provider):
    owner, visitor, deliveries = reset_clients
    if provider == 'gmail':
        # An incomplete configuration still identifies the selected provider.
        monkeypatch.setitem(app.config, 'GMAIL_CLIENT_ID', 'private-client-id')
        invalid_fields = 'PASSWORD_RESET_FROM,GMAIL_CLIENT_SECRET,GMAIL_REFRESH_TOKEN'
    elif provider == 'resend':
        monkeypatch.setitem(app.config, 'RESEND_API_KEY', 'private-api-key')
        invalid_fields = 'PASSWORD_RESET_FROM'
    else:
        monkeypatch.setitem(app.config, 'SMTP_HOST', '')
        invalid_fields = 'SMTP_HOST'
    for client, email in ((owner, 'alex@example.com'), (visitor, 'unknown@example.com')):
        response = client.post('/api/auth/' + route, json={'email': email}, headers=HEADERS)
        assert response.status_code == 503
        assert response.json == {'error': password_reset.UNAVAILABLE_MESSAGE}
    assert not deliveries
    assert [record.getMessage() for record in caplog.records] == [
        f'Password reset email failed: provider={provider} stage=configuration invalid_fields={invalid_fields}'] * 2
    for private_value in ('private-client-id', 'private-api-key', 'alex@example.com', 'unknown@example.com'):
        assert private_value not in caplog.text


@pytest.fixture
def forbid_mail_diagnostic_side_effects(monkeypatch):
    """Configuration inspection must work without provider or database access."""
    import social
    import db

    blocked = []
    for module, name in ((password_reset, 'urlopen'), (password_reset, 'deliver_password_reset'),
                         (smtplib, 'SMTP'), (social, 'raw_state'), (db, 'get_connection')):
        probe = Mock(side_effect=AssertionError('Configuration inspection contacted an external service'))
        monkeypatch.setattr(module, name, probe)
        blocked.append(probe)
    yield
    for probe in blocked:
        probe.assert_not_called()


def test_mail_cli_partial_gmail_names_missing_credentials_despite_fallback_settings(
        reset_clients, monkeypatch, forbid_mail_diagnostic_side_effects):
    monkeypatch.setitem(app.config, 'GMAIL_CLIENT_ID', 'private-client-id')
    monkeypatch.setitem(app.config, 'RESEND_API_KEY', 'private-resend-key')
    monkeypatch.setitem(app.config, 'PASSWORD_RESET_FROM', 'private-sender@example.com')
    result = app.test_cli_runner().invoke(args=['password_reset', 'check-mail'])
    assert result.exit_code == 1
    assert 'Provider: gmail' in result.output
    assert 'Configuration: not ready' in result.output
    assert 'Missing or invalid settings: GMAIL_CLIENT_SECRET, GMAIL_REFRESH_TOKEN' in result.output
    for private_value in ('private-client-id', 'private-resend-key', 'private-sender@example.com'):
        assert private_value not in result.output
    assert 'SMTP_HOST' not in result.output and 'RESEND_API_KEY' not in result.output


def test_mail_cli_reports_all_invalid_smtp_names_without_values(
        reset_clients, monkeypatch, forbid_mail_diagnostic_side_effects):
    for name, value in {
        'SMTP_FROM': 'private-sender-invalid', 'SMTP_HOST': '',
        'SMTP_PORT': 'private-port-invalid', 'SMTP_USERNAME': 'private-user',
        'SMTP_PASSWORD': '', 'SMTP_USE_TLS': 'private-tls-invalid',
    }.items():
        monkeypatch.setitem(app.config, name, value)
    result = app.test_cli_runner().invoke(args=['password_reset', 'check-mail'])
    assert result.exit_code == 1
    assert 'Provider: smtp' in result.output
    assert ('Missing or invalid settings: SMTP_FROM, SMTP_HOST, SMTP_PORT, SMTP_PASSWORD, SMTP_USE_TLS'
            in result.output)
    for private_value in ('private-sender-invalid', 'private-port-invalid', 'private-user', 'private-tls-invalid'):
        assert private_value not in result.output


@pytest.mark.parametrize('provider', ['gmail', 'resend', 'smtp'])
def test_mail_cli_ready_configuration_does_not_check_connectivity_or_print_credentials(
        reset_clients, monkeypatch, forbid_mail_diagnostic_side_effects, provider):
    monkeypatch.setitem(app.config, 'PASSWORD_RESET_BASE_URL', '')
    private_values = []
    if provider == 'gmail':
        gmail_settings(monkeypatch)
        private_values = ['test-client-id', 'private-client-secret', 'private-refresh-token', 'sender@gmail.com']
    elif provider == 'resend':
        monkeypatch.setitem(app.config, 'RESEND_API_KEY', 'private-api-key')
        monkeypatch.setitem(app.config, 'PASSWORD_RESET_FROM', 'private-sender@example.com')
        private_values = ['private-api-key', 'private-sender@example.com']
    else:
        monkeypatch.setitem(app.config, 'SMTP_USERNAME', 'private-smtp-user')
        monkeypatch.setitem(app.config, 'SMTP_PASSWORD', 'private-smtp-password')
        private_values = ['smtp.example.com', 'accounts@example.com', 'private-smtp-user', 'private-smtp-password']
    result = app.test_cli_runner().invoke(args=['password_reset', 'check-mail'])
    assert result.exit_code == 0
    assert 'Provider: ' + provider in result.output
    assert 'Configuration: ready' in result.output
    assert 'Missing or invalid settings:' not in result.output
    assert 'delivery and provider authentication are not checked' in result.output
    for private_value in private_values:
        assert private_value not in result.output


@pytest.mark.parametrize('base_url', ['', 'http://untrusted.example/reset',
                                     'https://private-user:private-password@example.com/reset',
                                     'https://[invalid', 123])
def test_mail_cli_checks_url_only_for_legacy_links_without_printing_it(
        reset_clients, monkeypatch, forbid_mail_diagnostic_side_effects, base_url):
    monkeypatch.setitem(app.config, 'PASSWORD_RESET_BASE_URL', base_url)
    runner = app.test_cli_runner()
    assert runner.invoke(args=['password_reset', 'check-mail']).exit_code == 0
    result = runner.invoke(args=['password_reset', 'check-mail', '--legacy-links'])
    assert result.exit_code == 1
    assert 'Missing or invalid settings: PASSWORD_RESET_BASE_URL' in result.output
    if base_url:
        assert str(base_url) not in result.output
    monkeypatch.setitem(app.config, 'PASSWORD_RESET_BASE_URL', 'https://trusted.example/reset')
    assert runner.invoke(args=['password_reset', 'check-mail', '--legacy-links']).exit_code == 0


@pytest.mark.parametrize('route', ['forgot-password', 'request-password-code'])
def test_partial_gmail_endpoint_logs_missing_secrets_without_disabling_error(
        reset_clients, monkeypatch, caplog, route):
    owner, visitor, deliveries = reset_clients
    assert register(owner).status_code == 201
    monkeypatch.setitem(app.config, 'GMAIL_CLIENT_ID', 'private-client-id')
    monkeypatch.setitem(app.config, 'RESEND_API_KEY', 'private-fallback-key')
    monkeypatch.setitem(app.config, 'PASSWORD_RESET_FROM', 'private-sender@example.com')
    for client, email in ((owner, 'alex@example.com'), (visitor, 'unknown@example.com')):
        response = client.post('/api/auth/' + route, json={'email': email}, headers=HEADERS)
        assert response.status_code == 503
        assert response.json == {'error': password_reset.UNAVAILABLE_MESSAGE}
    assert not deliveries
    assert [record.getMessage() for record in caplog.records] == [
        'Password reset email failed: provider=gmail stage=configuration '
        'invalid_fields=GMAIL_CLIENT_SECRET,GMAIL_REFRESH_TOKEN'] * 2
    for private_value in ('private-client-id', 'private-fallback-key', 'private-sender@example.com',
                          'alex@example.com', 'unknown@example.com'):
        assert private_value not in caplog.text
