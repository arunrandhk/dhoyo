"""JWT signatures and server-side revocation protect every account session."""
import base64
import json
from pathlib import Path
import secrets
import sys
import time

import jwt
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import app
from auth import COOKIE, ISSUED_AT_LEEWAY, LIFETIME, digest
import social
from social import raw_state


HEADERS = {'X-Dhoyo-Request': '1'}
SECRET = 'jwt-regression-secret-which-is-long-enough-for-hs256-and-hs512-signatures'
EMAIL = 'jwt-player@example.com'
PASSWORD = 'test-password-with-private-characters'
ISSUER = 'dhoyo'
AUDIENCE = 'dhoyo-web'
REQUIRED_CLAIMS = {'sub', 'jti', 'iat', 'exp', 'iss', 'aud'}


@pytest.fixture
def clients(tmp_path, monkeypatch):
    monkeypatch.setenv('SPORTSPACE_SOCIAL_DB', str(tmp_path / 'jwt-security.sqlite'))
    monkeypatch.setenv('AUTH_JWT_SECRET', SECRET)
    monkeypatch.setitem(app.config, 'AUTH_JWT_SECRET', SECRET)
    monkeypatch.setitem(app.config, 'AUTH_TEST_DEMO', False)
    return app.test_client(), app.test_client()


def register(client):
    response = client.post('/api/auth/register', json={
        'name': 'JWT Test Player', 'email': EMAIL, 'password': PASSWORD,
        'sport': 'Football', 'city': 'Delhi', 'state': 'Delhi', 'country': 'India',
    }, headers=HEADERS, base_url='https://localhost')
    assert response.status_code == 201
    return response


def login(client):
    return client.post('/api/auth/login', json={
        'email': EMAIL, 'password': PASSWORD,
    }, headers=HEADERS, base_url='https://localhost')


def decode(token):
    return jwt.decode(token, SECRET, algorithms=['HS256'],
                      issuer=ISSUER, audience=AUDIENCE,
                      leeway=ISSUED_AT_LEEWAY,
                      options={'require': sorted(REQUIRED_CLAIMS)})


def fresh_claims():
    now = int(time.time())
    return {
        'sub': 'player-' + 'a' * 24, 'jti': secrets.token_urlsafe(32),
        'iat': now, 'exp': now + LIFETIME, 'iss': ISSUER, 'aud': AUDIENCE,
    }


def sign(claims, *, key=SECRET, algorithm='HS256'):
    return jwt.encode(claims, key, algorithm=algorithm)


def altered_payload(token):
    header, payload, signature = token.split('.')
    data = json.loads(base64.urlsafe_b64decode(payload + '=' * (-len(payload) % 4)))
    data['sub'] = 'player-' + 'b' * 24
    replacement = base64.urlsafe_b64encode(
        json.dumps(data, separators=(',', ':')).encode()).decode().rstrip('=')
    return '.'.join((header, replacement, signature))


def test_signed_cookie_contains_only_identity_and_expiry_not_credentials(clients, caplog):
    owner, _ = clients
    registered = register(owner)
    cookie = owner.get_cookie(COOKIE)
    claims = decode(cookie.value)

    assert jwt.get_unverified_header(cookie.value)['alg'] == 'HS256'
    assert set(claims) == REQUIRED_CLAIMS
    assert claims['sub'] == registered.json['userId']
    assert isinstance(claims['jti'], str) and claims['jti']
    assert isinstance(claims['iat'], int) and isinstance(claims['exp'], int)
    assert claims['exp'] - claims['iat'] == LIFETIME
    assert cookie.http_only and cookie.secure and cookie.same_site == 'Lax'
    assert EMAIL not in json.dumps(claims) and PASSWORD not in json.dumps(claims)
    assert set(registered.json) == {'userId', 'name', 'accountType', 'organisationId'}
    assert registered.json['accountType'] == 'player'
    assert registered.json['organisationId'] is None

    with raw_state() as data:
        account_hash = data['accounts'][EMAIL]['password_hash']
        session = data['sessions'][digest(cookie.value)]
        assert session['user_id'] == claims['sub']
        assert cookie.value not in json.dumps(data)
        assert PASSWORD not in json.dumps(data)
        assert account_hash.startswith('scrypt:')

    responses = [registered, owner.get('/api/auth/me'), owner.get('/api/arena'),
                 owner.get('/api/social/feed')]
    for response in responses:
        assert response.status_code in (200, 201)
        body = response.get_data(as_text=True)
        assert EMAIL not in body and PASSWORD not in body and account_hash not in body
        assert cookie.value not in body
    assert EMAIL not in caplog.text and PASSWORD not in caplog.text
    assert cookie.value not in caplog.text


@pytest.mark.parametrize('secret', ['', 'short-secret'])
def test_missing_or_short_signing_secret_fails_closed_without_creating_account(
        clients, monkeypatch, secret):
    visitor, _ = clients
    monkeypatch.setenv('AUTH_JWT_SECRET', secret)
    monkeypatch.setitem(app.config, 'AUTH_JWT_SECRET', secret)
    registration = visitor.post('/api/auth/register', json={
        'name': 'JWT Test Player', 'email': EMAIL, 'password': PASSWORD,
        'sport': 'Football', 'city': 'Delhi', 'state': 'Delhi', 'country': 'India',
    }, headers=HEADERS)
    assert registration.status_code == 503
    assert login(visitor).status_code == 503
    assert visitor.get_cookie(COOKIE) is None
    assert visitor.get('/health').status_code == 200
    with raw_state() as data:
        assert EMAIL not in data.get('accounts', {})
        assert not data.get('sessions', {})


@pytest.mark.parametrize('case', [
    'opaque', 'malformed', 'unsigned', 'wrong-algorithm', 'wrong-key', 'altered-payload',
    'expired', 'future-iat', 'invalid-lifetime', 'excessive-lifetime',
    'wrong-issuer', 'wrong-audience',
    'missing-sub', 'missing-jti', 'missing-iat', 'missing-exp', 'missing-iss', 'missing-aud',
    'empty-sub', 'empty-jti', 'non-string-sub', 'non-string-jti',
    'string-iat', 'string-exp', 'boolean-iat', 'boolean-exp',
])
def test_invalid_jwt_is_rejected_before_database_access(clients, monkeypatch, case):
    visitor, _ = clients
    claims = fresh_claims()
    if case == 'opaque':
        token = secrets.token_urlsafe(32)
    elif case == 'malformed':
        token = 'not-a-valid.jwt.signature'
    elif case == 'unsigned':
        token = sign(claims, key='', algorithm='none')
    elif case == 'wrong-algorithm':
        token = sign(claims, algorithm='HS512')
    elif case == 'wrong-key':
        token = sign(claims, key='another-test-secret-long-enough-for-hs256-signatures')
    elif case == 'altered-payload':
        token = altered_payload(sign(claims))
    else:
        if case == 'expired':
            claims.update(iat=int(time.time()) - 100, exp=int(time.time()) - 1)
        elif case == 'future-iat':
            claims.update(iat=int(time.time()) + 3600, exp=int(time.time()) + 7200)
        elif case == 'invalid-lifetime':
            claims['iat'] = claims['exp']
        elif case == 'excessive-lifetime':
            claims['exp'] = claims['iat'] + LIFETIME + 1
        elif case == 'wrong-issuer':
            claims['iss'] = 'another-application'
        elif case == 'wrong-audience':
            claims['aud'] = 'another-client'
        elif case.startswith('missing-'):
            claims.pop(case.removeprefix('missing-'))
        elif case.startswith('empty-'):
            claims[case.removeprefix('empty-')] = ''
        elif case.startswith('non-string-'):
            claims[case.removeprefix('non-string-')] = 123
        elif case.startswith('string-'):
            field = case.removeprefix('string-')
            claims[field] = str(claims[field])
        elif case.startswith('boolean-'):
            claims[case.removeprefix('boolean-')] = True
        token = sign(claims)

    def unexpected_database_access():
        raise AssertionError('Invalid JWT must be rejected before reading shared state')

    monkeypatch.setattr(social, 'raw_state', unexpected_database_access)
    visitor.set_cookie(COOKIE, token)
    assert visitor.get('/api/arena').status_code == 401
    assert visitor.get('/api/auth/me').json == {'userId': None}


@pytest.mark.parametrize('change', ['delete-session', 'expire-session', 'change-owner'])
def test_signed_jwt_still_requires_matching_live_database_session(clients, change):
    owner, _ = clients
    register(owner)
    token = owner.get_cookie(COOKIE).value
    assert decode(token)['sub'] == owner.get('/api/auth/me').json['userId']
    with raw_state() as data:
        session = data['sessions'][digest(token)]
        if change == 'delete-session':
            data['sessions'].pop(digest(token))
        elif change == 'expire-session':
            session['expires'] = 0
        else:
            session['user_id'] = 'player-' + 'b' * 24
    assert owner.get('/api/arena').status_code == 401
    assert owner.get('/api/auth/me').json == {'userId': None}


def test_valid_signature_without_issued_session_cannot_authenticate(clients):
    visitor, _ = clients
    visitor.set_cookie(COOKIE, sign(fresh_claims()))
    assert visitor.get('/api/arena').status_code == 401
    assert visitor.get('/api/auth/me').json == {'userId': None}


@pytest.mark.parametrize('rollback', [0.001, 1.1, ISSUED_AT_LEEWAY])
def test_small_clock_rollback_preserves_a_live_issued_session(clients, monkeypatch, rollback):
    import auth
    owner, _ = clients
    identity = register(owner).json
    claims = decode(owner.get_cookie(COOKIE).value)
    monkeypatch.setattr(auth.time, 'time', lambda: claims['iat'] - rollback)
    assert owner.get('/api/arena').status_code == 200
    assert owner.get('/api/auth/me').json['userId'] == identity['userId']
    # The tolerance never grants access after the persisted session is revoked.
    with raw_state() as data:
        data['sessions'].clear()
    assert owner.get('/api/arena').status_code == 401


@pytest.mark.parametrize('boundary', ['beyond-issuance-tolerance', 'exact-expiry', 'after-expiry'])
def test_clock_tolerance_keeps_future_and_expired_tokens_rejected_before_database_access(
        clients, monkeypatch, boundary):
    import auth
    owner, _ = clients
    register(owner)
    claims = decode(owner.get_cookie(COOKIE).value)
    timestamp = {'beyond-issuance-tolerance': claims['iat'] - ISSUED_AT_LEEWAY - 0.01,
                 'exact-expiry': claims['exp'], 'after-expiry': claims['exp'] + 1}[boundary]
    monkeypatch.setattr(auth.time, 'time', lambda: timestamp)

    def unexpected_database_access():
        raise AssertionError('Future and expired JWTs must be rejected before database access')

    monkeypatch.setattr(social, 'raw_state', unexpected_database_access)
    assert owner.get('/api/arena').status_code == 401
    assert owner.get('/api/auth/me').json == {'userId': None}


def test_login_rotation_and_logout_revoke_previously_issued_jwts(clients):
    owner, replay = clients
    player_id = register(owner).json['userId']
    original = owner.get_cookie(COOKIE).value
    response = login(owner)
    assert response.status_code == 200 and response.json == {
        'userId': player_id, 'name': 'JWT Test Player',
        'accountType': 'player', 'organisationId': None,
    }
    rotated = owner.get_cookie(COOKIE).value
    assert original != rotated
    assert decode(original)['jti'] != decode(rotated)['jti']
    replay.set_cookie(COOKIE, original)
    assert replay.get('/api/arena').status_code == 401
    assert owner.get('/api/arena').status_code == 200

    with raw_state() as data:
        assert digest(original) not in data['sessions']
        assert digest(rotated) in data['sessions']
    assert owner.post('/api/auth/logout', json={}, headers=HEADERS).status_code == 200
    assert owner.get_cookie(COOKIE) is None
    replay.set_cookie(COOKIE, rotated)
    assert replay.get('/api/arena').status_code == 401
    assert replay.get('/api/auth/me').json == {'userId': None}
