"""Signed JWT cookies, revocable sessions, and password-hashed accounts."""
import hashlib
import ipaddress
import os
import re
import secrets
import time
from urllib.parse import urlsplit
import jwt
from flask import Blueprint, g, request, jsonify, current_app, has_request_context
from werkzeug.security import generate_password_hash, check_password_hash

auth = Blueprint('auth', __name__, url_prefix='/api/auth')
COOKIE = 'dhoyo_session'
LIFETIME = 7 * 86400
ISSUED_AT_LEEWAY = 5
JWT_ISSUER = 'dhoyo'
JWT_AUDIENCE = 'dhoyo-web'
LOGIN_RATE_WINDOW = 15 * 60
MAX_LOGIN_RATE_ENTRIES = 2048
MAX_LOGIN_IP_ATTEMPTS = 50
MAX_REGISTRATION_IP_ATTEMPTS = 10
REGISTRATION_RATE_WINDOW = 15 * 60
DUMMY_PASSWORD_HASH = generate_password_hash(secrets.token_urlsafe(32), method='scrypt')


def test_demo_enabled():
    return current_app.testing and current_app.config.get('AUTH_TEST_DEMO', False)


def render_terminates_tls():
    # Render's public ingress redirects HTTP and terminates HTTPS; its app port
    # is not publicly reachable. Do not trust client-supplied forwarded headers.
    return os.environ.get('RENDER') == 'true' and os.environ.get('RENDER_SERVICE_TYPE') == 'web'


def secure_transport():
    if request.is_secure or render_terminates_tls():
        return True
    if not (current_app.testing or current_app.config.get('AUTH_ALLOW_INSECURE_LOCAL',
                                                        os.environ.get('AUTH_ALLOW_INSECURE_LOCAL') == '1')):
        return False
    try:
        hostname = urlsplit(request.url).hostname or ''
    except ValueError:
        return False
    try:
        local_host = hostname == 'localhost' or ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        local_host = False
    try:
        local_peer = ipaddress.ip_address(request.remote_addr or '').is_loopback
    except ValueError:
        local_peer = False
    return local_host and local_peer


def jwt_secret():
    key = current_app.config.get('AUTH_JWT_SECRET', os.environ.get('AUTH_JWT_SECRET'))
    return key if isinstance(key, str) and len(key.encode('utf-8')) >= 32 else None


def verified_session_claims(token):
    """Validate before opening account state; JWT contents are never credentials."""
    key = jwt_secret()
    if not key or not isinstance(token, str) or len(token) > 2048:
        return None
    try:
        claims = jwt.decode(token, key, algorithms=['HS256'], issuer=JWT_ISSUER,
                            audience=JWT_AUDIENCE, options={
                                'require': ['sub', 'jti', 'iat', 'exp', 'iss', 'aud'],
                                'strict_aud': True,
                                # Use the same clock as the persisted revocation state.
                                'verify_exp': False, 'verify_iat': False,
                            })
    except jwt.InvalidTokenError:
        return None
    issued, expires = claims['iat'], claims['exp']
    if type(issued) is not int or type(expires) is not int:
        return None
    timestamp = time.time()
    # A small wall-clock correction must not invalidate a just-issued session.
    # Only issuance gets tolerance; expiry and database revocation remain strict.
    if (not 0 < expires - issued <= LIFETIME or
            issued > timestamp + ISSUED_AT_LEEWAY or timestamp >= expires):
        return None
    if not isinstance(claims['sub'], str) or not 1 <= len(claims['sub']) <= 100:
        return None
    if not isinstance(claims['jti'], str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}', claims['jti']):
        return None
    return claims


def current_user_id():
    if has_request_context():
        return getattr(g, 'user_id', 'demo-user' if test_demo_enabled() else None)
    return 'demo-user'


def digest(token):
    return hashlib.sha256(token.encode()).hexdigest()


def install_auth(app):
    app.register_blueprint(auth)
    from password_reset import password_reset
    app.register_blueprint(password_reset)
    from account_activation import account_activation
    from google_auth import google_auth
    app.register_blueprint(account_activation)
    app.register_blueprint(google_auth)

    @app.before_request
    def authenticate():
        if not (request.path.startswith('/api/') or request.path == '/users'):
            return
        if not secure_transport():
            return jsonify(error='Use HTTPS to access your account'), 403
        if test_demo_enabled():
            g.user_id = 'demo-user'
            return
        if request.method not in ('GET', 'HEAD', 'OPTIONS'):
            origin = request.headers.get('Origin')
            try:
                origin_matches = not origin or (urlsplit(origin).scheme in ('http', 'https')
                                                and urlsplit(origin).netloc == request.host)
            except ValueError:
                origin_matches = False
            if request.headers.get('Sec-Fetch-Site') == 'cross-site' or not origin_matches:
                return jsonify(error='Please submit from this website'), 403
            if not request.is_json or request.headers.get('X-Dhoyo-Request') != '1':
                return jsonify(error='JSON and X-Dhoyo-Request header required'), 403
        g.user_id = None
        if request.method == 'POST' and request.path in ('/api/auth/register', '/api/auth/login', '/api/auth/change-password') and not jwt_secret():
            current_app.logger.error('Authentication unavailable: configure AUTH_JWT_SECRET with at least 32 bytes')
            return jsonify(error='Sign-in is temporarily unavailable. Please try again later.'), 503
        # Native Android cannot use the browser's session cookie. Its connection
        # endpoint proves an explicitly approved, single-use ticket plus PKCE.
        if (request.method, request.path) in {('GET', '/api/play-games/config'), ('POST', '/api/play-games/connect')}:
            return
        token = request.cookies.get(COOKIE)
        claims = verified_session_claims(token) if token else None
        if claims:
            from social import raw_state
            with raw_state() as data:
                session = data.get('sessions', {}).get(digest(token))
                if session and session['user_id'] == claims['sub'] and session['expires'] > time.time():
                    account = next((value for value in data.get('accounts', {}).values()
                                    if value['player_id'] == session['user_id']), None)
                    if account and account.get('email_verified', True):
                        g.user_id = session['user_id']
        if request.path.startswith('/api/auth/'):
            from auth_envelope import PATHS, decrypt_request
            if request.method == 'POST' and request.path in PATHS:
                failure = decrypt_request()
                if failure is not None:
                    return failure
            return
        if not g.user_id:
            return jsonify(error='Sign in to continue'), 401
        if request.path == '/users':
            return jsonify(error='Use your own player profile'), 403
        if request.path == '/api/arena/awards':
            return jsonify(error='Organizer access is not enabled for player accounts'), 403


def account_identity(data, user_id):
    """Return account metadata from persisted identity, never from JWT roles."""
    account = next((value for value in data.get('accounts', {}).values()
                    if value['player_id'] == user_id), None)
    account_type = account.get('account_type', 'player') if account else 'player'
    from arena import ensure_arena
    profile = next((player for player in ensure_arena(data)['players']
                    if player['id'] == user_id), None)
    return dict(userId=user_id, name=profile['name'] if profile else '',
                accountType=account_type,
                organisationId=account.get('organisation_id') if account else None,
                emailVerified=account.get('email_verified', True) if account else False,
                googleLinked=bool(account and account.get('google_subject')))


def session_response(data, player_id, **payload):
    account = next((value for value in data.get('accounts', {}).values()
                    if value['player_id'] == player_id), None)
    if account and not account.get('email_verified', True):
        return jsonify(error='Activate your account using the link sent to your email.', activationRequired=True), 403
    issued = int(time.time())
    expires = issued + LIFETIME
    token = jwt.encode(dict(sub=player_id, jti=secrets.token_urlsafe(32), iat=issued,
                            exp=expires, iss=JWT_ISSUER, aud=JWT_AUDIENCE),
                       jwt_secret(), algorithm='HS256')
    sessions = data.setdefault('sessions', {})
    for key in list(sessions):
        if sessions[key]['expires'] < time.time():
            del sessions[key]
    previous = request.cookies.get(COOKIE)
    if previous:
        sessions.pop(digest(previous), None)
    sessions[digest(token)] = dict(user_id=player_id, expires=expires)
    response = jsonify(**account_identity(data, player_id), **payload)
    response.set_cookie(COOKIE, token, max_age=LIFETIME, httponly=True,
                        secure=request.is_secure or render_terminates_tls() or current_app.config.get('AUTH_COOKIE_SECURE', False), samesite='Lax', path='/')
    return response


@auth.get('/me')
def me():
    user_id = current_user_id()
    if not user_id or test_demo_enabled():
        return jsonify(userId=user_id)
    from social import raw_state
    with raw_state() as data:
        return jsonify(account_identity(data, user_id))


@auth.get('/encryption-key')
def encryption_key():
    from auth_envelope import public_challenge
    return public_challenge()


@auth.post('/register')
def register():
    from social import raw_state, body
    from account_activation import activation_settings, send_activation
    payload = body()
    name, email, password = payload.get('name'), payload.get('email'), payload.get('password')
    error = validate_onboarding(payload, require_phone=not legacy_registration_enabled())
    if error:
        return jsonify(error=error), 400
    if not valid_email(email):
        return jsonify(error='Enter your name and a valid email address'), 400
    if not isinstance(password, str) or not 10 <= len(password) <= 128:
        return jsonify(error='Use a password between 10 and 128 characters'), 400
    email = email.strip().casefold()
    settings = None if legacy_registration_enabled() else activation_settings()
    if settings is None and not legacy_registration_enabled():
        return jsonify(error='Account activation email is temporarily unavailable. Please try again later.'), 503
    with raw_state() as data:
        now = time.time()
        attempts = data.setdefault('registrationAttempts', {})
        for old in list(attempts):
            if attempts[old]['until'] <= now:
                del attempts[old]
        key = digest('register-ip:' + (request.remote_addr or ''))
        if ((key not in attempts and len(attempts) >= MAX_LOGIN_RATE_ENTRIES)
                or attempts.get(key, {}).get('count', 0) >= MAX_REGISTRATION_IP_ATTEMPTS):
            response = jsonify(error='Too many sign-up attempts. Try again in 15 minutes.')
            response.headers['Retry-After'] = str(REGISTRATION_RATE_WINDOW)
            return response, 429
        attempt = attempts.setdefault(key, dict(count=0, until=now + REGISTRATION_RATE_WINDOW))
        attempt['count'] += 1
    password_hash = generate_password_hash(password, method='scrypt')
    with raw_state() as data:
        accounts = data.setdefault('accounts', {})
        if email in accounts:
            return jsonify(error='An account with this email already exists. Sign in instead.'), 409
        player_id = create_account(data, payload, email, password_hash, verified=legacy_registration_enabled())
        if legacy_registration_enabled():
            return session_response(data, player_id), 201
    return send_activation(email, player_id, settings, created=True)


def legacy_registration_enabled():
    """Compatibility is opt-in and impossible outside an explicitly testing app."""
    return current_app.testing and current_app.config.get('AUTH_TEST_LEGACY_REGISTRATION', False)


def valid_email(email):
    return (isinstance(email, str) and len(email) <= 254 and email.count('@') == 1
            and bool(email.split('@')[0]) and '.' in email.rsplit('@', 1)[-1]
            and not any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in email))


def pending_account_ids(data):
    """Unactivated identities stay private; legacy and seeded profiles stay visible."""
    return {account['player_id'] for account in data.get('accounts', {}).values()
            if account.get('email_verified') is False}


def validate_onboarding(payload, require_phone=True):
    from social import string, SPORTS
    if not string(payload.get('name'), 100):
        return 'Enter your name (maximum 100 characters)'
    if payload.get('accountType', 'player') not in ('player', 'organisation'):
        return 'Choose a player or organisation account'
    if payload.get('accountType') == 'organisation' and not string(payload.get('organisationName'), 100):
        return 'Enter your organisation name (maximum 100 characters)'
    if payload.get('sport') not in SPORTS or any(not string(payload.get(k), 80) for k in ('city', 'state', 'country')):
        return 'Choose your sport and enter your city, state and country'
    if require_phone:
        phone = payload.get('phone')
        if isinstance(phone, str) and len(phone) <= 40 and re.fullmatch(r'\+[0-9 ()-]+', phone):
            phone = re.sub(r'[ ()-]', '', phone)
        if not isinstance(phone, str) or not re.fullmatch(r'\+[1-9][0-9]{7,14}', phone):
            return 'Enter your phone number with country code, for example +919876543210'
        payload['phone'] = phone
    return None


def create_account(data, payload, email, password_hash, verified=False, google_subject=None):
    """Persist only profile fields publicly; contact information stays on the account."""
    from arena import ensure_arena
    name = payload['name'].strip()
    account_type = payload.get('accountType', 'player')
    player_id = 'player-' + secrets.token_hex(12)
    account = dict(player_id=player_id, password_hash=password_hash, account_type=account_type,
                   email_verified=verified)
    if payload.get('phone'):
        account.update(phone=payload['phone'], phone_verified=False)
    if google_subject:
        account['google_subject'] = google_subject
    data.setdefault('accounts', {})[email] = account
    player = dict(id=player_id, name=name, initials=''.join(w[0] for w in name.split())[:2].upper(),
                  image='', avatar='', bio='', photoPrivacy='friends', awards=dict(Star=0, Diamond=0, Gold=0, Silver=0),
                  gamesPlayed=0, wins=0, supporters=[], teamId=None)
    player.update({k: payload[k].strip() for k in ('city', 'state', 'country', 'sport')})
    ensure_arena(data)['players'].append(player)
    data.setdefault('userPreferences', {})[player_id] = dict(sports=[player['sport']], following=[], **{k: player[k] for k in ('city', 'state', 'country')})
    if account_type == 'organisation':
        from organisations import create_organisation
        organisation = create_organisation(data, player_id, payload['organisationName'], player)
        account['organisation_id'] = organisation['id']
    return player_id


@auth.post('/login')
def login():
    from social import raw_state, body
    payload = body()
    email, password = payload.get('email'), payload.get('password')
    if not isinstance(email, str) or not isinstance(password, str) or len(email) > 254 or len(password) > 128:
        return jsonify(error='Email or password is incorrect'), 401
    email = email.strip().casefold()
    key = digest(email + '|' + (request.remote_addr or ''))
    ip_key = digest('login-ip:' + (request.remote_addr or ''))
    with raw_state() as data:
        # Reserve attempts before hashing, including concurrent and unknown-account requests.
        now = time.time()
        attempts = data.setdefault('loginAttempts', {})
        for old in list(attempts):
            if attempts[old]['until'] <= now:
                del attempts[old]
        if (len(attempts) + sum(entry not in attempts for entry in (key, ip_key)) > MAX_LOGIN_RATE_ENTRIES
                or attempts.get(key, {}).get('count', 0) >= 10
                or attempts.get(ip_key, {}).get('count', 0) >= MAX_LOGIN_IP_ATTEMPTS):
            response = jsonify(error='Too many attempts. Try again in 15 minutes.')
            response.headers['Retry-After'] = str(LOGIN_RATE_WINDOW)
            return response, 429
        attempt = attempts.setdefault(key, dict(count=0, until=now + LOGIN_RATE_WINDOW,
                                               email_digest=digest(email)))
        address_attempt = attempts.setdefault(ip_key, dict(count=0, until=now + LOGIN_RATE_WINDOW))
        attempt['count'] += 1
        address_attempt['count'] += 1
        account = data.get('accounts', {}).get(email)
        identity = (account['player_id'], account['password_hash']) if account else None

    # Equal expensive work for known and unknown accounts, outside the shared state lock.
    verified = check_password_hash(identity[1] if identity else DUMMY_PASSWORD_HASH, password)
    with raw_state() as data:
        account = data.get('accounts', {}).get(email)
        if not identity or not verified or not account or (account['player_id'], account['password_hash']) != identity:
            return jsonify(error='Email or password is incorrect'), 401
        if not account.get('email_verified', True):
            return jsonify(error='Activate your account using the link sent to your email.', activationRequired=True), 403
        attempts = data.setdefault('loginAttempts', {})
        attempts.pop(key, None)
        return session_response(data, account['player_id'])


@auth.post('/logout')
def logout():
    from social import raw_state
    with raw_state() as data:
        data.get('sessions', {}).pop(digest(request.cookies.get(COOKIE, '')), None)
    response = jsonify(ok=True)
    response.delete_cookie(COOKIE, path='/')
    return response


@auth.post('/change-password')
def change_password():
    from social import raw_state, body
    from password_reset import cleanup, consume_limits, revoke_account_credentials, RATE_WINDOW

    player_id = current_user_id()
    if not player_id:
        return jsonify(error='Sign in to change your password'), 401
    payload = body()
    if set(payload) != {'currentPassword', 'password'}:
        return jsonify(error='Enter your current password and a new password'), 400
    current_password, password = payload['currentPassword'], payload['password']
    if not isinstance(current_password, str) or not 1 <= len(current_password) <= 128:
        return jsonify(error='Enter your current password'), 400
    if not isinstance(password, str) or not 10 <= len(password) <= 128:
        return jsonify(error='Use a password between 10 and 128 characters'), 400

    session_digest = digest(request.cookies.get(COOKIE, ''))
    with raw_state() as data:
        now = time.time()
        session = data.get('sessions', {}).get(session_digest)
        if not session or session['user_id'] != player_id or session['expires'] <= now:
            return jsonify(error='Sign in to change your password'), 401
        owned_account = next(((email, account) for email, account in data.get('accounts', {}).items()
                              if account['player_id'] == player_id), None)
        if not owned_account:
            return jsonify(error='Sign in to change your password'), 401
        cleanup(data, now)
        limits = [('change-user:' + player_id, 10), ('change-ip:' + (request.remote_addr or ''), 10)]
        if not consume_limits(data, limits, now):
            response = jsonify(error='Too many password change attempts. Try again in 15 minutes.')
            response.headers['Retry-After'] = str(RATE_WINDOW)
            return response, 429
        email, account = owned_account
        previous_hash = account['password_hash']

    # Password hashing is expensive; do it outside the shared state transaction.
    if not check_password_hash(previous_hash, current_password):
        return jsonify(error='Your current password is incorrect'), 403
    password_hash = generate_password_hash(password, method='scrypt')
    with raw_state() as data:
        # A reset, sign-out or another password change may have occurred while hashing.
        session = data.get('sessions', {}).get(session_digest)
        if not session or session['user_id'] != player_id or session['expires'] <= time.time():
            return jsonify(error='Sign in to change your password'), 401
        account = data.get('accounts', {}).get(email)
        if not account or account['player_id'] != player_id:
            return jsonify(error='Sign in to change your password'), 401
        if account['password_hash'] != previous_hash:
            return jsonify(error='Your current password is incorrect'), 403
        account['password_hash'] = password_hash
        revoke_account_credentials(data, email, player_id)
        return session_response(data, player_id, message='Your password has been updated. Other sessions have been signed out.')
