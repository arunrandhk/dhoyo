# Account onboarding and Google sign-in

New password and Google accounts complete the same required profile: name,
international phone number, sport, city, state and country. An organisation
account also supplies its organisation name. Formatted phone numbers such as
`+91 98765 43210` are normalized to `+919876543210`. The phone number is collected
privately on the account and starts unverified. Players can verify it through
WhatsApp when WhatsApp reminders are configured. Public player profiles do not
expose phone or email.

New accounts cannot sign in or access authenticated APIs until they open the
activation email. Existing accounts without an `email_verified` field remain
compatible. Email activation also applies to Google accounts, including Google
accounts with verified email claims.

Pending players stay hidden from arena, friend and message discovery and cannot
receive friend requests, messages, support or team additions. Pending
organisations stay hidden from the organisation directory. Activation makes the
profile discoverable; existing accounts and seeded demo profiles remain visible.

## Configure email

Use the existing Gmail OAuth, Resend, or SMTP sender configuration described in
the password reset documentation. Set `PASSWORD_RESET_BASE_URL` to the trusted
public app URL, such as `https://your-domain.example/ring`. Activation links use
`#activate-token=...` so the proof does not appear in the request URL, ordinary
access logs or referrer headers. New signup returns a clear 503 while mail
configuration is unavailable; it never silently activates an account.

Activation tokens expire after 24 hours, are stored only as SHA-256 digests and
can be used once. A successful resend invalidates previous links; failed
delivery leaves an existing link usable. Resend and consumption endpoints are
rate limited. SMTP/API work happens outside the shared state transaction.
Provider credentials, ID tokens and activation links are never logged or returned
through the application API. The email contains the activation link.

## Configure Google

1. Create a Google Cloud project and configure its Google Auth Platform consent
   screen and authorised users as appropriate for its publishing status.
2. Create an OAuth client ID with application type **Web application**.
3. Add the app's exact production origin to **Authorised JavaScript origins**.
   Add the local development origin separately if needed. Google generally requires
   HTTPS except for supported localhost development origins.
4. Set the server's `GOOGLE_CLIENT_ID` to that web client ID, ending in
   `.apps.googleusercontent.com`, and restart the app.
5. Restart and open the login page. The website loads Google Identity Services
   and renders Google's button automatically when the configuration endpoint
   reports `enabled: true`. Until configured, the page shows a disabled Google
   availability message and offers email/password access. For local testing, authorise both `http://localhost`
   and `http://localhost:8002` in the Google client settings.

This uses the GIS credential callback and requires a client ID, without a client
secret or OAuth redirect endpoint. No Google account or credentials have been
created automatically. The server verifies Google RS256 signatures using
Google's fixed HTTPS JWKS endpoint, the configured audience, issuer, expiry,
issuance, verified email claim and the exact single-use nonce. Network and
cryptographic verification run outside the shared state transaction. Google
`sub`, rather than email, is the persistent linked identity.

An existing password account is never silently linked by matching email. The
user signs into Dhoyo first, chooses **Connect Google** on their profile and
authenticates the Google account with that same email. This avoids trusting a
third-party email claim as proof of ownership of an existing local account.

Google references: [server token verification](https://developers.google.com/identity/gsi/web/guides/verify-google-id-token),
[JavaScript API and nonce](https://developers.google.com/identity/gsi/web/reference/js-reference),
[client ID setup](https://developers.google.com/identity/gsi/web/guides/get-google-api-clientid).

## Deploy and open the features

The login page offers Google's button once configured. New Google users see the
same required contact/location form, without choosing a password. Existing
password users can choose **Connect Google account** on their own profile.
The activation page asks for explicit confirmation; loading an emailed URL alone
does not activate an account. An inactive login offers the resend form.

Open **Achievements & rankings** (`/ring#progress`) or **Tournament reminders**
(`/ring#reminders`) in the sidebar, on Home, or on your own player profile.
Both are visible on mobile Home. Open `/ring#signup` for the required signup form.
Signing in through a feature link returns to that feature.
See [achievement and season rules](player-progress.md)
and [reminder preferences and email scheduling](tournament-reminders.md).

Google sign-in is separate from Google Play. The optional Android app and native
Google Play Games connection have their own [setup guide](google-play-setup.md)
and website page at `/ring#google-play`. A Store link appears only after a real
listing URL is configured; Play Games stays disabled until its own credentials
are configured. Local source changes do not update the hosted Render service.

For Render, add the Google client ID, sender settings and public
`PASSWORD_RESET_BASE_URL` in the service's Environment settings, then redeploy.
The blueprint includes the public URL setting and an optional blank Google ID.
No Google client secret is needed for this callback flow.

For a short, controlled testing window only, set
`AUTH_SKIP_EMAIL_ACTIVATION=1` in the service environment and redeploy. New
password and Google accounts will be marked verified and signed in immediately,
without sending activation email. Remove the variable or set it to `0` and
redeploy as soon as testing is complete; leaving this enabled allows anyone to
register without proving email ownership.

For the existing EC2 deployment script, add optional fields to the same private
Secrets Manager JSON used by deployment: `google_client_id`,
`password_reset_base_url`, and the selected provider's settings. Resend uses
`resend_api_key` and `password_reset_from`; Gmail uses `gmail_client_id`,
`gmail_client_secret`, `gmail_refresh_token` and `password_reset_from`; SMTP uses
`smtp_host`, `smtp_port`, `smtp_from`, `smtp_username`, `smtp_password` and
`smtp_use_tls`. The deployment script passes these into the container without
printing their values. Preserve the existing required database and JWT fields.
Email reminders additionally require the scheduled command in their guide.

## Browser API contract

All POST requests require HTTPS, same-origin JSON and `X-Dhoyo-Request: 1`.
Credential and activation requests use the existing ECDH/AES-GCM auth envelope
obtained from `GET /api/auth/encryption-key?path=<exact-path>`.

| Endpoint | Clear payload inside auth envelope | Result |
| --- | --- | --- |
| `POST /api/auth/register` | `name,email,password,phone,sport,city,state,country,accountType,organisationName` | 201 `activationRequired,email,message`; no login session |
| `POST /api/auth/resend-activation` | `email` | Generic message for pending, active and unknown accounts |
| `POST /api/auth/activate-account` | `token` | Success message; then sign in |
| `GET /api/auth/google/config` | None | `enabled` and public `clientId` when enabled |
| `POST /api/auth/google/challenge` | Ordinary JSON `{}`; envelope not needed | `challengeId,nonce,expiresIn` and a private HttpOnly browser cookie |
| `POST /api/auth/google` | `credential,challengeId` | Session for linked activated account, or `onboardingRequired,name,email` and a private signup cookie |
| `POST /api/auth/google/register` | Required profile fields; Google email comes from private ticket | 201 `activationRequired,email,message`; no login session |
| `POST /api/auth/google/link` | `credential,challengeId`; requires signed-in session | `googleLinked:true,message` |

Initialize GIS with the nonce from the challenge response, then submit its
credential callback result to `/api/auth/google` or `/api/auth/google/link`.
Challenges expire in 5 minutes and are bound to the HttpOnly browser cookie and
current session cookie. Signup tickets expire in 10 minutes, are stored hashed,
and are consumed after profile creation. Each verification attempt consumes its
challenge even if Google verification fails. Start a fresh challenge for retry.

Pending password/Google login responds with 403 and `activationRequired:true`.
Google sign-in for an unlinked existing email responds with 409 and
`linkRequired:true`. `/api/auth/me` exposes `emailVerified` and `googleLinked`
for the current account without returning contact information.

## Local automated tests

Legacy domain fixtures explicitly use `AUTH_TEST_LEGACY_REGISTRATION` only while
Flask `TESTING` is true. That shortcut cannot enable legacy signup in production.
`test_account_onboarding.py` disables it and tests real onboarding with fake mail
delivery and locally signed RSA Google tokens. It never contacts Google or sends
real email.
