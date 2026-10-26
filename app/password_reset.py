"""Email ownership verification for single-use, expiring password resets."""
import base64
import json
import os
import re
import secrets
import smtplib
import ssl
import time
from email.message import EmailMessage
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import Request, urlopen

import click
from flask import Blueprint, current_app, jsonify, request
from werkzeug.security import check_password_hash, generate_password_hash

from auth import COOKIE, digest


password_reset = Blueprint('password_reset', __name__, url_prefix='/api/auth')
TOKEN_LIFETIME = 30 * 60
CODE_LIFETIME = 10 * 60
CODE_ATTEMPTS = 5
RATE_WINDOW = 15 * 60
MAX_RATE_ENTRIES = 2048
REQUEST_MESSAGE = 'If an account exists for that email, a password reset link has been sent.'
UNAVAILABLE_MESSAGE = 'Password reset is temporarily unavailable. Please try again later.'
INVALID_TOKEN_MESSAGE = 'This reset link is invalid or has expired. Request a new link.'
CODE_REQUEST_MESSAGE = 'If an account exists for that email, a password reset code has been sent.'
INVALID_CODE_MESSAGE = 'The code is invalid or has expired. Request a new code.'
# Unknown and unusable challenges must take the same verification work as real ones.
DUMMY_CODE_HASH = generate_password_hash(secrets.token_urlsafe(32), method='scrypt')


def setting(name, default=None):
    return current_app.config.get(name, os.environ.get(name, default))


def configured_mail_provider():
    if any(setting(name) for name in ('GMAIL_CLIENT_ID', 'GMAIL_CLIENT_SECRET', 'GMAIL_REFRESH_TOKEN')):
        return 'gmail'
    return 'resend' if setting('RESEND_API_KEY') else 'smtp'


def log_mail_failure(provider, stage, error=None, invalid_fields=None):
    """Log delivery diagnostics without provider bodies or account/recovery data."""
    detail = ''
    if isinstance(error, HTTPError) and type(error.code) is int and 100 <= error.code <= 599:
        detail = f' http_status={error.code}'
    elif isinstance(error, smtplib.SMTPException):
        detail = f' smtp_error={type(error).__name__}'
    if stage == 'configuration' and invalid_fields:
        detail += ' invalid_fields=' + ','.join(invalid_fields)
    current_app.logger.warning('Password reset email failed: provider=%s stage=%s%s', provider, stage, detail)


def mail_settings(require_base_url=True, invalid_fields=None):
    """Validate the selected provider; diagnostics contain setting names only."""
    invalid = []
    base_url = setting('PASSWORD_RESET_BASE_URL')
    if require_base_url:
        valid_base_url = isinstance(base_url, str) and bool(base_url)
        try:
            if valid_base_url:
                parsed = urlsplit(base_url)
                local_http = parsed.scheme == 'http' and parsed.hostname in ('localhost', '127.0.0.1', '::1')
                valid_base_url = (bool(parsed.hostname) and not parsed.username and not parsed.password
                                  and not parsed.query and not parsed.fragment
                                  and (parsed.scheme == 'https' or local_http)
                                  and not any(character.isspace() for character in base_url))
        except (ValueError, TypeError):
            valid_base_url = False
        if not valid_base_url:
            invalid.append('PASSWORD_RESET_BASE_URL')
    gmail = {name: setting(name) for name in ('GMAIL_CLIENT_ID', 'GMAIL_CLIENT_SECRET', 'GMAIL_REFRESH_TOKEN')}
    api_key = setting('RESEND_API_KEY')
    sender_name = 'PASSWORD_RESET_FROM' if any(gmail.values()) or api_key else 'SMTP_FROM'
    sender = setting(sender_name)
    if not isinstance(sender, str) or '@' not in sender or any(character in sender for character in '\r\n'):
        invalid.append(sender_name)
    if any(gmail.values()):
        for name, value in gmail.items():
            if not isinstance(value, str) or not value or any(character.isspace() for character in value):
                invalid.append(name)
        settings = dict(provider='gmail', sender=sender, base_url=base_url,
                        client_id=gmail['GMAIL_CLIENT_ID'], client_secret=gmail['GMAIL_CLIENT_SECRET'],
                        refresh_token=gmail['GMAIL_REFRESH_TOKEN'])
    elif api_key:
        if not isinstance(api_key, str) or any(character.isspace() for character in api_key):
            invalid.append('RESEND_API_KEY')
        settings = dict(provider='resend', api_key=api_key, sender=sender, base_url=base_url)
    else:
        host = setting('SMTP_HOST')
        if not isinstance(host, str) or not host:
            invalid.append('SMTP_HOST')
        port = None
        try:
            port = int(setting('SMTP_PORT', 587))
            if not 1 <= port <= 65535:
                invalid.append('SMTP_PORT')
        except (ValueError, TypeError):
            invalid.append('SMTP_PORT')
        username, password = setting('SMTP_USERNAME'), setting('SMTP_PASSWORD')
        if bool(username) != bool(password):
            invalid.append('SMTP_PASSWORD' if username else 'SMTP_USERNAME')
        tls = str(setting('SMTP_USE_TLS', 'true')).casefold()
        if tls not in ('true', 'false', '1', '0'):
            invalid.append('SMTP_USE_TLS')
        settings = dict(provider='smtp', host=host, port=port, sender=sender, base_url=base_url,
                        username=username, password=password, use_tls=tls in ('true', '1'))
    if invalid_fields is not None:
        invalid_fields.extend(invalid)
    return None if invalid else settings


@password_reset.cli.command('check-mail')
@click.option('--legacy-links', is_flag=True, help='Also validate the public URL required for reset links.')
def check_mail(legacy_links):
    """Check sender configuration without contacting a database or mail service."""
    invalid_fields = []
    settings = mail_settings(require_base_url=legacy_links, invalid_fields=invalid_fields)
    click.echo('Provider: ' + configured_mail_provider())
    click.echo('Configuration: ' + ('ready' if settings is not None else 'not ready'))
    if invalid_fields:
        click.echo('Missing or invalid settings: ' + ', '.join(invalid_fields))
    click.echo('Configuration check only; delivery and provider authentication are not checked.')
    if settings is None:
        raise click.exceptions.Exit(1)


def email_text(settings, token):
    if settings.get('purpose') == 'account_activation':
        activation_url = settings['base_url'] + '#activate-token=' + quote(token, safe='')
        return ('Activate your Dhoyo account using this link:\n\n' + activation_url +
                '\n\nThis link expires in 24 hours and can be used once. '
                'If you did not create this account, ignore this email.\n')
    if settings.get('purpose') == 'tournament_reminder':
        return settings['reminder_text']
    if settings.get('purpose') == 'tournament_activation':
        return ('Your captain invited you to participate in "' + settings['tournament_name'] +
                '" with team "' + settings['team_name'] + '".\n\n' +
                'Open this link and select Acknowledge participation:\n\n' + token +
                '\n\nThis link expires in 24 hours. Ignore it if you do not recognise this team.\n')
    if settings.get('purpose') == 'tournament_player':
        return ('Your 6-digit Dhoyo tournament email verification code is:\n\n' + token +
                '\n\nUse this code to verify your player email for participation in "' +
                settings['tournament_name'] + '". '
                'It expires in 10 minutes and can be used once. '
                'If you did not request this verification, you can ignore this email.\n')
    if settings.get('purpose') == 'code':
        return ('Your Dhoyo password reset code is:\n\n' + token +
                '\n\nEnter this code on the password reset screen. '
                'It expires in 10 minutes and can be used once. '
                'If you did not request a password reset, you can ignore this email.\n')
    reset_url = settings['base_url'] + '#reset-token=' + quote(token, safe='')
    return ('Use this link to choose a new Dhoyo password:\n\n' + reset_url +
            '\n\nThis link expires in 30 minutes and can be used once. '
            'If you did not request a password reset, you can ignore this email.\n')


def email_subject(settings):
    if settings.get('purpose') == 'account_activation':
        return 'Activate your Dhoyo account'
    if settings.get('purpose') == 'tournament_reminder':
        return settings['reminder_subject']
    if settings.get('purpose') == 'tournament_activation':
        return 'Acknowledge your Dhoyo tournament participation'
    if settings.get('purpose') == 'tournament_player':
        return 'Verify your Dhoyo tournament player email'
    return 'Your Dhoyo password reset code' if settings.get('purpose') == 'code' else 'Reset your Dhoyo password'


def email_message(settings, recipient, token):
    message = EmailMessage()
    message['Subject'] = email_subject(settings)
    message['From'] = settings['sender']
    message['To'] = recipient
    message.set_content(email_text(settings, token))
    return message


def json_response(response):
    if not 200 <= response.status < 300:
        raise ValueError('Unexpected delivery response')
    content = response.read(4097)
    if len(content) > 4096:
        raise ValueError('Unexpected delivery response size')
    result = json.loads(content)
    if not isinstance(result, dict):
        raise ValueError('Invalid delivery response')
    return result


def deliver_gmail_reset(settings, recipient, token):
    # Refresh for known and unknown accounts alike so provider authentication
    # failures never reveal which addresses have registered accounts.
    refresh_payload = urlencode(dict(
        client_id=settings['client_id'], client_secret=settings['client_secret'],
        refresh_token=settings['refresh_token'], grant_type='refresh_token'))
    refresh_request = Request('https://oauth2.googleapis.com/token', data=refresh_payload.encode('utf-8'),
                              headers={'Content-Type': 'application/x-www-form-urlencoded'}, method='POST')
    try:
        with urlopen(refresh_request, timeout=10) as response:
            result = json_response(response)
            access_token = result.get('access_token')
            if not isinstance(access_token, str) or not access_token or any(character.isspace() for character in access_token):
                raise ValueError('Invalid provider authentication response')
    except (HTTPError, URLError, OSError, ValueError) as error:
        log_mail_failure('gmail', 'oauth', error)
        return False, False
    if recipient is None:
        return True, False
    encoded = base64.urlsafe_b64encode(email_message(settings, recipient, token).as_bytes()).decode('ascii')
    send_request = Request('https://gmail.googleapis.com/gmail/v1/users/me/messages/send',
                           data=json.dumps({'raw': encoded}).encode('utf-8'),
                           headers={'Authorization': 'Bearer ' + access_token, 'Content-Type': 'application/json'},
                           method='POST')
    try:
        with urlopen(send_request, timeout=10) as response:
            result = json_response(response)
            if not isinstance(result.get('id'), str) or not result['id']:
                raise ValueError('Invalid delivery response')
        return True, True
    except (HTTPError, URLError, OSError, ValueError) as error:
        log_mail_failure('gmail', 'send', error)
        return True, False


def deliver_resend_reset(settings, recipient, token):
    # HTTPS supports hosts that block outbound SMTP. Do not email an unknown
    # account or probe unrelated APIs that require additional key permissions.
    if recipient is None:
        return True, False
    payload = {'from': settings['sender'], 'to': [recipient],
               'subject': email_subject(settings), 'text': email_text(settings, token)}
    send_request = Request('https://api.resend.com/emails', data=json.dumps(payload).encode('utf-8'),
                           headers={'Authorization': 'Bearer ' + settings['api_key'], 'Content-Type': 'application/json'},
                           method='POST')
    try:
        with urlopen(send_request, timeout=10) as response:
            result = json_response(response)
            if not isinstance(result.get('id'), str) or not result['id']:
                raise ValueError('Invalid delivery response')
        return True, True
    except (HTTPError, URLError, OSError, ValueError) as error:
        # Keep the response generic even if the configured provider fails;
        # errors only for registered accounts would reveal account existence.
        log_mail_failure('resend', 'send', error)
        return True, False


def deliver_password_reset(settings, recipient, token):
    """Deliver without exposing account existence through delivery errors.

    Gmail authentication and SMTP connectivity are checked for all requests.
    A failure during a known account's send retains the generic response.
    Never log a reset URL or provider credentials.
    """
    if settings['provider'] == 'gmail':
        return deliver_gmail_reset(settings, recipient, token)
    if settings['provider'] == 'resend':
        return deliver_resend_reset(settings, recipient, token)
    connection = None
    try:
        connection = smtplib.SMTP(settings['host'], settings['port'], timeout=10)
        if settings['use_tls']:
            connection.starttls(context=ssl.create_default_context())
        if settings['username']:
            connection.login(settings['username'], settings['password'])
    except (OSError, smtplib.SMTPException) as error:
        if connection:
            connection.close()
        log_mail_failure('smtp', 'connect', error)
        return False, False
    try:
        if recipient is None:
            return True, False
        connection.send_message(email_message(settings, recipient, token))
        return True, True
    except (OSError, smtplib.SMTPException) as error:
        log_mail_failure('smtp', 'send', error)
        return True, False
    finally:
        connection.close()


def deliver_tournament_player_code(settings, recipient, code, tournament_name):
    """Reuse the configured mail transport for tournament participation codes."""
    tournament_settings = dict(settings, purpose='tournament_player', tournament_name=tournament_name)
    return deliver_password_reset(tournament_settings, recipient, code)


def cleanup(data, now):
    tokens = data.setdefault('passwordResetTokens', {})
    for key in list(tokens):
        if tokens[key]['expires'] <= now:
            del tokens[key]
    codes = data.setdefault('passwordResetCodes', {})
    for key in list(codes):
        if codes[key]['expires'] <= now:
            del codes[key]
    limits = data.setdefault('passwordResetRateLimits', {})
    for key in list(limits):
        if limits[key]['until'] <= now:
            del limits[key]


def consume_limits(data, specifications, now):
    limits = data['passwordResetRateLimits']
    keys = [(digest(scope), maximum) for scope, maximum in specifications]
    if len(limits) + sum(key not in limits for key, _ in keys) > MAX_RATE_ENTRIES:
        return False
    if any(limits.get(key, {}).get('count', 0) >= maximum for key, maximum in keys):
        return False
    for key, _ in keys:
        entry = limits.setdefault(key, dict(count=0, until=now + RATE_WINDOW))
        entry['count'] += 1
    return True


def rate_limit_response():
    response = jsonify(error='Too many password reset attempts. Try again in 15 minutes.')
    response.headers['Retry-After'] = str(RATE_WINDOW)
    return response, 429


def valid_token(data, token_digest, now):
    record = data.get('passwordResetTokens', {}).get(token_digest)
    if not record or not record.get('active') or record['expires'] <= now:
        return None
    account = data.get('accounts', {}).get(record['email'])
    if not account or account['player_id'] != record['user_id']:
        return None
    return record


def valid_code_record(data, challenge_digest, now):
    record = data.get('passwordResetCodes', {}).get(challenge_digest)
    if not record or not record.get('active') or record['expires'] <= now:
        return None
    account = data.get('accounts', {}).get(record['email'])
    if not account or account['player_id'] != record['user_id']:
        return None
    return record


def revoke_account_credentials(data, email, player_id):
    """Invalidate all recovery proofs and sessions after a password update."""
    for collection in ('passwordResetTokens', 'passwordResetCodes', 'sessions'):
        records = data.get(collection, {})
        for key in list(records):
            if records[key]['user_id'] == player_id:
                del records[key]
    email_digest = digest(email)
    attempts = data.get('loginAttempts', {})
    for key in list(attempts):
        if attempts[key].get('email_digest') == email_digest:
            del attempts[key]
    attempts.pop(digest(email + '|' + (request.remote_addr or '')), None)


@password_reset.post('/request-password-code')
def request_password_code():
    from social import body, raw_state
    payload = body()
    if set(payload) != {'email'} or not isinstance(payload['email'], str):
        return jsonify(error='Enter a valid email address'), 400
    email = payload['email'].strip().casefold()
    if (len(email) > 254 or email.count('@') != 1 or not email.split('@')[0]
            or '.' not in email.rsplit('@', 1)[-1]
            or any(character.isspace() or ord(character) < 32 or ord(character) == 127 for character in email)):
        return jsonify(error='Enter a valid email address'), 400
    invalid_fields = []
    settings = mail_settings(require_base_url=False, invalid_fields=invalid_fields)
    if settings is None:
        log_mail_failure(configured_mail_provider(), 'configuration', invalid_fields=invalid_fields)
        return jsonify(error=UNAVAILABLE_MESSAGE), 503
    settings = dict(settings, purpose='code')
    with raw_state() as data:
        now = time.time()
        cleanup(data, now)
        limits = [('forgot-email:' + email, 3), ('forgot-ip:' + (request.remote_addr or ''), 20)]
        if not consume_limits(data, limits, now):
            return rate_limit_response()
        account = data.get('accounts', {}).get(email)
        identity = (account['player_id'], account['password_hash']) if account else None

    # Generate and hash even for unknown accounts to keep request behavior uniform.
    challenge = secrets.token_urlsafe(32)
    challenge_digest = digest(challenge)
    code = f'{secrets.randbelow(1_000_000):06d}'
    code_hash = generate_password_hash(code, method='scrypt')
    recipient = None
    with raw_state() as data:
        account = data.get('accounts', {}).get(email)
        if identity and account and (account['player_id'], account['password_hash']) == identity:
            data['passwordResetCodes'][challenge_digest] = dict(
                email=email, user_id=identity[0], code_hash=code_hash,
                expires=time.time() + CODE_LIFETIME, attempts=0, active=False)
            recipient = email
    # Delivery runs outside state transactions. An unsuccessful send keeps old codes usable.
    available, sent = deliver_password_reset(settings, recipient, code if recipient else None)
    if recipient:
        with raw_state() as data:
            cleanup(data, time.time())
            codes = data['passwordResetCodes']
            pending = codes.get(challenge_digest)
            account = data.get('accounts', {}).get(email)
            unchanged = account and (account['player_id'], account['password_hash']) == identity
            if pending and sent and unchanged:
                for key in list(codes):
                    if key != challenge_digest and codes[key]['user_id'] == pending['user_id'] and codes[key]['active']:
                        del codes[key]
                pending['active'] = True
            elif pending:
                del codes[challenge_digest]
    if not available:
        return jsonify(error=UNAVAILABLE_MESSAGE), 503
    return jsonify(message=CODE_REQUEST_MESSAGE, challengeId=challenge)


@password_reset.post('/reset-password-code')
def reset_password_code():
    from social import body, raw_state
    payload = body()
    if set(payload) != {'challengeId', 'code', 'password'}:
        return jsonify(error='Enter your reset code and a new password'), 400
    challenge, code, password = payload['challengeId'], payload['code'], payload['password']
    if not isinstance(password, str) or not 10 <= len(password) <= 128:
        return jsonify(error='Use a password between 10 and 128 characters'), 400
    challenge_digest = digest(challenge) if isinstance(challenge, str) and re.fullmatch(r'[A-Za-z0-9_-]{43}', challenge) else None
    valid_code_format = isinstance(code, str) and re.fullmatch(r'[0-9]{6}', code)
    with raw_state() as data:
        now = time.time()
        cleanup(data, now)
        if not consume_limits(data, [('reset-ip:' + (request.remote_addr or ''), 10)], now):
            return rate_limit_response()
        record = valid_code_record(data, challenge_digest, now) if challenge_digest else None
        code_hash, identity = None, None
        if record and record['attempts'] < CODE_ATTEMPTS:
            # Reserve before hashing so parallel guesses cannot exceed the shared challenge limit.
            record['attempts'] += 1
            code_hash = record['code_hash']
            identity = (record['email'], record['user_id'])
    if not challenge_digest or not valid_code_format:
        return jsonify(error=INVALID_CODE_MESSAGE), 400
    verified = check_password_hash(code_hash or DUMMY_CODE_HASH, code)
    if not code_hash or not verified:
        return jsonify(error=INVALID_CODE_MESSAGE), 400
    password_hash = generate_password_hash(password, method='scrypt')
    with raw_state() as data:
        record = valid_code_record(data, challenge_digest, time.time())
        if not record or record['code_hash'] != code_hash or (record['email'], record['user_id']) != identity:
            return jsonify(error=INVALID_CODE_MESSAGE), 400
        email, player_id = identity
        data['accounts'][email]['password_hash'] = password_hash
        revoke_account_credentials(data, email, player_id)
    response = jsonify(message='Your password has been reset. Sign in with your new password.')
    response.delete_cookie(COOKIE, path='/')
    return response


@password_reset.post('/forgot-password')
def forgot_password():
    from social import body, raw_state
    email = body().get('email')
    if not isinstance(email, str):
        return jsonify(error='Enter a valid email address'), 400
    email = email.strip().casefold()
    if len(email) > 254 or '@' not in email or '.' not in email.rsplit('@', 1)[-1] or any(character.isspace() for character in email):
        return jsonify(error='Enter a valid email address'), 400
    invalid_fields = []
    settings = mail_settings(invalid_fields=invalid_fields)
    if settings is None:
        log_mail_failure(configured_mail_provider(), 'configuration', invalid_fields=invalid_fields)
        return jsonify(error=UNAVAILABLE_MESSAGE), 503
    now = time.time()
    token, token_digest, recipient = None, None, None
    with raw_state() as data:
        cleanup(data, now)
        limits = [('forgot-email:' + email, 3), ('forgot-ip:' + (request.remote_addr or ''), 20)]
        if not consume_limits(data, limits, now):
            return rate_limit_response()
        account = data.get('accounts', {}).get(email)
        if account:
            token = secrets.token_urlsafe(32)
            token_digest, recipient = digest(token), email
            data['passwordResetTokens'][token_digest] = dict(
                email=email, user_id=account['player_id'], expires=now + TOKEN_LIFETIME, active=False)
    # Email transport can block; release the database transaction first.
    available, sent = deliver_password_reset(settings, recipient, token)
    if token_digest:
        with raw_state() as data:
            cleanup(data, time.time())
            tokens = data['passwordResetTokens']
            pending = tokens.get(token_digest)
            if pending and sent:
                for key in list(tokens):
                    if key != token_digest and tokens[key]['user_id'] == pending['user_id']:
                        del tokens[key]
                pending['active'] = True
            elif pending:
                del tokens[token_digest]
    if not available:
        return jsonify(error=UNAVAILABLE_MESSAGE), 503
    return jsonify(message=REQUEST_MESSAGE)


@password_reset.post('/reset-password')
def reset_password():
    from social import body, raw_state
    payload = body()
    token, password = payload.get('token'), payload.get('password')
    if not isinstance(password, str) or not 10 <= len(password) <= 128:
        return jsonify(error='Use a password between 10 and 128 characters'), 400
    token_digest = digest(token) if isinstance(token, str) and re.fullmatch(r'[A-Za-z0-9_-]{43}', token) else None
    with raw_state() as data:
        now = time.time()
        cleanup(data, now)
        if not consume_limits(data, [('reset-ip:' + (request.remote_addr or ''), 10)], now):
            return rate_limit_response()
        if not token_digest or not valid_token(data, token_digest, now):
            return jsonify(error=INVALID_TOKEN_MESSAGE), 400
    password_hash = generate_password_hash(password)
    with raw_state() as data:
        # Recheck after hashing so concurrent reset submissions stay single-use.
        record = valid_token(data, token_digest, time.time())
        if not record:
            return jsonify(error=INVALID_TOKEN_MESSAGE), 400
        email, player_id = record['email'], record['user_id']
        data['accounts'][email]['password_hash'] = password_hash
        revoke_account_credentials(data, email, player_id)
    response = jsonify(message='Your password has been reset. Sign in with your new password.')
    response.delete_cookie(COOKIE, path='/')
    return response
