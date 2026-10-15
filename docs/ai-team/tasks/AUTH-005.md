# AUTH-005: Encrypt credential request payloads

Status: COMPLETE
Service: Shared identity

The user requested that name, email and password no longer appear as readable
request-body fields. Add browser WebCrypto authenticated encryption across
login, signup, password change and both recovery flows. Preserve UI layout,
scrypt storage and minimal HttpOnly session-token claims.

Implementation uses P-256 ECDH, HKDF-SHA256 and AES-256-GCM. A bounded, expiring
single-use challenge and authenticated endpoint metadata prevent ciphertext
replay and cross-endpoint reuse. The persistent existing auth secret derives a
separate server encryption key shared by workers. Production rejects plaintext;
only explicit Flask test fixtures can bypass the envelope. There is no browser
plaintext fallback.

Changed files: `auth_envelope.py`, `auth.py`, `social.py`, `auth-encryption.js`,
`auth-ui.js`, `account-security.js`, script inclusion in `index.html`,
`requirements.txt`, targeted test fixtures and documentation.

Verification: 191 strict-encryption and existing identity/recovery API tests
passed; all seven UI test files passed. An isolated Chromium/SQLite/SMTP-sink
journey completed signup, rejected and successful login, password change,
logout, email code delivery, code reset and login with the new password. All
seven credential submissions contained only envelope metadata and ciphertext;
typed name, email, passwords and OTP were absent from the captured request
bodies. Plaintext and ciphertext replay were rejected. No browser errors and
no overflow at 390px. JavaScript syntax and whitespace checks pass.

Browser access to typed values before encryption remains possible and is
explicitly documented; HTTPS remains required for public hosts. Install the
updated dependency and restart Flask before loading the updated frontend.
