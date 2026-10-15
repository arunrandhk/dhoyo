"""Credential envelopes conceal fields and reject replay/tampering in real SQL state."""
import base64
import json
import time
import sys
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import app
from social import raw_state

HEADERS = {'X-Dhoyo-Request': '1'}
SECRET = 'synthetic-envelope-secret-0123456789abcdefghijklmnopqrstuvwxyz'
PAYLOAD = dict(name='Private Payload Player', email='private-payload@example.invalid',
               password='  private-password-123  ', sport='Football', city='Pune',
               state='Maharashtra', country='India')


def encode(value):
    return base64.urlsafe_b64encode(value).rstrip(b'=').decode()


def decode(value):
    return base64.urlsafe_b64decode(value + '=' * (-len(value) % 4))


def envelope(client, path, payload):
    response = client.get('/api/auth/encryption-key', query_string={'path': path}, base_url='https://localhost')
    assert response.status_code == 200
    challenge = response.json
    jwk = challenge['publicKey']
    peer = ec.EllipticCurvePublicNumbers(int.from_bytes(decode(jwk['x']), 'big'),
                                        int.from_bytes(decode(jwk['y']), 'big'), ec.SECP256R1()).public_key()
    private = ec.generate_private_key(ec.SECP256R1())
    shared = private.exchange(ec.ECDH(), peer)
    key = HKDF(algorithm=hashes.SHA256(), length=32, salt=decode(challenge['challengeId']),
               info=b'dhoyo-auth-request-v1').derive(shared)
    iv = __import__('secrets').token_bytes(12)
    aad = ('dhoyo-auth-v1|' + path + '|' + challenge['kid'] + '|' + challenge['challengeId']).encode()
    raw = private.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return dict(v=1, kid=challenge['kid'], challengeId=challenge['challengeId'], epk=encode(raw),
                iv=encode(iv), ciphertext=encode(AESGCM(key).encrypt(iv, json.dumps(payload).encode(), aad)))


def send(client, path, payload):
    return client.post(path, json=payload, headers=HEADERS, base_url='https://localhost')


@pytest.fixture
def clients(tmp_path, monkeypatch):
    monkeypatch.setenv('SPORTSPACE_SOCIAL_DB', str(tmp_path / 'encrypted-accounts.sqlite3'))
    monkeypatch.setitem(app.config, 'AUTH_TEST_DEMO', False)
    monkeypatch.setitem(app.config, 'AUTH_TEST_ALLOW_PLAINTEXT', False)
    monkeypatch.setitem(app.config, 'AUTH_JWT_SECRET', SECRET)
    return app.test_client(), app.test_client()


def test_encrypted_signup_login_and_change_password_preserve_exact_credentials(clients):
    owner, visitor = clients
    path = '/api/auth/register'
    encrypted = envelope(owner, path, PAYLOAD)
    wire = json.dumps(encrypted)
    for value in (PAYLOAD['name'], PAYLOAD['email'], PAYLOAD['password']):
        assert value not in wire
    assert not {'name', 'email', 'password'} & set(encrypted)
    registered = send(owner, path, encrypted)
    assert registered.status_code == 201
    with raw_state() as data:
        assert data['accounts'][PAYLOAD['email']]['password_hash'].startswith('scrypt:')
        assert PAYLOAD['password'] not in json.dumps(data)
        assert PAYLOAD['email'] not in json.dumps(data['authEncryptionChallenges'])
    login = dict(email=PAYLOAD['email'], password=PAYLOAD['password'])
    assert send(visitor, '/api/auth/login', envelope(visitor, '/api/auth/login', login)).status_code == 200
    changed = dict(currentPassword=PAYLOAD['password'], password='replacement-private-password')
    assert send(visitor, '/api/auth/change-password', envelope(visitor, '/api/auth/change-password', changed)).status_code == 200
    assert send(owner, '/api/auth/login', envelope(owner, '/api/auth/login', dict(login, password=changed['password']))).status_code == 200


@pytest.mark.parametrize('path', [
    '/api/auth/login', '/api/auth/register', '/api/auth/change-password',
    '/api/auth/request-password-code', '/api/auth/reset-password-code',
    '/api/auth/forgot-password', '/api/auth/reset-password'])
def test_plaintext_is_rejected_for_all_credential_paths(clients, path):
    owner, _ = clients
    response = send(owner, path, PAYLOAD)
    assert response.status_code == 400
    assert 'accounts' not in app_state()


def app_state():
    with raw_state() as data:
        return json.loads(json.dumps(data))


def test_replay_cannot_create_another_session_even_with_valid_ciphertext(clients):
    owner, visitor = clients
    assert send(owner, '/api/auth/register', envelope(owner, '/api/auth/register', PAYLOAD)).status_code == 201
    data = dict(email=PAYLOAD['email'], password=PAYLOAD['password'])
    captured = envelope(visitor, '/api/auth/login', data)
    assert send(visitor, '/api/auth/login', captured).status_code == 200
    state = app_state()
    assert send(visitor, '/api/auth/login', captured).status_code == 400
    assert app_state() == state


def test_even_a_failed_login_envelope_cannot_be_replayed_with_the_same_cookie(clients):
    _, visitor = clients
    captured = envelope(visitor, '/api/auth/login', dict(email='unknown@example.invalid', password='incorrect-password'))
    assert send(visitor, '/api/auth/login', captured).status_code == 401
    state = app_state()
    assert send(visitor, '/api/auth/login', captured).status_code == 400
    assert app_state() == state


@pytest.mark.parametrize('field,value', [('v', True), ('kid', 'unknown'), ('challengeId', 'bad'),
    ('epk', 'AA'), ('iv', 'AA'), ('ciphertext', 'AAAA'), ('password', 'extra-plaintext')])
def test_malformed_or_mixed_envelopes_do_not_create_accounts(clients, field, value):
    owner, _ = clients
    captured = envelope(owner, '/api/auth/register', PAYLOAD)
    captured[field] = value
    response = send(owner, '/api/auth/register', captured)
    assert response.status_code == 400
    assert 'accounts' not in app_state()


def test_tampering_path_expiry_and_key_rotation_are_rejected(clients, monkeypatch):
    owner, _ = clients
    captured = envelope(owner, '/api/auth/register', PAYLOAD)
    damaged = dict(captured, ciphertext=encode(bytes([decode(captured['ciphertext'])[0] ^ 1]) + decode(captured['ciphertext'])[1:]))
    assert send(owner, '/api/auth/register', damaged).status_code == 400
    assert send(owner, '/api/auth/login', captured).status_code == 400
    import auth_envelope
    from auth import digest
    with raw_state() as data:
        data['authEncryptionChallenges'][digest(captured['challengeId'])]['expires'] = time.time() - 1
    assert send(owner, '/api/auth/register', captured).status_code == 400
    fresh = envelope(owner, '/api/auth/register', PAYLOAD)
    monkeypatch.setitem(app.config, 'AUTH_JWT_SECRET', SECRET + '-rotated')
    assert send(owner, '/api/auth/register', fresh).status_code == 400


def test_server_key_is_stable_across_requests_and_plaintext_bypass_is_test_only(clients, monkeypatch):
    owner, _ = clients
    first = owner.get('/api/auth/encryption-key?path=/api/auth/login', base_url='https://localhost')
    second = owner.get('/api/auth/encryption-key?path=/api/auth/login', base_url='https://localhost')
    assert first.json['kid'] == second.json['kid']
    assert first.json['publicKey'] == second.json['publicKey']
    assert first.json['challengeId'] != second.json['challengeId']
    assert first.headers['Cache-Control'] == 'no-store'
    monkeypatch.setitem(app.config, 'AUTH_TEST_ALLOW_PLAINTEXT', True)
    monkeypatch.setitem(app.config, 'TESTING', False)
    assert send(owner, '/api/auth/register', PAYLOAD).status_code == 400


def test_public_http_and_cross_origin_requests_remain_blocked(clients):
    owner, _ = clients
    assert owner.get('/api/auth/encryption-key?path=/api/auth/login', base_url='http://public.example').status_code == 403
    assert owner.post('/api/auth/login', json=PAYLOAD, headers={**HEADERS, 'Origin': 'https://other.example'}, base_url='https://localhost').status_code == 403
