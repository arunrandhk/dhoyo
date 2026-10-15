"""Required account details and activation run with production onboarding rules."""
import json
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import app
import auth
import account_activation
import google_auth
import password_reset
import social

HEADERS = {'X-Dhoyo-Request': '1'}
EMAIL = 'onboarding@example.invalid'
PASSWORD = 'synthetic-onboarding-password'
CLIENT_ID = 'synthetic-client.apps.googleusercontent.com'
PROFILE = dict(name='New Player', phone='+91 98765 43210', sport='Football',
               city='Pune', state='Maharashtra', country='India')


def post(client, route, payload):
    return client.post('/api/auth/' + route, json=payload, headers=HEADERS, base_url='https://localhost')


def signup(client, **changes):
    values = dict(PROFILE, email=EMAIL, password=PASSWORD)
    values.update(changes)
    return post(client, 'register', values)


def activate(client, token):
    return post(client, 'activate-account', {'token': token})


def login(client):
    return post(client, 'login', {'email': EMAIL, 'password': PASSWORD})


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv('SPORTSPACE_SOCIAL_DB', str(tmp_path / 'onboarding.sqlite'))
    monkeypatch.setitem(app.config, 'AUTH_TEST_DEMO', False)
    monkeypatch.setitem(app.config, 'AUTH_TEST_LEGACY_REGISTRATION', False)
    for key in ('GMAIL_CLIENT_ID', 'GMAIL_CLIENT_SECRET', 'GMAIL_REFRESH_TOKEN'):
        monkeypatch.delenv(key, raising=False)
        monkeypatch.setitem(app.config, key, None)
    monkeypatch.setitem(app.config, 'RESEND_API_KEY', 'synthetic-resend-key')
    monkeypatch.setitem(app.config, 'PASSWORD_RESET_FROM', 'Dhoyo <noreply@example.invalid>')
    monkeypatch.setitem(app.config, 'PASSWORD_RESET_BASE_URL', 'https://dhoyo.example.invalid/ring')
    monkeypatch.setitem(app.config, 'GOOGLE_CLIENT_ID', CLIENT_ID)
    sent = []
    def delivery(settings, email, token):
        if email:
            sent.append(dict(settings=settings, email=email, token=token))
        return True, bool(email)
    monkeypatch.setattr(account_activation, 'deliver_password_reset', delivery)
    return SimpleNamespace(owner=app.test_client(), visitor=app.test_client(), sent=sent)


def test_password_signup_requires_email_activation_and_keeps_phone_private(setup):
    result = signup(setup.owner)
    assert result.status_code == 201
    assert result.json['activationRequired'] is True and result.json['email'] == EMAIL
    assert setup.owner.get_cookie(auth.COOKIE) is None
    assert setup.owner.get('/api/arena', base_url='https://localhost').status_code == 401
    assert login(setup.owner).status_code == 403
    with social.raw_state() as data:
        account = data['accounts'][EMAIL]
        assert account['phone'] == '+919876543210'
        assert account['phone_verified'] is False
        assert account['email_verified'] is False
        player = next(p for p in data['arena']['players'] if p['id'] == account['player_id'])
        assert 'phone' not in player and 'email' not in player
        proof = setup.sent[-1]['token']
        assert proof not in json.dumps(data)
        assert data['accountActivationTokens'][auth.digest(proof)]['active'] is True
    assert proof not in result.get_data(as_text=True)
    assert activate(setup.owner, proof).status_code == 200
    assert setup.owner.get_cookie(auth.COOKIE) is None
    assert login(setup.owner).status_code == 200
    assert setup.owner.get('/api/auth/me', base_url='https://localhost').json['emailVerified'] is True
    assert activate(setup.visitor, proof).status_code == 400


@pytest.mark.parametrize('field,value', [('name', ''), ('phone', ''), ('phone', '9876543210'),
    ('phone', '+019876543210'), ('phone', '+919876543210ext22'), ('phone', '+919876543210\n'),
    ('sport', 'Unknown'), ('city', ''), ('state', ''), ('country', ''), ('accountType', 'admin'),
    ('email', 'bad@invalid'), ('email', 'a@b.invalid\n')])
def test_required_signup_details_validated(setup, field, value):
    values = dict(PROFILE, email=EMAIL, password=PASSWORD)
    values[field] = value
    assert post(setup.owner, 'register', values).status_code == 400
    with social.raw_state() as data:
        assert EMAIL not in data.get('accounts', {})
    assert setup.sent == []


def test_organisation_signup_requires_name_and_activation(setup):
    assert signup(setup.owner, accountType='organisation').status_code == 400
    result = signup(setup.owner, accountType='organisation', organisationName='Play Club')
    assert result.status_code == 201 and result.json['activationRequired']
    assert activate(setup.owner, setup.sent[-1]['token']).status_code == 200
    response = login(setup.owner)
    assert response.json['accountType'] == 'organisation'
    assert response.json['organisationId']


def test_activation_expiry_resend_invalidation_and_generic_unknown_response(setup):
    signup(setup.owner)
    old = setup.sent[-1]['token']
    assert post(setup.owner, 'resend-activation', {'email': EMAIL}).status_code == 200
    fresh = setup.sent[-1]['token']
    assert activate(setup.owner, old).status_code == 400
    known = post(setup.owner, 'resend-activation', {'email': EMAIL})
    unknown = post(setup.owner, 'resend-activation', {'email': 'unknown@example.invalid'})
    assert known.status_code == unknown.status_code == 200
    assert known.json == unknown.json
    with social.raw_state() as data:
        for record in data['accountActivationTokens'].values():
            record['expires'] = time.time() - 1
    assert activate(setup.owner, setup.sent[-1]['token']).status_code == 400
    assert post(setup.owner, 'resend-activation', {'email': EMAIL}).status_code == 200
    assert post(setup.owner, 'resend-activation', {'email': EMAIL}).status_code == 429
    assert fresh != old


def test_missing_mail_configuration_fails_closed_without_creating_account(setup, monkeypatch):
    monkeypatch.setitem(app.config, 'PASSWORD_RESET_BASE_URL', None)
    response = signup(setup.owner)
    assert response.status_code == 503
    with social.raw_state() as data:
        assert EMAIL not in data.get('accounts', {})


def test_mail_failure_leaves_recoverable_pending_account_without_live_token(setup, monkeypatch):
    monkeypatch.setattr(account_activation, 'deliver_password_reset', lambda *_: (True, False))
    response = signup(setup.owner)
    assert response.status_code == 503 and response.json['activationRequired']
    with social.raw_state() as data:
        assert data['accounts'][EMAIL]['email_verified'] is False
        assert data['accountActivationTokens'] == {}
    assert login(setup.owner).status_code == 403


def test_delivery_outside_shared_state_and_failed_resend_preserves_old_token(setup, monkeypatch):
    signup(setup.owner)
    previous = setup.sent[-1]['token']
    original = social.raw_state
    depth = [0]
    @contextmanager
    def tracked():
        with original() as data:
            depth[0] += 1
            try:
                yield data
            finally:
                depth[0] -= 1
    monkeypatch.setattr(social, 'raw_state', tracked)
    def fail_delivery(*_):
        assert depth[0] == 0
        return True, False
    monkeypatch.setattr(account_activation, 'deliver_password_reset', fail_delivery)
    assert post(setup.owner, 'resend-activation', {'email': EMAIL}).status_code == 200
    assert activate(setup.owner, previous).status_code == 200


def test_activation_throttle_and_pending_account_cannot_reuse_session(setup):
    signup(setup.owner)
    for _ in range(20):
        assert activate(setup.visitor, 'wrong').status_code == 400
    assert activate(setup.visitor, 'wrong').status_code == 429
    # Even a persisted validly signed session cannot bypass account activation.
    with social.raw_state() as data:
        player_id = data['accounts'][EMAIL]['player_id']
    issued = int(time.time())
    token = jwt.encode(dict(sub=player_id, jti='a' * 43, iat=issued, exp=issued + 300,
                            iss=auth.JWT_ISSUER, aud=auth.JWT_AUDIENCE), app.config.get('AUTH_JWT_SECRET') or __import__('os').environ['AUTH_JWT_SECRET'], algorithm='HS256')
    with social.raw_state() as data:
        data['sessions'] = {auth.digest(token): dict(user_id=player_id, expires=issued + 300)}
    setup.owner.set_cookie(auth.COOKIE, token)
    assert setup.owner.get('/api/arena', base_url='https://localhost').status_code == 401


def test_existing_accounts_without_activation_field_stay_compatible(setup):
    signup(setup.owner)
    with social.raw_state() as data:
        data['accounts'][EMAIL].pop('email_verified')
    assert login(setup.owner).status_code == 200


def verified_viewer(setup):
    viewer_email = 'viewer@example.invalid'
    assert signup(setup.visitor, email=viewer_email).status_code == 201
    assert activate(setup.visitor, setup.sent[-1]['token']).status_code == 200
    result = post(setup.visitor, 'login', {'email': viewer_email, 'password': PASSWORD})
    assert result.status_code == 200
    return result.json['userId']


def test_pending_player_excluded_from_discovery_and_targeting_until_activation(setup):
    viewer_id = verified_viewer(setup)
    assert signup(setup.owner).status_code == 201
    activation_token = setup.sent[-1]['token']
    with social.raw_state() as data:
        player_id = data['accounts'][EMAIL]['player_id']
        # A legitimate team owner cannot add an inactive identity by guessing ID.
        data['arena']['teams'].append(dict(id='viewer-owned-team', name='Viewer Team',
            sport='Football', city='Pune', ownerId=viewer_id, members=[viewer_id], requests=[], capacity=11))
    def get(route):
        return setup.visitor.get('/api/' + route, base_url='https://localhost')
    overview = get('arena').json
    assert player_id not in {player['id'] for player in overview['players']}
    assert 'demo-user' in {player['id'] for player in overview['players']}
    for route in ('friends/players', 'messages/players'):
        assert player_id not in {player['id'] for player in get(route).json['players']}
    assert get('arena/players/' + player_id).status_code == 404
    assert get('messages/conversations/' + player_id).status_code == 404
    from messages import sticker_ids
    with app.app_context():
        sticker_id = next(iter(sticker_ids()))
    for route, payload in (
        ('arena/players/' + player_id + '/support', {}),
        ('arena/teams/viewer-owned-team/members', {'playerId': player_id}),
        ('friends/requests', {'playerId': player_id}),
        ('messages/conversations/' + player_id, {'stickerId': sticker_id}),
    ):
        result = setup.visitor.post('/api/' + route, json=payload, headers=HEADERS, base_url='https://localhost')
        assert result.status_code == 404, route
    assert activate(setup.owner, activation_token).status_code == 200
    for route in ('arena', 'friends/players', 'messages/players'):
        assert player_id in {player['id'] for player in get(route).json['players']}
    assert get('arena/players/' + player_id).status_code == 200
    assert get('messages/conversations/' + player_id).status_code == 200
    with social.raw_state() as data:
        assert data['arena']['teams'][-1]['members'] == [viewer_id]
        assert next(p for p in data['arena']['players'] if p['id'] == player_id)['supporters'] == []
        # Backward-compatible active accounts without the new flag remain visible.
        data['accounts'][EMAIL].pop('email_verified')
    assert player_id in {player['id'] for player in get('messages/players').json['players']}


def test_pending_organisation_is_hidden_until_its_owner_activates(setup):
    verified_viewer(setup)
    assert signup(setup.owner, accountType='organisation', organisationName='Pending Sports Club').status_code == 201
    activation_token = setup.sent[-1]['token']
    with social.raw_state() as data:
        organisation_id = data['accounts'][EMAIL]['organisation_id']
    def visible_ids():
        result = setup.visitor.get('/api/organisations', base_url='https://localhost')
        assert result.status_code == 200
        return {item['id'] for item in result.json['organisations']}
    assert organisation_id not in visible_ids()
    assert activate(setup.owner, activation_token).status_code == 200
    assert organisation_id in visible_ids()
    with social.raw_state() as data:
        data['accounts'][EMAIL].pop('email_verified')
    assert organisation_id in visible_ids()


def test_activation_email_has_trusted_fragment_url(setup):
    signup(setup.owner)
    message = setup.sent[-1]
    text = password_reset.email_text(message['settings'], message['token'])
    assert 'https://dhoyo.example.invalid/ring#activate-token=' + message['token'] in text
    assert '24 hours' in text
    assert password_reset.email_subject(message['settings']) == 'Activate your Dhoyo account'


@pytest.fixture
def google_key(monkeypatch):
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    monkeypatch.setattr(google_auth.GOOGLE_KEYS, 'get_signing_key_from_jwt',
                        lambda _: SimpleNamespace(key=private.public_key()))
    return private


def google_challenge(client):
    response = post(client, 'google/challenge', {})
    assert response.status_code == 200
    return response.json


def credential(private, expected_nonce, **changes):
    claims = dict(sub='stable-google-subject', iss='https://accounts.google.com', aud=CLIENT_ID,
                  iat=int(time.time()), exp=int(time.time()) + 300, nonce=expected_nonce,
                  email=EMAIL, email_verified=True, name='Google Player')
    claims.update(changes)
    return jwt.encode(claims, private, algorithm='RS256', headers={'kid': 'synthetic-key'})


def google_signin(client, private, **changes):
    challenge = google_challenge(client)
    payload = dict(credential=credential(private, challenge['nonce'], **changes), challengeId=challenge['challengeId'])
    return post(client, 'google', payload), payload


def test_google_disabled_without_configuration(setup, monkeypatch):
    monkeypatch.setitem(app.config, 'GOOGLE_CLIENT_ID', None)
    response = setup.owner.get('/api/auth/google/config', base_url='https://localhost')
    assert response.json == {'enabled': False}
    assert post(setup.owner, 'google/challenge', {}).status_code == 503
    assert post(setup.owner, 'google', {}).status_code == 503


def test_google_onboarding_requires_details_and_email_activation(setup, google_key):
    response, proof = google_signin(setup.owner, google_key)
    assert response.json['onboardingRequired'] is True and response.json['email'] == EMAIL
    assert setup.owner.get_cookie(auth.COOKIE) is None
    assert post(setup.owner, 'google', proof).status_code == 400
    assert post(setup.owner, 'google/register', {'name': 'Incomplete'}).status_code == 400
    created = post(setup.owner, 'google/register', dict(PROFILE, email='forged@example.invalid', google_subject='forged'))
    assert created.status_code == 201 and created.json['activationRequired']
    assert setup.owner.get_cookie(google_auth.SIGNUP_COOKIE, path='/api/auth') is None
    with social.raw_state() as data:
        account = data['accounts'][EMAIL]
        assert account['google_subject'] == 'stable-google-subject'
        assert 'forged@example.invalid' not in data['accounts']
        assert proof['credential'] not in json.dumps(data)
        assert data['googleSignupTickets'] == {}
    blocked, _ = google_signin(setup.owner, google_key)
    assert blocked.status_code == 403 and blocked.json['activationRequired']
    assert activate(setup.owner, setup.sent[-1]['token']).status_code == 200
    signed_in, _ = google_signin(setup.owner, google_key)
    assert signed_in.status_code == 200 and signed_in.json['googleLinked'] is True
    # Stable Google subject is the identity even when Google's email has changed.
    changed, _ = google_signin(setup.visitor, google_key, email='changed@example.invalid')
    assert changed.json['userId'] == signed_in.json['userId']


@pytest.mark.parametrize('changes', [dict(aud='wrong-client'), dict(iss='https://attacker.invalid'),
    dict(exp=1), dict(iat=int(time.time()) + 3600), dict(email_verified=False),
    dict(email_verified='true'), dict(nonce='wrong'), dict(sub=''), dict(email='bad'),
    dict(azp='other-client'), dict(aud=[CLIENT_ID, 'other-client'])])
def test_google_signature_claim_checks_reject_invalid_tokens(setup, google_key, changes):
    response, _ = google_signin(setup.owner, google_key, **changes)
    assert response.status_code == 400
    assert setup.owner.get_cookie(google_auth.SIGNUP_COOKIE, path='/api/auth') is None
    assert setup.owner.get_cookie(auth.COOKIE) is None


def test_google_rejects_tampered_signature_and_untrusted_profile(setup, google_key):
    challenge = google_challenge(setup.owner)
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    assert post(setup.owner, 'google', dict(credential=credential(other, challenge['nonce']),
                 challengeId=challenge['challengeId'])).status_code == 400
    assert post(setup.owner, 'google', dict(email=EMAIL, sub='stable-google-subject', email_verified=True)).status_code == 400


def test_google_challenge_bound_to_browser_session_expiry_and_single_use(setup, google_key):
    challenge = google_challenge(setup.owner)
    payload = dict(credential=credential(google_key, challenge['nonce']), challengeId=challenge['challengeId'])
    assert post(setup.visitor, 'google', payload).status_code == 400
    assert post(setup.owner, 'google', payload).status_code == 200
    assert post(setup.owner, 'google', payload).status_code == 400
    challenge = google_challenge(setup.owner)
    with social.raw_state() as data:
        data['googleAuthChallenges'][auth.digest(challenge['challengeId'])]['expires'] = time.time() - 1
    assert post(setup.owner, 'google', dict(credential=credential(google_key, challenge['nonce']), challengeId=challenge['challengeId'])).status_code == 400
    challenge = google_challenge(setup.owner)
    setup.owner.set_cookie(auth.COOKIE, 'changed-session-context')
    assert post(setup.owner, 'google', dict(credential=credential(google_key, challenge['nonce']), challengeId=challenge['challengeId'])).status_code == 400


def test_google_signup_ticket_bound_to_browser_and_expires(setup, google_key):
    google_signin(setup.owner, google_key)
    assert post(setup.visitor, 'google/register', PROFILE).status_code == 400
    with social.raw_state() as data:
        for record in data['googleSignupTickets'].values():
            record['expires'] = time.time() - 1
    assert post(setup.owner, 'google/register', PROFILE).status_code == 400


def test_google_verification_outside_shared_state(setup, google_key, monkeypatch):
    original = social.raw_state
    original_verify = google_auth.verify_google_token
    depth = [0]
    @contextmanager
    def tracked():
        with original() as data:
            depth[0] += 1
            try:
                yield data
            finally:
                depth[0] -= 1
    monkeypatch.setattr(social, 'raw_state', tracked)
    def verified(*args):
        assert depth[0] == 0
        return original_verify(*args)
    monkeypatch.setattr(google_auth, 'verify_google_token', verified)
    assert google_signin(setup.owner, google_key)[0].status_code == 200


def test_google_requires_explicit_link_for_existing_password_account(setup, google_key):
    signup(setup.owner)
    activate(setup.owner, setup.sent[-1]['token'])
    response, _ = google_signin(setup.visitor, google_key)
    assert response.status_code == 409 and response.json['linkRequired'] is True
    assert post(setup.visitor, 'google/link', {}).status_code == 401
    assert login(setup.owner).status_code == 200
    challenge = google_challenge(setup.owner)
    wrong = post(setup.owner, 'google/link', dict(credential=credential(google_key, challenge['nonce'], email='other@example.invalid'),
                                               challengeId=challenge['challengeId']))
    assert wrong.status_code == 400
    challenge = google_challenge(setup.owner)
    result = post(setup.owner, 'google/link', dict(credential=credential(google_key, challenge['nonce']), challengeId=challenge['challengeId']))
    assert result.status_code == 200 and result.json['googleLinked'] is True
    response, _ = google_signin(setup.visitor, google_key)
    assert response.status_code == 200


def test_google_rate_limits_verification_and_challenges(setup):
    for _ in range(30):
        assert post(setup.owner, 'google/challenge', {}).status_code == 200
    assert post(setup.owner, 'google/challenge', {}).status_code == 429


def test_new_sensitive_endpoints_require_encrypted_requests(setup, monkeypatch):
    monkeypatch.setitem(app.config, 'AUTH_TEST_ALLOW_PLAINTEXT', False)
    for route in ('activate-account', 'resend-activation', 'google', 'google/register', 'google/link'):
        assert post(setup.owner, route, {}).status_code == 400
        challenge = setup.owner.get('/api/auth/encryption-key', query_string={'path': '/api/auth/' + route}, base_url='https://localhost')
        assert challenge.status_code == 200


def test_encrypted_signup_and_activation_complete_without_exposing_proof(setup, monkeypatch):
    from test_auth_encryption import envelope
    monkeypatch.setitem(app.config, 'AUTH_TEST_ALLOW_PLAINTEXT', False)
    path = '/api/auth/register'
    payload = dict(PROFILE, email=EMAIL, password=PASSWORD)
    response = post(setup.owner, 'register', envelope(setup.owner, path, payload))
    assert response.status_code == 201 and response.json['activationRequired']
    token = setup.sent[-1]['token']
    path = '/api/auth/activate-account'
    wire = envelope(setup.owner, path, {'token': token})
    assert token not in json.dumps(wire)
    assert post(setup.owner, 'activate-account', wire).status_code == 200
    assert post(setup.owner, 'activate-account', wire).status_code == 400
    path = '/api/auth/login'
    signed_in = post(setup.owner, 'login', envelope(setup.owner, path, {'email': EMAIL, 'password': PASSWORD}))
    assert signed_in.status_code == 200


def test_google_encrypted_credential_and_profile_flow(setup, google_key, monkeypatch):
    from test_auth_encryption import envelope
    monkeypatch.setitem(app.config, 'AUTH_TEST_ALLOW_PLAINTEXT', False)
    challenge = google_challenge(setup.owner)
    raw = dict(credential=credential(google_key, challenge['nonce']), challengeId=challenge['challengeId'])
    encrypted = envelope(setup.owner, '/api/auth/google', raw)
    assert raw['credential'] not in json.dumps(encrypted)
    assert post(setup.owner, 'google', encrypted).json['onboardingRequired']
    encrypted = envelope(setup.owner, '/api/auth/google/register', PROFILE)
    assert post(setup.owner, 'google/register', encrypted).json['activationRequired']


def test_production_cannot_enable_test_legacy_registration(setup, monkeypatch):
    monkeypatch.setitem(app.config, 'TESTING', False)
    monkeypatch.setitem(app.config, 'AUTH_TEST_LEGACY_REGISTRATION', True)
    with app.app_context():
        assert auth.legacy_registration_enabled() is False
