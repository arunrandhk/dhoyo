# Encrypted account request payloads

The website encrypts account request bodies before calling `fetch`. Login,
sign-up, password changes, recovery-code requests, code resets and legacy link
resets use this transport. The Network request body contains an encrypted
envelope instead of readable name, email, password, reset code or reset token:

```json
{
  "v": 1,
  "kid": "…",
  "challengeId": "…",
  "epk": "…",
  "iv": "…",
  "ciphertext": "…"
}
```

The browser uses native WebCrypto: a new P-256 ECDH key pair for each submission,
HKDF-SHA256 and AES-256-GCM. Additional authenticated data binds the encrypted
body to its account endpoint, key identifier and challenge. The server derives
its purpose-separated private key from the existing persistent
`AUTH_JWT_SECRET`, so workers with the same secret can process the request.
No new deployment secret is required.

`GET /api/auth/encryption-key?path=/api/auth/login` returns the public key and
an opaque one-use challenge. Challenges expire after two minutes, are bound to
the current session cookie and stored in the shared transactional database.
The challenge is consumed atomically after successful decryption, including
when a valid encrypted submission subsequently fails password validation.
Replaying the ciphertext, changing its endpoint or modifying its contents fails.
Key requests are bounded and rate limited. Responses disable caching.

Readable credential JSON is rejected in normal deployments. Unsupported or
insecure browsers fail before submitting credentials; there is no plaintext
fallback. Existing unit/API fixtures opt into `AUTH_TEST_ALLOW_PLAINTEXT` only
when Flask's `TESTING` mode is also enabled. The strict encryption tests and
real browser checks do not use that exception. Logout submits an empty object
and continues to use the existing HttpOnly session cookie.

Passwords still use one-way scrypt hashes in the database. Session JWTs contain
only an opaque player identifier, a random session identifier and timing/issuer
metadata. Name, email and password are not token claims. Signed JWTs are not a
substitute for encrypting credentials.

HTTPS remains required on public hosts. Local loopback development uses the
existing explicit local HTTP setting. This extra encryption conceals the HTTP
request body; it cannot hide typed values from the browser's owner, a debugger
attached before encryption, malicious extensions or compromised page scripts.
The app still displays public profile names and returns the signed-in account's
display metadata as needed for the interface.

## Run after updating

Install the updated dependencies in the active environment and restart Flask:

```bash
python -m pip install -r app/requirements.txt
cd app
python -m flask --app app:app run --port 8002
```

Keep your existing `AUTH_JWT_SECRET`, database and local HTTP settings. Refresh
the page to load `auth-encryption.js`. Do not run the browser from a static file
server; the public-key endpoint is supplied by Flask.

Implementation references: [WebCrypto key agreement](https://developer.mozilla.org/en-US/docs/Web/API/SubtleCrypto/deriveBits),
[Python ECDH primitives](https://cryptography.io/en/latest/hazmat/primitives/asymmetric/ec/)
and [authenticated encryption](https://cryptography.io/en/latest/hazmat/primitives/aead/).
