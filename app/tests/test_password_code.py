"""Email OTP recovery verifies ownership without exposing or persisting reset codes."""
import base64
from email import message_from_bytes
import json
from pathlib import Path
import re
import smtplib
import sys
import time
from unittest.mock import Mock

import pytest
from werkzeug.security import check_password_hash

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import app
from auth import COOKIE, digest
import password_reset
from social import raw_state


HEADERS = {'X-Dhoyo-Request': '1'}
PASSWORD = 'my-current-password'
NEW_PASSWORD = '  New pässword ⚽  '
REAL_DELIVER = password_reset.deliver_password_reset


@pytest.fixture
def clients(tmp_path, monkeypatch):
    monkeypatch.setenv('SPORTSPACE_SOCIAL_DB', str(tmp_path / 'password-code.sqlite'))
    monkeypatch.setitem(app.config, 'AUTH_TEST_DEMO', False)
    for name, value in {
        'SMTP_HOST': 'smtp.example.com', 'SMTP_PORT': '587',
        'SMTP_FROM': 'sender@gmail.com', 'SMTP_USERNAME': '', 'SMTP_PASSWORD': '',
        'SMTP_USE_TLS': 'true', 'RESEND_API_KEY': '', 'PASSWORD_RESET_FROM': '',
        'GMAIL_CLIENT_ID': '', 'GMAIL_CLIENT_SECRET': '', 'GMAIL_REFRESH_TOKEN': '',
        'PASSWORD_RESET_BASE_URL': 'https://dhoyo.example/index.html',
    }.items():
        monkeypatch.setitem(app.config, name, value)
    monkeypatch.setattr(password_reset.secrets, 'randbelow', lambda maximum: 1234)
    deliveries = []

    def deliver(settings, recipient, code):
        with raw_state() as data:
            data['deliveryOutsideTransaction'] = True
        deliveries.append((settings, recipient, code))
        return True, recipient is not None

    monkeypatch.setattr(password_reset, 'deliver_password_reset', deliver)
    return app.test_client(), app.test_client(), app.test_client(), deliveries


def register(client, email='alex@gmail.com'):
    response = client.post('/api/auth/register', json=dict(
        name='Alex', email=email, password=PASSWORD, sport='Football',
        city='Delhi', state='Delhi', country='India'), headers=HEADERS)
    assert response.status_code == 201
    return response.json['userId']


def request_code(client, email='alex@gmail.com', **kwargs):
    kwargs.setdefault('base_url', 'https://localhost')
    return client.post('/api/auth/request-password-code', json={'email': email}, headers=HEADERS, **kwargs)


def reset(client, challenge, code='001234', password=NEW_PASSWORD, **kwargs):
    kwargs.setdefault('base_url', 'https://localhost')
    return client.post('/api/auth/reset-password-code', json={
        'challengeId': challenge, 'code': code, 'password': password}, headers=HEADERS, **kwargs)


def login(client, password=PASSWORD, email='alex@gmail.com', **kwargs):
    kwargs.setdefault('base_url', 'https://localhost')
    return client.post('/api/auth/login', json={'email': email, 'password': password}, headers=HEADERS, **kwargs)


def test_request_is_generic_and_stores_only_hashed_code_and_challenge(clients, caplog):
    owner, visitor, _, deliveries = clients
    register(owner)
    known = request_code(owner, '  ALEX@GMAIL.COM  ')
    unknown = request_code(visitor, 'unknown@gmail.com')
    assert known.status_code == unknown.status_code == 200
    assert known.json['message'] == unknown.json['message'] == password_reset.CODE_REQUEST_MESSAGE
    assert set(known.json) == set(unknown.json) == {'message', 'challengeId'}
    assert known.json['challengeId'] != unknown.json['challengeId']
    for response in (known, unknown):
        assert re.fullmatch(r'[A-Za-z0-9_-]{43}', response.json['challengeId'])
        assert '001234' not in response.get_data(as_text=True)
    assert deliveries[0][0]['purpose'] == 'code'
    assert deliveries[0][1:] == ('alex@gmail.com', '001234')
    assert deliveries[1][1:] == (None, None)
    with raw_state() as data:
        assert set(data['passwordResetCodes']) == {digest(known.json['challengeId'])}
        record = data['passwordResetCodes'][digest(known.json['challengeId'])]
        assert record['active'] and record['attempts'] == 0
        assert record['code_hash'].startswith('scrypt:')
        assert check_password_hash(record['code_hash'], '001234')
        assert 590 < record['expires'] - time.time() <= 600
        assert data['deliveryOutsideTransaction']
        assert '001234' not in str(data)
        assert known.json['challengeId'] not in str(data)
        assert unknown.json['challengeId'] not in str(data)
    assert '001234' not in caplog.text
    assert reset(visitor, unknown.json['challengeId']).status_code == 400


def test_success_revokes_own_credentials_and_preserves_other_accounts(clients):
    owner, second_browser, unrelated, _ = clients
    player_id = register(owner)
    other_id = register(unrelated, email='sam@gmail.com')
    assert login(second_browser).status_code == 200
    challenge = request_code(owner).json['challengeId']
    other_challenge = request_code(unrelated, email='sam@gmail.com').json['challengeId']
    with raw_state() as data:
        data['passwordResetTokens'] = {
            digest('x' * 43): dict(email='alex@gmail.com', user_id=player_id,
                                   expires=time.time() + 1800, active=True),
            digest('y' * 43): dict(email='sam@gmail.com', user_id=other_id,
                                   expires=time.time() + 1800, active=True),
        }
        data['loginAttempts'] = {
            digest('alex@gmail.com|' + address): dict(count=10, until=time.time() + 900,
                                                     email_digest=digest('alex@gmail.com'))
            for address in ('127.0.0.1', '192.0.2.1')
        }
        data['loginAttempts']['unrelated'] = dict(count=2, until=time.time() + 900,
                                                 email_digest=digest('sam@gmail.com'))
    response = reset(owner, challenge)
    assert response.status_code == 200
    assert response.json == {'message': 'Your password has been reset. Sign in with your new password.'}
    assert owner.get_cookie(COOKIE) is None
    assert owner.get('/api/arena').status_code == second_browser.get('/api/arena').status_code == 401
    assert unrelated.get('/api/auth/me').json['userId'] == other_id
    with raw_state() as data:
        assert set(data['passwordResetTokens']) == {digest('y' * 43)}
        assert set(data['passwordResetCodes']) == {digest(other_challenge)}
        assert set(data['loginAttempts']) == {'unrelated'}
        assert all(session['user_id'] == other_id for session in data['sessions'].values())
        password_hash = data['accounts']['alex@gmail.com']['password_hash']
        assert password_hash.startswith('scrypt:') and check_password_hash(password_hash, NEW_PASSWORD)
        assert NEW_PASSWORD not in str(data)
    assert reset(second_browser, challenge).status_code == 400
    assert login(second_browser).status_code == 401
    assert login(second_browser, NEW_PASSWORD.strip()).status_code == 401
    for address in ('127.0.0.1', '192.0.2.1'):
        assert login(second_browser, NEW_PASSWORD,
                     environ_overrides={'REMOTE_ADDR': address}).status_code == 200
    assert login(unrelated, email='sam@gmail.com').status_code == 200


def test_fifth_correct_attempt_succeeds_and_sixth_attempt_after_five_wrong_is_rejected(clients, monkeypatch):
    owner, visitor, _, _ = clients
    register(owner)
    first = request_code(owner).json['challengeId']
    for index in range(4):
        assert reset(visitor, first, code='123456',
                     environ_overrides={'REMOTE_ADDR': f'192.0.2.{index}'}).status_code == 400
    assert reset(visitor, first).status_code == 200
    second = request_code(visitor).json['challengeId']
    for index in range(5):
        assert reset(visitor, second, code='123456',
                     environ_overrides={'REMOTE_ADDR': f'198.51.100.{index}'}).status_code == 400
    check = Mock(wraps=password_reset.check_password_hash)
    monkeypatch.setattr(password_reset, 'check_password_hash', check)
    assert reset(visitor, second).status_code == 400
    check.assert_called_once_with(password_reset.DUMMY_CODE_HASH, '001234')
    with raw_state() as data:
        assert data['passwordResetCodes'][digest(second)]['attempts'] == 5


def test_known_wrong_and_unknown_challenges_both_verify_outside_transaction(clients, monkeypatch):
    owner, visitor, _, _ = clients
    register(owner)
    known = request_code(owner).json['challengeId']
    unknown = request_code(visitor, 'unknown@gmail.com').json['challengeId']
    real_check = password_reset.check_password_hash
    checked_hashes = []

    def check_outside_transaction(password_hash, code):
        with raw_state() as data:
            data['verificationOutsideTransaction'] = True
        checked_hashes.append(password_hash)
        return real_check(password_hash, code)

    monkeypatch.setattr(password_reset, 'check_password_hash', check_outside_transaction)
    known_response = reset(visitor, known, code='123456')
    unknown_response = reset(visitor, unknown, code='123456')
    assert known_response.status_code == unknown_response.status_code == 400
    assert known_response.json == unknown_response.json == {'error': password_reset.INVALID_CODE_MESSAGE}
    assert len(checked_hashes) == 2
    assert checked_hashes[0].startswith('scrypt:')
    assert checked_hashes[1] == password_reset.DUMMY_CODE_HASH
    with raw_state() as data:
        assert data['verificationOutsideTransaction']
        assert data['passwordResetCodes'][digest(known)]['attempts'] == 1
        assert digest(unknown) not in data['passwordResetCodes']


def test_expiry_invalid_password_and_pending_code_cannot_change_account(clients):
    owner, visitor, _, _ = clients
    register(owner)
    challenge = request_code(owner).json['challengeId']
    assert reset(visitor, challenge, password='short').status_code == 400
    assert reset(visitor, challenge, password='x' * 129).status_code == 400
    with raw_state() as data:
        record = data['passwordResetCodes'][digest(challenge)]
        assert record['attempts'] == 0
        record['active'] = False
    assert reset(visitor, challenge).status_code == 400
    with raw_state() as data:
        record = data['passwordResetCodes'][digest(challenge)]
        record['active'] = True
        record['expires'] = 0
    assert reset(visitor, challenge).status_code == 400
    with raw_state() as data:
        assert not data['passwordResetCodes']
    assert login(visitor).status_code == 200


@pytest.mark.parametrize('code', [1234, None, [], '1234', '0012345', '００１２３４', ' 001234'])
def test_code_requires_exactly_six_ascii_digit_characters(clients, code):
    owner, visitor, _, _ = clients
    register(owner)
    challenge = request_code(owner).json['challengeId']
    assert reset(visitor, challenge, code=code).status_code == 400
    with raw_state() as data:
        assert data['passwordResetCodes'][digest(challenge)]['attempts'] == 1
    assert login(visitor).status_code == 200


@pytest.mark.parametrize('payload', [
    {}, [], {'email': None}, {'email': '@gmail.com'}, {'email': 'alex@localhost'},
    {'email': 'a@b@gmail.com'}, {'email': 'alex@gma\nil.com'},
    {'email': 'alex@gmail.com', 'userId': 'player-1'},
])
def test_request_requires_strict_valid_email_payload(clients, payload):
    owner, _, _, deliveries = clients
    response = owner.post('/api/auth/request-password-code', json=payload, headers=HEADERS)
    assert response.status_code == 400
    assert not deliveries


def test_reset_rejects_account_identifiers_and_missing_fields(clients):
    owner, visitor, _, _ = clients
    player_id = register(owner)
    challenge = request_code(owner).json['challengeId']
    payload = dict(challengeId=challenge, code='001234', password=NEW_PASSWORD)
    for invalid in ({}, [], {'email': 'alex@gmail.com', 'password': NEW_PASSWORD},
                    {**payload, 'userId': player_id}, {**payload, 'email': 'alex@gmail.com'}):
        assert visitor.post('/api/auth/reset-password-code', json=invalid, headers=HEADERS).status_code == 400
    assert login(visitor).status_code == 200


def test_request_limits_are_shared_with_legacy_recovery_and_expire(clients):
    owner, visitor, _, deliveries = clients
    register(owner)
    assert request_code(owner).status_code == 200
    assert owner.post('/api/auth/forgot-password', json={'email': 'alex@gmail.com'}, headers=HEADERS).status_code == 200
    assert request_code(owner).status_code == 200
    assert request_code(visitor, '  ALEX@GMAIL.COM  ').status_code == 429
    for index in range(17):
        assert request_code(visitor, f'unknown-{index}@gmail.com').status_code == 200
    response = request_code(visitor, 'another@gmail.com')
    assert response.status_code == 429 and response.headers['Retry-After'] == '900'
    assert len(deliveries) == 20
    with raw_state() as data:
        for entry in data['passwordResetRateLimits'].values():
            entry['until'] = 0
    assert request_code(visitor).status_code == 200


def test_submission_ip_limit_is_shared_with_legacy_recovery(clients):
    owner, visitor, _, _ = clients
    for _ in range(5):
        assert reset(owner, 'invalid-challenge').status_code == 400
        assert visitor.post('/api/auth/reset-password', json={
            'token': 'invalid-token', 'password': NEW_PASSWORD}, headers=HEADERS).status_code == 400
    response = reset(visitor, 'invalid-challenge')
    assert response.status_code == 429 and response.headers['Retry-After'] == '900'


def test_failed_send_preserves_old_code_and_success_replaces_it(clients, monkeypatch):
    owner, visitor, _, _ = clients
    register(owner)
    first = request_code(owner).json['challengeId']
    real_deliver = password_reset.deliver_password_reset
    monkeypatch.setattr(password_reset, 'deliver_password_reset', lambda *args: (True, False))
    failed = request_code(owner)
    assert failed.status_code == 200
    with raw_state() as data:
        assert set(data['passwordResetCodes']) == {digest(first)}
    monkeypatch.setattr(password_reset, 'deliver_password_reset', real_deliver)
    third = request_code(owner).json['challengeId']
    assert reset(visitor, first).status_code == 400
    assert reset(visitor, failed.json['challengeId']).status_code == 400
    assert reset(visitor, third).status_code == 200


def test_unavailable_configuration_and_provider_are_uniform(clients, monkeypatch):
    owner, visitor, _, deliveries = clients
    register(owner)
    monkeypatch.setitem(app.config, 'SMTP_HOST', '')
    assert request_code(owner).status_code == request_code(visitor, 'unknown@gmail.com').status_code == 503
    assert not deliveries
    monkeypatch.setitem(app.config, 'SMTP_HOST', 'smtp.example.com')
    monkeypatch.setitem(app.config, 'PASSWORD_RESET_BASE_URL', '')
    assert request_code(owner).status_code == 200  # Codes do not contain reset links.
    monkeypatch.setattr(password_reset, 'deliver_password_reset', lambda *args: (False, False))
    known, unknown = request_code(owner), request_code(visitor, 'unknown@gmail.com')
    assert known.status_code == unknown.status_code == 503 and known.json == unknown.json
    with raw_state() as data:
        assert len(data['passwordResetCodes']) == 1  # The earlier delivered code remains valid.


@pytest.mark.parametrize('revoker', ['change', 'link'])
def test_signed_in_and_legacy_password_updates_revoke_otp_codes(clients, revoker):
    owner, visitor, _, deliveries = clients
    register(owner)
    challenge = request_code(owner).json['challengeId']
    if revoker == 'change':
        response = owner.post('/api/auth/change-password', json={
            'currentPassword': PASSWORD, 'password': NEW_PASSWORD}, headers=HEADERS)
    else:
        owner.post('/api/auth/forgot-password', json={'email': 'alex@gmail.com'}, headers=HEADERS)
        response = owner.post('/api/auth/reset-password', json={
            'token': deliveries[-1][2], 'password': NEW_PASSWORD}, headers=HEADERS)
    assert response.status_code == 200
    assert reset(visitor, challenge).status_code == 400
    assert login(visitor, NEW_PASSWORD).status_code == 200


def test_password_change_during_delivery_prevents_pending_code_activation(clients, monkeypatch):
    owner, visitor, _, _ = clients
    register(owner)

    def deliver_then_change(settings, recipient, code):
        assert owner.post('/api/auth/change-password', json={
            'currentPassword': PASSWORD, 'password': NEW_PASSWORD}, headers=HEADERS).status_code == 200
        return True, True

    monkeypatch.setattr(password_reset, 'deliver_password_reset', deliver_then_change)
    challenge = request_code(owner).json['challengeId']
    with raw_state() as data:
        assert not data['passwordResetCodes']
    assert reset(visitor, challenge).status_code == 400
    assert login(visitor, NEW_PASSWORD).status_code == 200


def test_out_of_order_delivery_keeps_pending_codes_until_they_complete(clients, monkeypatch):
    owner, visitor, _, _ = clients
    register(owner)
    inner = []
    inside = [False]

    def deliver_nested(settings, recipient, code):
        if not inside[0]:
            inside[0] = True
            inner.append(request_code(visitor).json['challengeId'])
            with raw_state() as data:
                assert len(data['passwordResetCodes']) == 2
                assert sum(record['active'] for record in data['passwordResetCodes'].values()) == 1
        return True, True

    monkeypatch.setattr(password_reset, 'deliver_password_reset', deliver_nested)
    outer = request_code(owner).json['challengeId']
    with raw_state() as data:
        assert set(data['passwordResetCodes']) == {digest(outer)}
        assert data['passwordResetCodes'][digest(outer)]['active']
    assert reset(visitor, inner[0]).status_code == 400
    assert reset(visitor, outer).status_code == 200


def test_code_revocation_during_verification_prevents_password_overwrite(clients, monkeypatch):
    owner, visitor, _, _ = clients
    register(owner)
    challenge = request_code(owner).json['challengeId']
    real_check = password_reset.check_password_hash

    def revoke_then_check(password_hash, code):
        with raw_state() as data:
            data['passwordResetCodes'].clear()
        return real_check(password_hash, code)

    monkeypatch.setattr(password_reset, 'check_password_hash', revoke_then_check)
    assert reset(visitor, challenge).status_code == 400
    assert login(visitor).status_code == 200


def test_concurrent_correct_submissions_consume_code_once(clients, monkeypatch):
    owner, first, second, _ = clients
    register(owner)
    challenge = request_code(owner).json['challengeId']
    real_hash = password_reset.generate_password_hash
    inside = [False]
    winner_password = 'a-winner-password'

    def consume_then_hash(password, **kwargs):
        if not inside[0]:
            inside[0] = True
            assert reset(second, challenge, password=winner_password).status_code == 200
        return real_hash(password, **kwargs)

    monkeypatch.setattr(password_reset, 'generate_password_hash', consume_then_hash)
    assert reset(first, challenge).status_code == 400
    assert login(first, winner_password).status_code == 200
    assert login(first, NEW_PASSWORD).status_code == 401


def test_csrf_checks_apply_to_both_code_routes(clients):
    owner, _, _, _ = clients
    for route, payload in (
        ('request-password-code', {'email': 'alex@gmail.com'}),
        ('reset-password-code', {'challengeId': 'x' * 43, 'code': '001234', 'password': NEW_PASSWORD}),
    ):
        url = '/api/auth/' + route
        assert owner.post(url, json=payload).status_code == 403
        assert owner.post(url, data=payload, headers=HEADERS).status_code == 403
        assert owner.post(url, json=payload, headers={**HEADERS, 'Origin': 'https://attacker.example'}).status_code == 403


def response_mock(content):
    response = Mock(status=200)
    response.read.return_value = content
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    return response


@pytest.mark.parametrize('provider', ['gmail', 'resend', 'smtp'])
def test_provider_email_contains_code_instead_of_link_without_logging(clients, monkeypatch, caplog, provider):
    owner, _, _, _ = clients
    register(owner)
    monkeypatch.setattr(password_reset, 'deliver_password_reset', REAL_DELIVER)
    smtp = Mock()
    if provider == 'gmail':
        for name, value in {
            'GMAIL_CLIENT_ID': 'client-id', 'GMAIL_CLIENT_SECRET': 'private-secret',
            'GMAIL_REFRESH_TOKEN': 'private-refresh-token', 'PASSWORD_RESET_FROM': 'sender@gmail.com',
        }.items():
            monkeypatch.setitem(app.config, name, value)
        open_request = Mock(side_effect=[response_mock(b'{"access_token":"private-access-token"}'),
                                        response_mock(b'{"id":"message-id"}')])
        monkeypatch.setattr(password_reset, 'urlopen', open_request)
    elif provider == 'resend':
        monkeypatch.setitem(app.config, 'RESEND_API_KEY', 'private-api-key')
        monkeypatch.setitem(app.config, 'PASSWORD_RESET_FROM', 'sender@dhoyo.example')
        open_request = Mock(return_value=response_mock(b'{"id":"message-id"}'))
        monkeypatch.setattr(password_reset, 'urlopen', open_request)
    else:
        monkeypatch.setattr(smtplib, 'SMTP', Mock(return_value=smtp))
    response = request_code(owner)
    assert response.status_code == 200
    if provider == 'gmail':
        send_request = open_request.call_args.args[0]
        assert send_request.full_url == 'https://gmail.googleapis.com/gmail/v1/users/me/messages/send'
        message = message_from_bytes(base64.urlsafe_b64decode(json.loads(send_request.data)['raw']))
        subject, text = message['Subject'], message.get_payload(decode=True).decode()
        assert message['To'] == 'alex@gmail.com'
    elif provider == 'resend':
        payload = json.loads(open_request.call_args.args[0].data)
        subject, text = payload['subject'], payload['text']
        assert payload['to'] == ['alex@gmail.com']
    else:
        message = smtp.send_message.call_args.args[0]
        subject, text = message['Subject'], message.get_content()
        assert message['To'] == 'alex@gmail.com' and smtp.starttls.call_count == 1
    assert subject == 'Your Dhoyo password reset code'
    assert '001234' in text and '10 minutes' in text and '#reset-token=' not in text
    for secret in ('001234', 'private-secret', 'private-refresh-token', 'private-access-token', 'private-api-key'):
        assert secret not in caplog.text
    assert reset(owner, response.json['challengeId']).status_code == 200
