"""Google Identity Services sign-in with explicit local account linking."""
import re
import secrets
import time

import jwt
from flask import Blueprint, current_app, jsonify, request
from werkzeug.security import generate_password_hash

from auth import (COOKIE, digest, jwt_secret, current_user_id, render_terminates_tls,
                  valid_email, validate_onboarding, create_account, session_response,
                  email_activation_bypass_enabled)
from password_reset import setting

google_auth = Blueprint('google_auth', __name__, url_prefix='/api/auth')
CHALLENGE_COOKIE = 'dhoyo_google_challenge'
SIGNUP_COOKIE = 'dhoyo_google_signup'
CHALLENGE_LIFETIME = 5 * 60
SIGNUP_LIFETIME = 10 * 60
MAX_ENTRIES = 2048
RATE_WINDOW = 15 * 60
GOOGLE_JWKS_URL = 'https://www.googleapis.com/oauth2/v3/certs'
# A fixed trusted endpoint and a general-purpose JWT library validate real Google
# signatures. Its cached signing keys respect rotation without exposing tokens.
GOOGLE_KEYS = jwt.PyJWKClient(GOOGLE_JWKS_URL, timeout=5, lifespan=300)


def client_id():
    value = setting('GOOGLE_CLIENT_ID')
    return value if isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9_-]+\.apps\.googleusercontent\.com', value) else None


def cookie(response, name, value, lifetime):
    response.set_cookie(name, value, max_age=lifetime, httponly=True, samesite='Strict', path='/api/auth',
                        secure=request.is_secure or render_terminates_tls() or current_app.config.get('AUTH_COOKIE_SECURE', False))


def cleanup(data, timestamp):
    for collection in ('googleAuthChallenges', 'googleSignupTickets'):
        entries = data.setdefault(collection, {})
        for key in list(entries):
            if entries[key]['expires'] <= timestamp:
                del entries[key]
    rates = data.setdefault('googleAuthRates', {})
    for key in list(rates):
        if rates[key]['until'] <= timestamp:
            del rates[key]
    return rates


def reserve_limit(data, purpose, maximum=30):
    timestamp = time.time()
    rates = cleanup(data, timestamp)
    key = digest(purpose + ':' + (request.remote_addr or ''))
    if ((key not in rates and len(rates) >= MAX_ENTRIES)
            or rates.get(key, {}).get('count', 0) >= maximum):
        return False
    record = rates.setdefault(key, dict(count=0, until=timestamp + RATE_WINDOW))
    record['count'] += 1
    return True


def unavailable():
    return jsonify(error='Google sign-in is not configured yet. Use email and password to continue.'), 503


def invalid():
    return jsonify(error='Google sign-in could not be verified. Please try again.'), 400


def limited():
    response = jsonify(error='Too many Google sign-in attempts. Try again in 15 minutes.')
    response.headers['Retry-After'] = str(RATE_WINDOW)
    return response, 429


@google_auth.get('/google/config')
def config():
    configured = client_id()
    response = jsonify(enabled=bool(configured and jwt_secret()), **({'clientId': configured} if configured and jwt_secret() else {}))
    response.headers['Cache-Control'] = 'no-store'
    return response


@google_auth.post('/google/challenge')
def challenge():
    from social import raw_state, body
    if not client_id() or not jwt_secret():
        return unavailable()
    if body() != {}:
        return invalid()
    browser = secrets.token_urlsafe(32)
    challenge_id = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    with raw_state() as data:
        if not reserve_limit(data, 'challenge'):
            return limited()
        challenges = data['googleAuthChallenges']
        if len(challenges) >= MAX_ENTRIES:
            return limited()
        previous = digest(request.cookies.get(CHALLENGE_COOKIE, ''))
        for key in list(challenges):
            if challenges[key]['browser'] == previous:
                del challenges[key]
        challenges[digest(challenge_id)] = dict(nonce=digest(nonce), browser=digest(browser),
            binding=digest(request.cookies.get(COOKIE, '')), expires=time.time() + CHALLENGE_LIFETIME)
    response = jsonify(challengeId=challenge_id, nonce=nonce, expiresIn=CHALLENGE_LIFETIME)
    cookie(response, CHALLENGE_COOKIE, browser, CHALLENGE_LIFETIME)
    response.headers['Cache-Control'] = 'no-store'
    return response


def verify_google_token(credential, audience, nonce_digest):
    """Perform network/signature work outside database transactions."""
    key = GOOGLE_KEYS.get_signing_key_from_jwt(credential)
    claims = jwt.decode(credential, key.key, algorithms=['RS256'], audience=audience,
                        issuer=['https://accounts.google.com', 'accounts.google.com'],
                        options={'require': ['sub', 'iat', 'exp', 'iss', 'aud', 'email', 'email_verified', 'nonce'],
                                 'strict_aud': True})
    if (not isinstance(claims.get('sub'), str) or not 1 <= len(claims['sub']) <= 255
            or not valid_email(claims.get('email')) or claims.get('email_verified') is not True
            or not isinstance(claims.get('nonce'), str)
            or not secrets.compare_digest(digest(claims['nonce']), nonce_digest)
            or (claims.get('azp') is not None and claims['azp'] != audience)):
        raise ValueError('Invalid identity claims')
    return dict(subject=claims['sub'], email=claims['email'].casefold(),
                name=claims.get('name', '') if isinstance(claims.get('name', ''), str) else '')


def verified_identity():
    from social import raw_state, body
    audience = client_id()
    if not audience or not jwt_secret():
        return None, unavailable()
    payload = body()
    if set(payload) != {'credential', 'challengeId'}:
        return None, invalid()
    credential, challenge_id = payload['credential'], payload['challengeId']
    if (not isinstance(credential, str) or not 1 <= len(credential) <= 12000
            or not isinstance(challenge_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}', challenge_id)):
        return None, invalid()
    with raw_state() as data:
        if not reserve_limit(data, 'verify'):
            return None, limited()
        challenges = data['googleAuthChallenges']
        record = challenges.get(digest(challenge_id))
        if (not record or not secrets.compare_digest(record['browser'], digest(request.cookies.get(CHALLENGE_COOKIE, '')))
                or not secrets.compare_digest(record['binding'], digest(request.cookies.get(COOKIE, '')))):
            return None, invalid()
        # Invalid credential submissions consume the nonce too; concurrent replays
        # cannot race network verification and reuse the same authentication proof.
        del challenges[digest(challenge_id)]
    try:
        return verify_google_token(credential, audience, record['nonce']), None
    except (jwt.PyJWTError, ValueError, TypeError, OSError):
        return None, invalid()


@google_auth.post('/google')
def sign_in():
    from social import raw_state
    identity, failure = verified_identity()
    if failure is not None:
        return failure
    with raw_state() as data:
        linked = next((account for account in data.get('accounts', {}).values()
                       if account.get('google_subject') == identity['subject']), None)
        if linked:
            return session_response(data, linked['player_id'])
        if identity['email'] in data.get('accounts', {}):
            return jsonify(error='This email already has a Dhoyo account. Sign in with your password, then connect Google from your profile.', linkRequired=True), 409
        cleanup(data, time.time())
        tickets = data['googleSignupTickets']
        if len(tickets) >= MAX_ENTRIES:
            return limited()
        tickets.pop(digest(request.cookies.get(SIGNUP_COOKIE, '')), None)
        ticket = secrets.token_urlsafe(32)
        tickets[digest(ticket)] = dict(identity, binding=digest(request.cookies.get(COOKIE, '')),
                                      expires=time.time() + SIGNUP_LIFETIME)
    response = jsonify(onboardingRequired=True, email=identity['email'], name=identity['name'][:100])
    cookie(response, SIGNUP_COOKIE, ticket, SIGNUP_LIFETIME)
    response.headers['Cache-Control'] = 'no-store'
    return response


@google_auth.post('/google/register')
def register():
    from social import raw_state, body
    if not client_id() or not jwt_secret():
        return unavailable()
    payload = body()
    error = validate_onboarding(payload)
    if error:
        return jsonify(error=error), 400
    skip_activation = email_activation_bypass_enabled()
    if not skip_activation:
        from account_activation import activation_settings
        settings = activation_settings()
        if settings is None:
            return jsonify(error='Account activation email is temporarily unavailable. Please try again later.'), 503
    ticket_digest = digest(request.cookies.get(SIGNUP_COOKIE, ''))
    with raw_state() as data:
        if not reserve_limit(data, 'register', maximum=10):
            return limited()
        ticket = data['googleSignupTickets'].get(ticket_digest)
        if not ticket or ticket['binding'] != digest(request.cookies.get(COOKIE, '')):
            return jsonify(error='Your Google sign-in has expired. Please sign in with Google again.'), 400
        identity = (ticket['subject'], ticket['email'])
    # Generate an unusable random password outside storage, only after checking
    # the browser ticket/rate limit. Email recovery may establish one later.
    password_hash = generate_password_hash(secrets.token_urlsafe(64), method='scrypt')
    with raw_state() as data:
        cleanup(data, time.time())
        ticket = data['googleSignupTickets'].get(ticket_digest)
        if (not ticket or (ticket['subject'], ticket['email']) != identity
                or ticket['binding'] != digest(request.cookies.get(COOKIE, ''))):
            return jsonify(error='Your Google sign-in has expired. Please sign in with Google again.'), 400
        if ticket['email'] in data.get('accounts', {}) or any(
                value.get('google_subject') == ticket['subject'] for value in data.get('accounts', {}).values()):
            del data['googleSignupTickets'][ticket_digest]
            return jsonify(error='This account already exists. Sign in to continue.'), 409
        email = ticket['email']
        player_id = create_account(data, payload, email, password_hash,
                                   verified=skip_activation, google_subject=ticket['subject'])
        del data['googleSignupTickets'][ticket_digest]
        if skip_activation:
            response = session_response(data, player_id)
    if not skip_activation:
        from account_activation import send_activation
        response = send_activation(email, player_id, settings, created=True)
    # send_activation may include a status tuple; delete the short-lived cookie
    # after either successful delivery or a recoverable provider failure.
    from flask import make_response
    response = make_response(response)
    response.delete_cookie(SIGNUP_COOKIE, path='/api/auth')
    return response


@google_auth.post('/google/link')
def link():
    from social import raw_state
    player_id = current_user_id()
    if not player_id:
        return jsonify(error='Sign in before connecting Google.'), 401
    identity, failure = verified_identity()
    if failure is not None:
        return failure
    with raw_state() as data:
        owned = next(((email, account) for email, account in data.get('accounts', {}).items()
                      if account['player_id'] == player_id), None)
        # Recheck persisted session state after Google verification releases storage.
        session = data.get('sessions', {}).get(digest(request.cookies.get(COOKIE, '')))
        if not owned or not session or session['user_id'] != player_id or session['expires'] <= time.time():
            return jsonify(error='Sign in before connecting Google.'), 401
        email, account = owned
        if identity['email'] != email:
            return jsonify(error='Choose the Google account with the same email as your Dhoyo account.'), 400
        if any(value.get('google_subject') == identity['subject'] and value['player_id'] != player_id
               for value in data.get('accounts', {}).values()):
            return jsonify(error='This Google account is already connected to another account.'), 409
        if account.get('google_subject') and account['google_subject'] != identity['subject']:
            return jsonify(error='Your account is already connected to Google.'), 409
        account['google_subject'] = identity['subject']
    return jsonify(message='Google is now connected to your account.', googleLinked=True)
