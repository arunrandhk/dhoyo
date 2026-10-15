"""Single-use email ownership links for newly created accounts."""
import re
import secrets
import time

from flask import Blueprint, jsonify, request

from auth import digest, valid_email
from password_reset import mail_settings, deliver_password_reset, log_mail_failure, configured_mail_provider

account_activation = Blueprint('account_activation', __name__, url_prefix='/api/auth')
TOKEN_LIFETIME = 24 * 60 * 60
RATE_WINDOW = 15 * 60
MAX_ENTRIES = 2048
MESSAGE = 'If this account needs activation, an activation link has been sent to its email.'
UNAVAILABLE = 'Account activation email is temporarily unavailable. Please try again later.'


def activation_settings():
    invalid = []
    settings = mail_settings(invalid_fields=invalid)
    if settings is None:
        log_mail_failure(configured_mail_provider(), 'configuration', invalid_fields=invalid)
        return None
    return dict(settings, purpose='account_activation')


def cleanup(data, now):
    tokens = data.setdefault('accountActivationTokens', {})
    for key in list(tokens):
        if tokens[key]['expires'] <= now:
            del tokens[key]
    rates = data.setdefault('accountActivationRates', {})
    for key in list(rates):
        if rates[key]['until'] <= now:
            del rates[key]
    return tokens, rates


def reserve_limits(data, specifications, now):
    _, rates = cleanup(data, now)
    entries = [(digest(scope), maximum) for scope, maximum in specifications]
    if (len(rates) + sum(key not in rates for key, _ in entries) > MAX_ENTRIES
            or any(rates.get(key, {}).get('count', 0) >= maximum for key, maximum in entries)):
        return False
    for key, _ in entries:
        record = rates.setdefault(key, dict(count=0, until=now + RATE_WINDOW))
        record['count'] += 1
    return True


def too_many():
    response = jsonify(error='Too many activation attempts. Try again in 15 minutes.')
    response.headers['Retry-After'] = str(RATE_WINDOW)
    return response, 429


def send_activation(email, player_id, settings, created=False):
    """Stage a hashed proof, release storage for delivery, then activate only on send."""
    from social import raw_state
    token = secrets.token_urlsafe(32)
    token_digest = digest(token)
    recipient = None
    with raw_state() as data:
        tokens, _ = cleanup(data, time.time())
        account = data.get('accounts', {}).get(email)
        if account and account['player_id'] == player_id and not account.get('email_verified', True):
            if len(tokens) >= MAX_ENTRIES:
                return jsonify(error=UNAVAILABLE, activationRequired=True, email=email), 503
            recipient = email
            tokens[token_digest] = dict(email=email, user_id=player_id,
                                       expires=time.time() + TOKEN_LIFETIME, active=False)
    # Provider errors never expose credentials, tokens or URLs in responses/logs.
    available, sent = deliver_password_reset(settings, recipient, token if recipient else None)
    if recipient:
        with raw_state() as data:
            tokens, _ = cleanup(data, time.time())
            record = tokens.get(token_digest)
            account = data.get('accounts', {}).get(email)
            if record and sent and account and account['player_id'] == player_id and not account.get('email_verified', True):
                for key in list(tokens):
                    if key != token_digest and tokens[key]['user_id'] == player_id:
                        del tokens[key]
                record['active'] = True
            elif record:
                del tokens[token_digest]
    if not available or (created and not sent):
        payload = dict(error=UNAVAILABLE)
        if created:
            payload.update(activationRequired=True, email=email)
        return jsonify(**payload), 503
    if created:
        return jsonify(activationRequired=True, email=email,
                       message='Check your email and activate your account before signing in.'), 201
    return jsonify(message=MESSAGE)


@account_activation.post('/resend-activation')
def resend_activation():
    from social import raw_state, body
    payload = body()
    if set(payload) != {'email'} or not valid_email(payload.get('email')):
        return jsonify(error='Enter a valid email address'), 400
    email = payload['email'].strip().casefold()
    settings = activation_settings()
    if settings is None:
        return jsonify(error=UNAVAILABLE), 503
    with raw_state() as data:
        if not reserve_limits(data, [('send-email:' + email, 3), ('send-ip:' + (request.remote_addr or ''), 20)], time.time()):
            return too_many()
        account = data.get('accounts', {}).get(email)
        player_id = account['player_id'] if account else None
    return send_activation(email, player_id, settings)


@account_activation.post('/activate-account')
def activate_account():
    from social import raw_state, body
    payload = body()
    token = payload.get('token')
    token_digest = digest(token) if isinstance(token, str) and re.fullmatch(r'[A-Za-z0-9_-]{43}', token) else None
    with raw_state() as data:
        if not reserve_limits(data, [('activate-ip:' + (request.remote_addr or ''), 20)], time.time()):
            return too_many()
        tokens, _ = cleanup(data, time.time())
        record = tokens.get(token_digest) if set(payload) == {'token'} else None
        account = data.get('accounts', {}).get(record['email']) if record else None
        if (not record or not record.get('active') or not account
                or account['player_id'] != record['user_id'] or account.get('email_verified', True)):
            return jsonify(error='This activation link is invalid or has expired. Request a new link.'), 400
        account['email_verified'] = True
        account['email_verified_at'] = int(time.time())
        for key in list(tokens):
            if tokens[key]['user_id'] == record['user_id']:
                del tokens[key]
    return jsonify(message='Your account is activated. You can now sign in.')
