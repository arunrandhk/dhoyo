# Password recovery

From the login page, choose **Forgot password? Reset password**, enter the
account email (including Gmail addresses), and choose **Send verification code**.
Enter the six-digit code received by email, a new password, and its confirmation,
then choose **Reset password**. Passwords must contain 10–128 characters; every
character, including spaces, is preserved. After resetting, sign in with the
new password. `/ring#forgot-password` also opens recovery directly.

Codes expire after ten minutes, can be used once, and allow at most five
verification attempts. Only a scrypt code hash and the digest of an opaque
challenge identifier are stored. Request responses are identical for registered
and unregistered addresses. The code and challenge never enter the page URL.
Successful recovery revokes account sessions, other codes, legacy reset links
and failed-login limits. Failed email delivery leaves an earlier working code
usable. Codes require a configured email sender; no link base URL is needed.

Signed-in users can open **Profile → Password & security** to update their
password after confirming the current password. This keeps the current browser
signed in with a newly rotated session and signs out the account's other
devices. The same dialog offers **Send a reset code** when the current password
is forgotten. **Back to profile** returns without changing the password.

| Method | Endpoint | Input |
| --- | --- | --- |
| POST | `/api/auth/request-password-code` | `{ "email": "player@gmail.com" }` |
| POST | `/api/auth/reset-password-code` | `{ "challengeId": "…", "code": "123456", "password": "…" }` |
| POST | `/api/auth/change-password` | `{ "currentPassword": "…", "password": "…" }` |

Existing reset links remain supported, expire after 30 minutes, and can be used
once. Only a token digest is
stored in the existing PostgreSQL or explicit local SQLite state. Successful
resets revoke the account's sessions, outstanding reset links, and login lockouts.
The browser immediately removes the token from the address bar and keeps it in
memory for the reset request. Account profiles and sports data are retained.

The request response is the same for registered and unregistered email addresses.
Code and link requests share limits of three per email and twenty per client
address in fifteen minutes. Reset submissions are limited to ten per address in
that period. Signed-in password changes allow ten attempts per account and client
address in fifteen minutes.
Missing sender configuration shows a service-unavailable message. Delivery errors
are logged without tokens or credentials; recipient-specific errors keep the
generic response so they cannot reveal whether an account exists.

If a code email does not arrive, inspect the service logs for `Password reset
email failed`. Entries identify the selected provider and the failing stage
(`configuration`, `oauth`, `connect`, or `send`). HTTP failures also include a
numeric `http_status`; SMTP failures include the exception class. These logs
exclude email addresses, provider response bodies, credentials, tokens, and
verification codes. A generic request-success response alone does not confirm
delivery; provider failures must be diagnosed from these server logs.

The exact message **Password reset is temporarily unavailable. Please try again
later.** means configuration validation, Gmail authorization, or the SMTP
connection failed. It does not mean the submitted account password is wrong.
The checked-in `render.yaml` declares database settings and private Resend
inputs for new Blueprint deployments. The existing service's email sender must
be configured separately in its private Environment settings.
Adding recovery code to the repository does not create sender credentials.

Configuration failures include `invalid_fields` with only the missing or invalid
variable names. An incomplete Gmail configuration takes priority over Resend
and SMTP: supply all three Gmail credentials and `PASSWORD_RESET_FROM`, or
remove all Gmail credentials before using another provider.

For a local configuration check, run from the repository root with the same
private environment settings as the application:

```bash
cd app
../.venv/bin/python -m flask --app app password_reset check-mail
```

Add `--legacy-links` to also validate `PASSWORD_RESET_BASE_URL`. This command
reports configuration only, never displays setting values, and makes no database
or provider requests. A ready configuration still needs working provider
credentials; diagnose provider errors from the running service's logs.

Address limits currently use the connection's `remote_addr`. Behind Render's
proxy, that can be shared by multiple visitors. An operator can apply Flask's
`ProxyFix` with the verified number of trusted proxy hops to distinguish visitors;
do not choose a count or trust forwarded headers without verifying the ingress
chain. [Render's proxy guidance](https://render.com/articles/how-render-handles-ddos-attacks),
[Flask's proxy configuration](https://flask.palletsprojects.com/en/stable/deploying/proxy_fix/).

## Enable OTP delivery on an existing Render service

If no email sender is configured, the server cannot deliver an OTP. Configure
one sender before testing recovery:

1. Choose [Gmail API](#gmail-on-render) using an authorized Gmail account, or
   [Resend](#resend-on-render) using a sender on your verified domain.
2. Create the selected provider's credentials using the instructions below.
3. Open **Render → byte-ring-demo → Environment** and add its required variables:

   | Provider | Required variables for OTP email |
   | --- | --- |
   | Gmail API | `GMAIL_CLIENT_ID`, `GMAIL_CLIENT_SECRET`, `GMAIL_REFRESH_TOKEN`, `PASSWORD_RESET_FROM` |
   | Resend | `RESEND_API_KEY`, `PASSWORD_RESET_FROM` |

4. Save the environment changes and deploy. If using Resend, leave all three
   Gmail credential variables unset so they do not take priority.
5. Request one code for an account registered in this application's database,
   then verify that the email arrives and the code resets the password. If it
   does not arrive, check the provider's delivery logs and Render's safe
   `Password reset email failed` entries.

Keep real credential values in Render's private Environment settings, not in
Git or chat. These are sender credentials, separate from the account password
being reset. `PASSWORD_RESET_BASE_URL` is only needed for legacy reset links.

Updating `render.yaml` alone will not add new private credentials to this
existing service. Render only prompts for `sync: false` secrets during initial
Blueprint creation and ignores those entries during later Blueprint updates.
[Render's secret-variable instructions](https://render.com/docs/blueprint-spec#prompting-for-secret-values).

## Resend on Render

Recipients can use Gmail, Outlook, Yahoo, or other email providers. The sender
needs one domain you own and verify in Resend. For example, verify
`auth.example.com` to send from `no-reply@auth.example.com`; replace this example
with your own domain. The application's `onrender.com` hosting address is not
a sender domain you control.

1. In **Resend → Domains**, add your domain or subdomain. Copy the exact DNS
   records from its **Records** tab into your DNS provider, then verify sending.
   Record types and values can vary; use the records generated for your domain.
   [Resend domain verification](https://resend.com/docs/dashboard/domains/manage-domains).
2. In **Resend → API Keys**, create a key with **Sending access**, restricted
   to that domain. Put the key directly in Render's private settings.
   [Resend API key permissions](https://resend.com/docs/api-reference/api-keys/create-api-key).
3. In **Render → byte-ring-demo → Environment**, set:

   | Variable | Value |
   | --- | --- |
   | `RESEND_API_KEY` | The private Resend sending key |
   | `PASSWORD_RESET_FROM` | Your sender address, such as `no-reply@auth.example.com` |

4. Leave `GMAIL_CLIENT_ID`, `GMAIL_CLIENT_SECRET`, and `GMAIL_REFRESH_TOKEN`
   unset. Any Gmail credential selects Gmail instead of Resend.
5. Choose **Save and deploy** to activate the new settings. If deploying code
   changes as well, choose **Save, rebuild, and deploy**.
   [Render environment deployment options](https://render.com/docs/configure-environment-variables).
6. Request a code for your own registered application account and confirm its
   receipt. Resend's email log distinguishes accepted sends from later delivery
   failures; check Render's safe failure logs when submission fails.

`PASSWORD_RESET_BASE_URL` is unnecessary for OTP email; set it only if legacy
reset links are also needed. The application sends through Resend's HTTPS
email API, which works without SMTP access.
[Resend's send-email API](https://resend.com/docs/api-reference/emails/send-email).

The default `onboarding@resend.dev` sender can only send test emails to the email
address associated with your Resend account. Verify your own domain before
sending recovery codes to other players. A Gmail address cannot be used as your
own verified domain.
[Resend's test-sender restriction](https://resend.com/docs/knowledge-base/403-error-resend-dev-domain).

## Gmail on Render

Use the Gmail API to send over HTTPS. The repository's Render free service cannot
send outbound SMTP traffic on ports 25, 465, or 587, so Gmail SMTP and app passwords
on those ports will not work with that plan.
[Render's free-service limits](https://render.com/docs/free).

Authorize the Gmail account that will send recovery emails:

1. Create a Google Cloud project, enable the Gmail API, and configure its OAuth
   consent screen for the sender account. In **Google Auth platform → Audience**,
   add the sender as a test user when using an external application in Testing.
   [Google's consent-screen setup](https://developers.google.com/workspace/guides/configure-oauth-consent).
2. Create a **Web application** OAuth client. For the manual authorization below,
   add `https://developers.google.com/oauthplayground` as an authorized redirect URI.
3. Open [Google's OAuth Playground](https://developers.google.com/oauthplayground/),
   select **Use your own OAuth credentials** in its settings, and enter that
   client's ID and secret. Keep access type **Offline**.
4. Authorize only `https://www.googleapis.com/auth/gmail.send` while signed in as
   the sender. Exchange the authorization code for tokens and retain the refresh
   token privately. The account must match the sender address below.
5. Add these variables in the Render service's **Environment** settings, then
   deploy the application changes:

| Variable | Value |
| --- | --- |
| `GMAIL_CLIENT_ID` | Your Google OAuth client ID |
| `GMAIL_CLIENT_SECRET` | Its secret |
| `GMAIL_REFRESH_TOKEN` | The sender's refresh token |
| `PASSWORD_RESET_FROM` | The authorized Gmail address or its verified send-as alias |
| `PASSWORD_RESET_BASE_URL` | `https://byte-ring-demo.onrender.com/static/sportspace/index.html` (only required for legacy links) |

Keep credentials in Render's private environment settings. A Gmail login password
or app password is not an OAuth refresh token. The application requests access
tokens on the server and sends MIME email through `users.messages.send`; no mail
credentials are sent to the browser.
[Google's Gmail sending guide](https://developers.google.com/workspace/gmail/api/guides/sending),
[offline authorization](https://developers.google.com/identity/protocols/oauth2/web-server#offline).

Use your own OAuth client: the Playground's default credentials produce refresh
tokens that it revokes after 24 hours. External OAuth applications in **Testing**
can also have short-lived refresh tokens; follow Google's consent-screen and
authorization requirements for a lasting deployment.
[OAuth Playground instructions](https://developers.google.com/oauthplayground/),
[Google's token expiration rules](https://developers.google.com/identity/protocols/oauth2#expiration).

## SMTP on hosts that allow it

For a host that permits SMTP, leave the HTTPS provider credentials unset and set
`SMTP_HOST` and `SMTP_FROM`. Set `PASSWORD_RESET_BASE_URL` only for legacy links.
Optional settings are
`SMTP_PORT` (587), `SMTP_USERNAME` and `SMTP_PASSWORD` as a pair, and
`SMTP_USE_TLS` (true, using STARTTLS). For local testing, the base URL may use
HTTP with `localhost` or `127.0.0.1`; public deployments require HTTPS. The reset
URL always comes from this configured value, never the request's Host header.

## Diagnosing login failures

Login treats email addresses without regard to case and trims their surrounding
spaces. Passwords are compared exactly. A successful password reset clears the
account's failed-login limits. Repeated failed logins otherwise impose a
15-minute limit and report it explicitly.

Ensure Render's `SPORTSPACE_SOCIAL_DB` variable is unset when using Neon. Setting
it selects a local SQLite file, which Render can remove on restart or redeploy.
The legacy `/users` table and sample player profiles are separate from registered
accounts and cannot be used as login credentials. Database health alone does not
prove that a particular account exists.

## Inspecting the saved password

Registered accounts are stored in `public.sportspace_state`, row `id = 1`, under
`payload.accounts`; the legacy `users` table has no login password. In Neon's SQL
editor or a PostgreSQL console connected to the application's database, replace
the example with the account's email:

```sql
SELECT payload #>> ARRAY[
    'accounts', lower(trim('you@example.com')), 'password_hash'
] AS password_hash
FROM public.sportspace_state
WHERE id = 1;
```

The value starts with `scrypt:` and contains hashing parameters, a random salt,
and the password hash. It cannot reveal the original password. `NULL` means the
account or its password hash is absent; no result row means no application state
has been saved in this database. Keep the returned hash private.

To check a password you already know, use Werkzeug's
`check_password_hash(saved_hash, candidate_password)`, which returns `True` for
a match. Password characters, including spaces, must match exactly. Use the
password change or recovery flow to set a new password; never save plaintext in
`password_hash`.

## Validation

Run `.venv/bin/python -m pytest app/tests -q` and
`node app/tests/test_auth_ui.cjs`. Tests cover exact-password login after a new
application process, recovery forms, token expiry and replay, session revocation,
rate limits, sender configuration, and mocked email delivery. Test fixtures never
send real email or alter accounts on the deployed website.
