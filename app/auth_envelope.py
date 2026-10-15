"""Authenticated encryption for credential-bearing browser requests.

The server's purpose-separated ECDH key follows the existing persistent auth
secret across workers. Every request uses a fresh client key, nonce and one-use
challenge. TLS, password hashing and session validation remain mandatory.
"""
import base64
import hashlib
import json
import re
import secrets
import time

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from flask import current_app, g, jsonify, request


PATHS = frozenset('/api/auth/' + name for name in (
    'login', 'register', 'change-password', 'request-password-code',
    'reset-password-code', 'forgot-password', 'reset-password'))
LIFETIME = 120
MAX_CHALLENGES = 2048
MAX_RATE_ENTRIES = 2048
RATE_WINDOW = 15 * 60
P256_ORDER = int('FFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551', 16)
ERROR = 'The encrypted sign-in request is invalid or expired. Please try again.'
INFO = b'dhoyo-auth-request-v1'


def encode(value):
    return base64.urlsafe_b64encode(value).rstrip(b'=').decode('ascii')


def decode(value, size=None, maximum=24000):
    if not isinstance(value, str) or not 1 <= len(value) <= maximum or not re.fullmatch(r'[A-Za-z0-9_-]+', value):
        raise ValueError('Invalid encrypted field')
    result = base64.b64decode(value + '=' * (-len(value) % 4), altchars=b'-_', validate=True)
    if encode(result) != value or (size is not None and len(result) != size):
        raise ValueError('Invalid encrypted field')
    return result


def server_key():
    from auth import jwt_secret
    secret = jwt_secret()
    if not secret:
        return None
    seed = HKDF(algorithm=hashes.SHA256(), length=32, salt=None,
                info=b'dhoyo-auth-request-server-key-v1').derive(secret.encode('utf-8'))
    private = ec.derive_private_key(int.from_bytes(seed, 'big') % (P256_ORDER - 1) + 1, ec.SECP256R1())
    public = private.public_key()
    raw = public.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    kid = encode(hashlib.sha256(raw).digest()[:16])
    numbers = public.public_numbers()
    return private, kid, dict(kty='EC', crv='P-256', x=encode(numbers.x.to_bytes(32, 'big')),
                              y=encode(numbers.y.to_bytes(32, 'big')), ext=True)


def aad(path, kid, challenge):
    return ('dhoyo-auth-v1|' + path + '|' + kid + '|' + challenge).encode('utf-8')


def cleanup(data, timestamp):
    challenges = data.setdefault('authEncryptionChallenges', {})
    for key in list(challenges):
        if challenges[key]['expires'] <= timestamp:
            del challenges[key]
    limits = data.setdefault('authEncryptionRates', {})
    for key in list(limits):
        if limits[key]['until'] <= timestamp:
            del limits[key]
    return challenges, limits


def public_challenge():
    from auth import digest
    from social import raw_state
    path = request.args.get('path', '')
    if path not in PATHS:
        return jsonify(error='Choose a supported account action'), 400
    material = server_key()
    if not material:
        return jsonify(error='Sign-in is temporarily unavailable. Please try again later.'), 503
    _, kid, public = material
    with raw_state() as data:
        timestamp = time.time()
        challenges, limits = cleanup(data, timestamp)
        key = digest('auth-encryption:' + (request.remote_addr or ''))
        if (len(challenges) >= MAX_CHALLENGES or
                (key not in limits and len(limits) >= MAX_RATE_ENTRIES) or
                limits.get(key, {}).get('count', 0) >= 100):
            response = jsonify(error='Too many account requests. Try again later.')
            response.headers['Retry-After'] = str(RATE_WINDOW)
            return response, 429
        rate = limits.setdefault(key, dict(count=0, until=timestamp + RATE_WINDOW))
        rate['count'] += 1
        challenge = secrets.token_urlsafe(32)
        challenges[digest(challenge)] = dict(path=path, kid=kid, expires=timestamp + LIFETIME,
                                            binding=digest(request.cookies.get('dhoyo_session', '')))
    response = jsonify(v=1, kid=kid, publicKey=public, challengeId=challenge, expiresIn=LIFETIME)
    response.headers['Cache-Control'] = 'no-store'
    return response


def decrypt_request():
    """Return an error response or install a validated plaintext body on g."""
    from auth import digest
    from social import raw_state
    envelope = request.get_json(silent=True)
    # Only explicitly opted-in Flask tests can use existing plaintext fixtures.
    if (current_app.testing and current_app.config.get('AUTH_TEST_ALLOW_PLAINTEXT')
            and (not isinstance(envelope, dict) or 'ciphertext' not in envelope)):
        return None
    try:
        if not isinstance(envelope, dict) or set(envelope) != {'v', 'kid', 'challengeId', 'epk', 'iv', 'ciphertext'}:
            raise ValueError('Encrypted account request required')
        if type(envelope['v']) is not int or envelope['v'] != 1:
            raise ValueError('Invalid protocol')
        challenge = envelope['challengeId']
        decode(challenge, 32)
        material = server_key()
        if not material:
            return jsonify(error='Sign-in is temporarily unavailable. Please try again later.'), 503
        private, kid, _ = material
        if envelope['kid'] != kid:
            raise ValueError('Expired encryption key')
        peer_bytes = decode(envelope['epk'], 65)
        if peer_bytes[0] != 4:
            raise ValueError('Invalid public key')
        peer = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), peer_bytes)
        iv = decode(envelope['iv'], 12)
        ciphertext = decode(envelope['ciphertext'])
        if not 16 <= len(ciphertext) <= 16000:
            raise ValueError('Invalid encrypted size')
        key = digest(challenge)
        with raw_state() as data:
            challenges, _ = cleanup(data, time.time())
            record = challenges.get(key)
            if (not record or record['path'] != request.path or record['kid'] != kid or
                    record['binding'] != digest(request.cookies.get('dhoyo_session', ''))):
                raise ValueError('Expired or mismatched challenge')
        shared = private.exchange(ec.ECDH(), peer)
        derived = HKDF(algorithm=hashes.SHA256(), length=32, salt=decode(challenge, 32), info=INFO).derive(shared)
        clear = AESGCM(derived).decrypt(iv, ciphertext, aad(request.path, kid, challenge))
        payload = json.loads(clear)
        if not isinstance(payload, dict):
            raise ValueError('Invalid account data')
        # Consume only after authentication; concurrent replays share this lock.
        with raw_state() as data:
            challenges, _ = cleanup(data, time.time())
            record = challenges.get(key)
            if (not record or record['path'] != request.path or record['kid'] != kid or
                    record['binding'] != digest(request.cookies.get('dhoyo_session', ''))):
                raise ValueError('Consumed challenge')
            del challenges[key]
        g.auth_payload = payload
    except (ValueError, TypeError, KeyError, InvalidTag, UnicodeError):
        return jsonify(error=ERROR), 400
    return None
