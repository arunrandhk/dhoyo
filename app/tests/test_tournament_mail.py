import base64
import json
import os
import smtplib
import sys
from email import message_from_bytes
from unittest.mock import Mock
from urllib.parse import parse_qs

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from app import app
import password_reset


CODE = '001234'
RECIPIENT = 'player@example.com'
TOURNAMENT_NAME = 'Delhi Cup — Under 19\r\nBcc: unrelated@example.com'
SUBJECT = 'Verify your Dhoyo tournament player email'


@pytest.fixture(autouse=True)
def mail_config(monkeypatch):
    for name, value in {
        'SMTP_HOST': 'smtp.example.com', 'SMTP_PORT': '587',
        'SMTP_FROM': 'accounts@example.com', 'SMTP_USERNAME': 'smtp-user',
        'SMTP_PASSWORD': 'private-smtp-password', 'SMTP_USE_TLS': 'true',
        'RESEND_API_KEY': '', 'PASSWORD_RESET_FROM': '',
        'GMAIL_CLIENT_ID': '', 'GMAIL_CLIENT_SECRET': '', 'GMAIL_REFRESH_TOKEN': '',
        'PASSWORD_RESET_BASE_URL': '',
    }.items():
        monkeypatch.setitem(app.config, name, value)

    def forbid_network(*args, **kwargs):
        raise AssertionError('Tournament mail tests must never contact a mail service')

    monkeypatch.setattr(password_reset, 'urlopen', forbid_network)
    monkeypatch.setattr(smtplib, 'SMTP', forbid_network)


def response_mock(content):
    response = Mock(status=200)
    response.read.return_value = content
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    return response


def assert_tournament_email(subject, text):
    assert subject == SUBJECT
    assert CODE in text
    assert TOURNAMENT_NAME.replace('\r\n', '\n') in text.replace('\r\n', '\n')
    assert 'verify your player email for participation' in text
    assert '6-digit' in text and '10 minutes' in text and 'can be used once' in text
    assert 'did not request this verification' in text and 'ignore this email' in text
    assert 'password reset' not in text.casefold() and '#reset-token=' not in text


@pytest.mark.parametrize('result', [(True, True), (True, False), (False, False)])
def test_wrapper_preserves_configuration_and_delivery_result(monkeypatch, result):
    settings = {'provider': 'smtp', 'sender': 'accounts@example.com', 'purpose': 'code'}
    original = dict(settings)
    deliver = Mock(return_value=result)
    monkeypatch.setattr(password_reset, 'deliver_password_reset', deliver)

    assert password_reset.deliver_tournament_player_code(settings, RECIPIENT, CODE, TOURNAMENT_NAME) == result

    assert settings == original
    deliver.assert_called_once_with(
        dict(settings, purpose='tournament_player', tournament_name=TOURNAMENT_NAME), RECIPIENT, CODE)


def test_tournament_code_is_sent_as_smtp_mime_without_requiring_reset_url(monkeypatch, caplog):
    smtp = Mock()
    constructor = Mock(return_value=smtp)
    monkeypatch.setattr(smtplib, 'SMTP', constructor)

    with app.app_context():
        settings = password_reset.mail_settings(require_base_url=False)
        assert settings is not None
        assert password_reset.deliver_tournament_player_code(
            settings, RECIPIENT, CODE, TOURNAMENT_NAME) == (True, True)

    constructor.assert_called_once_with('smtp.example.com', 587, timeout=10)
    assert smtp.starttls.call_args.kwargs['context'].check_hostname
    smtp.login.assert_called_once_with('smtp-user', 'private-smtp-password')
    smtp.send_message.assert_called_once()
    message = message_from_bytes(smtp.send_message.call_args.args[0].as_bytes())
    assert message['To'] == RECIPIENT and message['From'] == 'accounts@example.com'
    assert message['Bcc'] is None
    assert_tournament_email(message['Subject'], message.get_payload(decode=True).decode('utf-8'))
    smtp.close.assert_called_once()
    assert CODE not in caplog.text and 'private-smtp-password' not in caplog.text


def test_tournament_code_is_sent_as_resend_json(monkeypatch, caplog):
    monkeypatch.setitem(app.config, 'RESEND_API_KEY', 'private-api-key')
    monkeypatch.setitem(app.config, 'PASSWORD_RESET_FROM', 'accounts@dhoyo.example')
    open_request = Mock(return_value=response_mock(b'{"id":"message-id"}'))
    monkeypatch.setattr(password_reset, 'urlopen', open_request)

    with app.app_context():
        settings = password_reset.mail_settings(require_base_url=False)
        assert password_reset.deliver_tournament_player_code(
            settings, RECIPIENT, CODE, TOURNAMENT_NAME) == (True, True)

    open_request.assert_called_once()
    send_request = open_request.call_args.args[0]
    assert send_request.full_url == 'https://api.resend.com/emails'
    assert send_request.get_method() == 'POST'
    assert send_request.get_header('Authorization') == 'Bearer private-api-key'
    assert open_request.call_args.kwargs == {'timeout': 10}
    payload = json.loads(send_request.data)
    assert payload['to'] == [RECIPIENT] and payload['from'] == 'accounts@dhoyo.example'
    assert 'bcc' not in payload
    assert_tournament_email(payload['subject'], payload['text'])
    assert CODE not in caplog.text and 'private-api-key' not in caplog.text


def test_tournament_code_is_sent_as_gmail_mime(monkeypatch, caplog):
    for name, value in {
        'GMAIL_CLIENT_ID': 'client-id', 'GMAIL_CLIENT_SECRET': 'private-client-secret',
        'GMAIL_REFRESH_TOKEN': 'private-refresh-token', 'PASSWORD_RESET_FROM': 'sender@gmail.com',
    }.items():
        monkeypatch.setitem(app.config, name, value)
    open_request = Mock(side_effect=[
        response_mock(b'{"access_token":"private-access-token"}'),
        response_mock(b'{"id":"gmail-message-id"}'),
    ])
    monkeypatch.setattr(password_reset, 'urlopen', open_request)

    with app.app_context():
        settings = password_reset.mail_settings(require_base_url=False)
        assert password_reset.deliver_tournament_player_code(
            settings, RECIPIENT, CODE, TOURNAMENT_NAME) == (True, True)

    assert open_request.call_count == 2
    refresh_request, send_request = [call.args[0] for call in open_request.call_args_list]
    assert refresh_request.full_url == 'https://oauth2.googleapis.com/token'
    assert parse_qs(refresh_request.data.decode()) == {
        'client_id': ['client-id'], 'client_secret': ['private-client-secret'],
        'refresh_token': ['private-refresh-token'], 'grant_type': ['refresh_token'],
    }
    assert send_request.full_url == 'https://gmail.googleapis.com/gmail/v1/users/me/messages/send'
    assert send_request.get_header('Authorization') == 'Bearer private-access-token'
    message = message_from_bytes(base64.urlsafe_b64decode(json.loads(send_request.data)['raw']))
    assert message['To'] == RECIPIENT and message['From'] == 'sender@gmail.com'
    assert message['Bcc'] is None
    assert_tournament_email(message['Subject'], message.get_payload(decode=True).decode('utf-8'))
    assert all(call.kwargs == {'timeout': 10} for call in open_request.call_args_list)
    for secret in (CODE, 'private-client-secret', 'private-refresh-token', 'private-access-token'):
        assert secret not in caplog.text
