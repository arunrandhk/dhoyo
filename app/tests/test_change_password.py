"""Authenticated password changes preserve one browser and revoke other credentials."""
from pathlib import Path
import sys
import time

import pytest
from werkzeug.security import check_password_hash

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import app
import auth
from auth import COOKIE, digest
from social import raw_state


HEADERS = {'X-Dhoyo-Request': '1'}
PASSWORD = '  Current pässword ⚽  '
NEW_PASSWORD = '  My new pässword ☃  '


@pytest.fixture
def clients(tmp_path, monkeypatch):
    monkeypatch.setenv('SPORTSPACE_SOCIAL_DB', str(tmp_path / 'change-password.sqlite'))
    monkeypatch.setitem(app.config, 'AUTH_TEST_DEMO', False)
    return app.test_client(), app.test_client(), app.test_client()


def register(client, email='alex@example.com'):
    response = client.post('/api/auth/register', json=dict(
        name='Alex', email=email, password=PASSWORD, sport='Football',
        city='Delhi', state='Delhi', country='India'), headers=HEADERS, base_url='https://localhost')
    assert response.status_code == 201
    return response.json['userId']


def login(client, password=PASSWORD, email='alex@example.com', **kwargs):
    kwargs.setdefault('base_url', 'https://localhost')
    return client.post('/api/auth/login', json={'email': email, 'password': password},
                       headers=HEADERS, **kwargs)


def change(client, current_password=PASSWORD, password=NEW_PASSWORD, **kwargs):
    kwargs.setdefault('base_url', 'https://localhost')
    return client.post('/api/auth/change-password', json={
        'currentPassword': current_password, 'password': password}, headers=HEADERS, **kwargs)


def test_change_rotates_session_revokes_account_credentials_and_preserves_other_accounts(clients):
    owner, second_browser, unrelated = clients
    player_id = register(owner)
    other_id = register(unrelated, email='sam@example.com')
    assert login(second_browser).status_code == 200
    old_cookie = owner.get_cookie(COOKIE).value
    second_cookie = second_browser.get_cookie(COOKIE).value
    with raw_state() as data:
        data['passwordResetTokens'] = {
            digest('x' * 43): dict(email='alex@example.com', user_id=player_id,
                                   expires=time.time() + 1800, active=True),
            digest('y' * 43): dict(email='alex@example.com', user_id=player_id,
                                   expires=time.time() + 1800, active=False),
            digest('z' * 43): dict(email='sam@example.com', user_id=other_id,
                                   expires=time.time() + 1800, active=True),
        }
        data['loginAttempts'] = {
            digest('alex@example.com|' + address): dict(count=10, until=time.time() + 900,
                                                       email_digest=digest('alex@example.com'))
            for address in ('127.0.0.1', '192.0.2.1')
        }
        data['loginAttempts']['unrelated'] = dict(count=2, until=time.time() + 900,
                                                 email_digest=digest('sam@example.com'))

    response = change(owner)
    assert response.status_code == 200
    assert response.json == {
        'userId': player_id,
        'name': 'Alex', 'accountType': 'player', 'organisationId': None,
        'message': 'Your password has been updated. Other sessions have been signed out.',
    }
    new_cookie = owner.get_cookie(COOKIE)
    assert new_cookie.value not in (old_cookie, second_cookie)
    assert new_cookie.http_only and new_cookie.same_site == 'Lax'
    assert owner.get('/api/auth/me').json['userId'] == player_id
    assert owner.get('/api/arena').status_code == 200
    assert second_browser.get('/api/arena').status_code == 401
    assert unrelated.get('/api/auth/me').json['userId'] == other_id
    with raw_state() as data:
        assert set(data['passwordResetTokens']) == {digest('z' * 43)}
        assert set(data['loginAttempts']) == {'unrelated'}
        assert digest(old_cookie) not in data['sessions']
        assert digest(second_cookie) not in data['sessions']
        assert sum(session['user_id'] == player_id for session in data['sessions'].values()) == 1
        password_hash = data['accounts']['alex@example.com']['password_hash']
        assert password_hash.startswith('scrypt:')
        assert check_password_hash(password_hash, NEW_PASSWORD)
        assert PASSWORD not in str(data) and NEW_PASSWORD not in str(data)
    assert second_browser.post('/api/auth/reset-password', json={
        'token': 'x' * 43, 'password': 'a-reset-password'}, headers=HEADERS).status_code == 400
    assert login(second_browser).status_code == 401
    assert login(second_browser, NEW_PASSWORD.strip()).status_code == 401
    for address in ('127.0.0.1', '192.0.2.1'):
        assert login(second_browser, NEW_PASSWORD,
                     environ_overrides={'REMOTE_ADDR': address}).status_code == 200
    assert login(unrelated, email='sam@example.com').status_code == 200


def test_wrong_current_password_keeps_session_and_password(clients):
    owner, returning, _ = clients
    player_id = register(owner)
    old_cookie = owner.get_cookie(COOKIE).value
    assert change(owner, current_password=PASSWORD.strip()).status_code == 403
    assert owner.get_cookie(COOKIE).value == old_cookie
    assert owner.get('/api/auth/me').json['userId'] == player_id
    assert login(returning).status_code == 200
    assert login(returning, NEW_PASSWORD).status_code == 401


def test_change_requires_live_session_and_account(clients):
    owner, visitor, _ = clients
    assert change(visitor).status_code == 401
    visitor.set_cookie(COOKIE, 'unknown-session')
    assert change(visitor).status_code == 401
    register(owner)
    with raw_state() as data:
        session = data['sessions'][digest(owner.get_cookie(COOKIE).value)]
        session['expires'] = 0
    assert change(owner).status_code == 401
    assert login(owner).status_code == 200
    with raw_state() as data:
        data['accounts'].clear()
    assert change(owner).status_code == 401


@pytest.mark.parametrize('payload', [
    None, [], {}, {'password': NEW_PASSWORD}, {'currentPassword': PASSWORD},
    {'currentPassword': PASSWORD, 'password': NEW_PASSWORD, 'userId': 'another-player'},
    {'currentPassword': PASSWORD, 'password': NEW_PASSWORD, 'email': 'sam@example.com'},
    {'currentPassword': None, 'password': NEW_PASSWORD},
    {'currentPassword': [], 'password': NEW_PASSWORD},
    {'currentPassword': '', 'password': NEW_PASSWORD},
    {'currentPassword': 'x' * 129, 'password': NEW_PASSWORD},
    {'currentPassword': PASSWORD, 'password': None},
    {'currentPassword': PASSWORD, 'password': False},
    {'currentPassword': PASSWORD, 'password': []},
    {'currentPassword': PASSWORD, 'password': 'x' * 9},
    {'currentPassword': PASSWORD, 'password': 'x' * 129},
])
def test_strict_fields_and_password_policy_do_not_modify_account(clients, payload):
    owner, returning, _ = clients
    register(owner)
    response = owner.post('/api/auth/change-password', json=payload, headers=HEADERS)
    # Flask omits a JSON body for json=None, which the shared CSRF gate rejects.
    assert response.status_code == (403 if payload is None else 400)
    assert login(returning).status_code == 200


@pytest.mark.parametrize('password', ['x' * 10, 'x' * 128, '  Pässwörd⚽  '])
def test_password_policy_boundaries_and_exact_characters(clients, password):
    owner, returning, _ = clients
    register(owner)
    assert change(owner, password=password).status_code == 200
    assert login(returning, password).status_code == 200


def test_csrf_checks_reject_changes_and_preserve_password(clients):
    owner, returning, _ = clients
    register(owner)
    payload = {'currentPassword': PASSWORD, 'password': NEW_PASSWORD}
    assert owner.post('/api/auth/change-password', json=payload).status_code == 403
    assert owner.post('/api/auth/change-password', data=payload, headers=HEADERS).status_code == 403
    assert owner.post('/api/auth/change-password', json=payload,
                      headers={**HEADERS, 'Origin': 'https://attacker.example'}).status_code == 403
    assert owner.post('/api/auth/change-password', json=payload,
                      headers={**HEADERS, 'Sec-Fetch-Site': 'cross-site'}).status_code == 403
    assert login(returning).status_code == 200


def test_user_attempt_limit_is_shared_across_browsers_and_addresses_and_expires(clients):
    owner, second_browser, _ = clients
    register(owner)
    assert login(second_browser).status_code == 200
    for index in range(10):
        browser = owner if index % 2 else second_browser
        assert change(browser, current_password='incorrect',
                      environ_overrides={'REMOTE_ADDR': f'192.0.2.{index}'}).status_code == 403
    response = change(owner, environ_overrides={'REMOTE_ADDR': '198.51.100.1'})
    assert response.status_code == 429
    assert response.headers['Retry-After'] == '900'
    assert owner.get('/api/arena').status_code == 200
    with raw_state() as data:
        for limit in data['passwordResetRateLimits'].values():
            limit['until'] = 0
        assert 'incorrect' not in str(data)
    assert change(owner).status_code == 200


def test_ip_attempt_limit_is_shared_across_accounts(clients):
    first, second, _ = clients
    register(first)
    register(second, email='sam@example.com')
    for _ in range(5):
        assert change(first, current_password='incorrect').status_code == 403
        assert change(second, current_password='incorrect').status_code == 403
    assert change(first).status_code == 429
    assert change(second).status_code == 429


def test_revocation_during_hashing_prevents_password_overwrite(clients, monkeypatch):
    owner, returning, _ = clients
    register(owner)
    real_hash = auth.generate_password_hash

    def revoke_then_hash(password, **kwargs):
        with raw_state() as data:
            data['sessions'].clear()
        return real_hash(password, **kwargs)

    monkeypatch.setattr(auth, 'generate_password_hash', revoke_then_hash)
    assert change(owner).status_code == 401
    assert login(returning).status_code == 200
    assert login(returning, NEW_PASSWORD).status_code == 401
