"""Security regressions use synthetic accounts and isolated local state."""
from contextlib import contextmanager
from pathlib import Path
import sys
import time

import pytest
from werkzeug.security import generate_password_hash

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import app
import auth
import social


HEADERS = {'X-Dhoyo-Request': '1'}
EMAIL = 'security-check@example.invalid'
PASSWORD = 'synthetic-account-password-42'


@pytest.fixture
def clients(tmp_path, monkeypatch):
    monkeypatch.setenv('SPORTSPACE_SOCIAL_DB', str(tmp_path / 'security.sqlite'))
    monkeypatch.setitem(app.config, 'TESTING', True)
    monkeypatch.setitem(app.config, 'AUTH_TEST_DEMO', False)
    return app.test_client(), app.test_client()


def register(client):
    response = client.post('/api/auth/register', headers=HEADERS, json=dict(
        name='Security Check', email=EMAIL, password=PASSWORD, sport='Football',
        city='Delhi', state='Delhi', country='India'))
    assert response.status_code == 201
    return response.json['userId']


def login(client, email=EMAIL, password=PASSWORD, **kwargs):
    return client.post('/api/auth/login', headers=HEADERS,
                       json={'email': email, 'password': password}, **kwargs)


def test_unknown_and_known_accounts_verify_scrypt_outside_state_transaction(clients, monkeypatch):
    owner, visitor = clients
    register(owner)
    original_state = social.raw_state
    original_check = auth.check_password_hash
    depth = 0
    checked_hashes = []

    @contextmanager
    def tracked_state():
        nonlocal depth
        with original_state() as data:
            depth += 1
            try:
                yield data
            finally:
                depth -= 1

    def check_outside_state(password_hash, submitted_password):
        assert depth == 0, 'Password verification must release shared state first'
        assert password_hash.startswith('scrypt:')
        checked_hashes.append(password_hash)
        return original_check(password_hash, submitted_password)

    monkeypatch.setattr(social, 'raw_state', tracked_state)
    monkeypatch.setattr(auth, 'check_password_hash', check_outside_state)
    known = login(visitor, password='incorrect-password')
    unknown = login(visitor, email='unknown@example.invalid', password='incorrect-password')
    assert known.status_code == unknown.status_code == 401
    assert known.json == unknown.json
    assert len(checked_hashes) == 2
    assert checked_hashes[0] != checked_hashes[1]
    assert visitor.get_cookie(auth.COOKIE) is None


@pytest.mark.parametrize('account_change', ['password', 'delete'])
def test_account_change_during_password_verification_cannot_issue_stale_session(
        clients, monkeypatch, account_change):
    owner, visitor = clients
    register(owner)
    original_check = auth.check_password_hash
    replacement_hash = generate_password_hash('replacement-synthetic-password', method='scrypt')

    def change_during_check(password_hash, submitted_password):
        result = original_check(password_hash, submitted_password)
        assert result is True
        with social.raw_state() as data:
            if account_change == 'delete':
                del data['accounts'][EMAIL]
            else:
                data['accounts'][EMAIL]['password_hash'] = replacement_hash
            data['sessions'].clear()
        return result

    monkeypatch.setattr(auth, 'check_password_hash', change_during_check)
    response = login(visitor)
    assert response.status_code == 401
    assert visitor.get_cookie(auth.COOKIE) is None
    with social.raw_state() as data:
        assert data['sessions'] == {}


def test_varying_email_cannot_bypass_login_ip_limit(clients, monkeypatch):
    _, visitor = clients
    # Verification behavior has its own test; avoid repeating expensive scrypt here.
    monkeypatch.setattr(auth, 'check_password_hash', lambda *_: False)
    for number in range(50):
        response = login(visitor, email=f'missing-{number}@example.invalid',
                         password='incorrect-password')
        assert response.status_code == 401
    response = login(visitor, email='another-missing@example.invalid', password='incorrect-password')
    assert response.status_code == 429
    assert response.headers.get('Retry-After')
    assert login(visitor, email='other-ip@example.invalid', password='incorrect-password',
                 base_url='https://localhost',
                 environ_overrides={'REMOTE_ADDR': '192.0.2.20'}).status_code == 401
    with social.raw_state() as data:
        assert len(data['loginAttempts']) <= auth.MAX_LOGIN_RATE_ENTRIES


def test_login_rate_storage_is_bounded_and_expired_entries_release_capacity(clients, monkeypatch):
    _, visitor = clients
    monkeypatch.setattr(auth, 'check_password_hash', lambda *_: False)
    maximum = auth.MAX_LOGIN_RATE_ENTRIES
    with social.raw_state() as data:
        data['loginAttempts'] = {
            f'existing-{number}': {'count': 0, 'until': time.time() + 900}
            for number in range(maximum)
        }
    assert login(visitor, password='incorrect-password').status_code == 429
    with social.raw_state() as data:
        assert len(data['loginAttempts']) == maximum
        for record in data['loginAttempts'].values():
            record['until'] = 0
    assert login(visitor, password='incorrect-password').status_code == 401
    with social.raw_state() as data:
        assert len(data['loginAttempts']) <= maximum
        assert all(record['until'] > time.time() for record in data['loginAttempts'].values())


@pytest.mark.parametrize('path,method', [
    ('/api/auth/login', 'post'),
    ('/api/auth/register', 'post'),
    ('/api/auth/me', 'get'),
    ('/api/arena', 'get'),
    ('/users', 'get'),
])
def test_public_http_authentication_is_rejected_before_database_access(clients, monkeypatch, path, method):
    _, visitor = clients

    def forbidden_state():
        raise AssertionError('Public HTTP requests must not access account state')

    monkeypatch.setattr(social, 'raw_state', forbidden_state)
    response = getattr(visitor, method)(path, base_url='http://ring.example.invalid',
                                        headers=HEADERS, **({'json': {}} if method == 'post' else {}))
    assert response.status_code == 403
    assert response.headers.get('Set-Cookie') is None
    assert visitor.get('/health', base_url='http://ring.example.invalid').status_code == 200


@pytest.mark.parametrize('base_url,headers', [
    ('http://ring.example.invalid', {'X-Forwarded-Proto': 'https'}),
    ('http://localhost.evil.invalid', {}),
    ('http://127.0.0.1.evil.invalid', {}),
])
def test_forwarded_header_and_localhost_lookalikes_cannot_bypass_https(clients, base_url, headers):
    _, visitor = clients
    response = visitor.get('/api/auth/me', base_url=base_url, headers=headers)
    assert response.status_code == 403


def test_https_and_actual_localhost_remain_usable(clients):
    _, visitor = clients
    for base_url in ('https://ring.example.invalid', 'http://localhost',
                     'http://127.0.0.1', 'http://[::1]'):
        response = visitor.get('/api/auth/me', base_url=base_url)
        assert response.status_code == 200
        assert response.json == {'userId': None}
    assert visitor.get('/api/arena', base_url='https://ring.example.invalid').status_code == 401
    assert visitor.get('/health', base_url='https://ring.example.invalid').status_code == 200


def test_demo_flag_cannot_bypass_authentication_outside_testing(clients, monkeypatch):
    _, visitor = clients
    monkeypatch.setitem(app.config, 'AUTH_TEST_DEMO', True)
    monkeypatch.setitem(app.config, 'TESTING', False)
    assert visitor.get('/api/auth/me', base_url='https://localhost').json == {'userId': None}
    assert visitor.get('/api/arena', base_url='https://localhost').status_code == 401
    monkeypatch.setitem(app.config, 'TESTING', True)
    assert visitor.get('/api/auth/me').json == {'userId': 'demo-user'}


def test_demo_flag_outside_testing_cannot_switch_real_account_to_shared_preferences(clients, monkeypatch):
    owner, _ = clients
    player_id = register(owner)
    with social.raw_state() as data:
        original_demo_preferences = dict(data['preferences'])
    monkeypatch.setitem(app.config, 'AUTH_TEST_DEMO', True)
    monkeypatch.setitem(app.config, 'TESTING', False)
    preferences = owner.get('/api/social/preferences', base_url='https://localhost')
    assert preferences.status_code == 200
    assert preferences.json['city'] == 'Delhi'
    assert preferences.json['sports'] == ['Football']
    changed = owner.patch('/api/social/preferences', json={'city': 'Toronto'}, headers=HEADERS,
                          base_url='https://localhost')
    assert changed.status_code == 200
    with social.raw_state() as data:
        assert data['preferences'] == original_demo_preferences
        assert data['userPreferences'][player_id]['city'] == 'Toronto'
    assert owner.post('/api/arena/awards', json=dict(playerId='athlete-1', matchId='match-final',
        tier='Star', count=1), headers={**HEADERS, 'X-Demo-Role': 'organizer'},
        base_url='https://localhost').status_code == 403


def test_public_json_and_logs_never_include_credentials_or_recovery_proofs(clients, caplog):
    caplog.set_level('DEBUG')
    owner, visitor = clients
    player_id = register(owner)
    raw_session = owner.get_cookie(auth.COOKIE).value
    reset_proof = 'synthetic-reset-proof-never-serialize'
    code_hash = generate_password_hash('654321', method='scrypt')
    with social.raw_state() as data:
        password_hash = data['accounts'][EMAIL]['password_hash']
        data['passwordResetTokens'] = {
            auth.digest(reset_proof): dict(email=EMAIL, user_id=player_id,
                                          expires=time.time() + 1800, active=True),
        }
        data['passwordResetCodes'] = {
            auth.digest('synthetic-challenge-proof'): dict(email=EMAIL, user_id=player_id,
                code_hash=code_hash, expires=time.time() + 600, attempts=0, active=True),
        }
    paths = ['/api/auth/me', '/api/arena', '/api/arena/players/' + player_id,
             '/api/social/feed', '/api/social/stories', '/api/friends',
             '/api/friends/players', '/api/messages/players', '/api/messages/conversations']
    secrets = (EMAIL, PASSWORD, password_hash, raw_session, auth.digest(raw_session),
               reset_proof, auth.digest(reset_proof), code_hash, '654321')
    private_fields = ('password_hash', 'code_hash', 'passwordResetTokens',
                      'passwordResetCodes', 'loginAttempts')
    for path in paths:
        response = owner.get(path)
        assert response.status_code == 200, path
        serialized = response.get_data(as_text=True)
        assert all(value not in serialized for value in secrets), path
        assert all(field not in serialized for field in private_fields), path
    assert login(visitor, password='incorrect-synthetic-password').status_code == 401
    assert all(value not in caplog.text for value in secrets)
    assert 'incorrect-synthetic-password' not in caplog.text
