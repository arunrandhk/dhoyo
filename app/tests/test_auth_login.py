"""Credential regressions for exact passwords and persisted player accounts."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import app

HEADERS = {'X-Dhoyo-Request': '1'}


@pytest.fixture
def clients(tmp_path, monkeypatch):
    monkeypatch.setenv('SPORTSPACE_SOCIAL_DB', str(tmp_path / 'accounts.sqlite'))
    # Domain tests enable the demo account; these tests exercise real cookies.
    monkeypatch.setitem(app.config, 'AUTH_TEST_DEMO', False)
    return app.test_client(), app.test_client()


def register(client, email='player@example.com', password='my-long-password'):
    response = client.post('/api/auth/register', json=dict(
        name='Test Player', email=email, password=password, sport='Football',
        city='Delhi', state='Delhi', country='India'), headers=HEADERS)
    assert response.status_code == 201
    return response.json['userId']


@pytest.mark.parametrize('password', [
    '  long password 123  ',
    'Pässwörd⚽🔑12345',
    'a' * 128,
])
def test_login_preserves_every_password_character_and_normalizes_email(clients, password):
    owner, returning = clients
    player_id = register(owner, email='Player@Example.COM', password=password)
    assert owner.post('/api/auth/logout', json={}, headers=HEADERS).status_code == 200

    login = returning.post('/api/auth/login', json=dict(
        email='  PLAYER@example.com  ', password=password), headers=HEADERS)
    assert login.status_code == 200
    assert login.json['userId'] == player_id
    assert returning.get('/api/auth/me').json['userId'] == player_id

    changed = returning.post('/api/auth/login', json=dict(
        email='player@example.com', password=password + 'x'), headers=HEADERS)
    assert changed.status_code == 401


def test_account_and_password_survive_a_fresh_application_process(clients):
    owner, _ = clients
    player_id = register(owner)
    assert owner.post('/api/auth/logout', json={}, headers=HEADERS).status_code == 200

    program = """
import json
from app import app
app.config['AUTH_TEST_DEMO'] = False
app.config['TESTING'] = True
app.config['AUTH_TEST_ALLOW_PLAINTEXT'] = True
client = app.test_client()
login = client.post('/api/auth/login', json={
    'email': 'player@example.com', 'password': 'my-long-password'
}, headers={'X-Dhoyo-Request': '1'}, base_url='https://localhost')
assert login.status_code == 200
assert client.get('/api/auth/me', base_url='https://localhost').json['userId'] == login.json['userId']
print(json.dumps(login.json))
"""
    result = subprocess.run(
        [sys.executable, '-c', program], cwd=Path(__file__).resolve().parents[1],
        env=os.environ.copy(), check=True, capture_output=True, text=True)
    assert json.loads(result.stdout)['userId'] == player_id


def test_correct_login_clears_previous_failed_attempts(clients):
    owner, returning = clients
    player_id = register(owner)
    for _ in range(9):
        assert returning.post('/api/auth/login', json=dict(
            email='player@example.com', password='wrong-password'),
            headers=HEADERS).status_code == 401
    login = returning.post('/api/auth/login', json=dict(
        email='PLAYER@example.com', password='my-long-password'), headers=HEADERS)
    assert login.status_code == 200
    assert login.json['userId'] == player_id
    assert returning.post('/api/auth/login', json=dict(
        email='player@example.com', password='wrong-password'),
        headers=HEADERS).status_code == 401


def test_correct_password_login_recovers_after_lockout_expires(clients, monkeypatch):
    import auth

    owner, returning = clients
    register(owner)
    clock = [1_800_000_000]
    monkeypatch.setattr(auth.time, 'time', lambda: clock[0])
    for _ in range(10):
        assert returning.post('/api/auth/login', json=dict(
            email='player@example.com', password='wrong-password'),
            headers=HEADERS).status_code == 401
    locked = returning.post('/api/auth/login', json=dict(
        email='player@example.com', password='my-long-password'), headers=HEADERS)
    assert locked.status_code == 429
    clock[0] += 901
    assert returning.post('/api/auth/login', json=dict(
        email='player@example.com', password='my-long-password'),
        headers=HEADERS).status_code == 200
