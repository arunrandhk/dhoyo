# Tournament player email verification

## Activation links and acknowledgement

The organiser chooses **Player email confirmation** in the existing tournament
form: activation links (the default for new events in the UI) or six-digit codes.
This setting is locked when the event is published. Existing events keep the code
workflow. The required-email checkbox controls whether every player must have an
email; it does not require acknowledgements before an activation-link team can register.

With activation links, the captain enters player emails and registers the team.
The browser sends a separate activation email to each saved player. The team stays
registered if delivery fails, with a message to retry via **Edit team**. Captains
can resend individual emails there. New emails added when editing must be saved
before sending a link. Players remain **Pending** until they open the email and
choose **Acknowledge participation**. Captains see counts on the tournament card
and each status in Edit team; organisers see each status in the roster. Reopen the
form or refresh the tournament list to load updated statuses.

Recipients do not need an account. Loading a link alone does not acknowledge it,
so mail scanners cannot accidentally confirm participation. Links expire in 24
hours; replacing/removing an email or cancelling the registration invalidates its
links. Repeated confirmation of a valid link returns the same acknowledged state.
The database stores only token digests, tied to an internal roster identifier.
Tokens are delivered only by email, never returned by the captain API. The URL
fragment is removed before confirmation, and the page loads no third-party scripts.
Sending is rate limited and provider calls run outside the database transaction.

For either confirmation method, a captain or player email can belong to only one
active team in the same tournament. Saving a roster reserves its emails
immediately, including pending players without accounts. Registration and roster
edits check this rule together with the captain's account email. Cancelling a team
or removing a player releases that membership. The same players may enter other
tournaments. Members who later create an account see that they are already
registered. Captains retain control of editing and withdrawal; private roster
details remain visible only to the captain and owning organiser.

Activation email requires the existing Gmail/Resend/SMTP configuration **and** a
valid `PASSWORD_RESET_BASE_URL`, for example `https://your-domain.example/sportspace`.
The trusted origin of that setting is used to build `/tournament-acknowledgement`;
URLs are never built from an incoming Host header. Local HTTP is allowed only for
localhost/loopback, with the app's existing local HTTP setting enabled.

- `POST /api/tournaments/{id}/player-emails/send-activation`: `{ "email": "player@example.com" }`, sent by the captain after saving the roster.
- `POST /api/auth/tournament-acknowledgement`: `{ "token": "opaque email token" }`, submitted by the recipient page without a login.
- Tournament option: `playerEmailConfirmation: "activation_link"` or `"code"`.
- Roster status: `acknowledgementStatus: "pending"` or `"acknowledged"`, with `acknowledgedAt` after confirmation.

## Six-digit codes

The captain enters one different email address for each player in the team
registration form. The number of email rows matches the tournament's configured
team size. **Send all codes** sends a separate six-digit code to each address;
**Send code** sends or resends only that player's code. Each player gives their
code to the captain, who enters it in that player's row and chooses **Verify**.
The team can register after every listed address is verified.
If the organiser makes player emails optional, the captain can leave them all
blank or enter and verify up to the configured team size.

The tournament creation form enables **Require an email for every player** by default.
Organisers can disable it on a new event or draft. Existing tournaments default
to disabled for compatibility with their saved teams. Published events keep
their registration requirements fixed.

Codes expire after ten minutes. A proof is specific to the signed-in captain,
tournament and email address and can be consumed by one registration submission.
Each code allows at most five verification attempts. Resends for the same
captain, event and email are spaced at least 60 seconds apart. Delivery requests
are limited to three per recipient, 150 per captain and 300 per client address
in fifteen minutes.
Entering a code does not itself mark an address verified: the server must confirm
the code first. Changing an email clears its verification and requires a new
code. Email-delivery errors keep the form open with its entered values.

The captain can edit an existing team before registration closes. Unchanged
saved verified addresses remain verified; replacing addresses requires new
verification before saving. Player emails and their verification timestamps are
visible only to that captain and the owning organisation's **View teams** roster.
They are omitted from public tournament details and other players' responses.
Codes are sent in the email body and are never returned by the API or put in a
page URL.

| Method | Endpoint | Input |
| --- | --- | --- |
| POST | `/api/tournaments/{id}/player-emails/request-code` | `{ "email": "player@example.com" }` |
| POST | `/api/tournaments/{id}/player-emails/verify-code` | `{ "email": "player@example.com", "challengeId": "…", "code": "123456" }` |
| POST | `/api/tournaments/{id}/registrations` | `{ "teamName": "North Stars", "playerEmails": [{ "email": "player@example.com", "challengeId": "…" }] }`, plus any answers and note |
| PATCH | `/api/tournaments/{id}/registrations/me` | Changed team details; omit `playerEmails` to retain the saved verified roster |

When changing part of a saved roster, unchanged verified entries need only
`{ "email": "…" }`; replacement entries include their new `challengeId`.
An optional roster can be cleared by sending `playerEmails: []`; a required
roster must still contain exactly the configured team size.

The request response includes the normalized `email`, opaque `challengeId`,
`expiresIn: 600` and a message. Verification responds with `verified: true` only
after a matching code is accepted. Registration checks all proofs again in the
database transaction that reserves the team's place.

The database stores challenges under
`organisationService.playerEmailChallenges`, keyed by the SHA-256 digest of the
challenge identifier. It stores scrypt code hashes, expiry, verification and
consumption state; it does not store raw codes. Limits use hashed keys under
`organisationService.playerEmailRateLimits`. Expired entries are cleaned during
verification interactions. Failed mail delivery preserves an earlier working
code. Cancelling and registering again requires fresh verification.

## Configure email delivery

Tournament codes use the same sender configuration as password recovery. See
[Gmail, Resend and SMTP setup](password-reset.md). No reset URL is required.

| Provider | Required private settings |
| --- | --- |
| Gmail API | `GMAIL_CLIENT_ID`, `GMAIL_CLIENT_SECRET`, `GMAIL_REFRESH_TOKEN`, `PASSWORD_RESET_FROM` |
| Resend | `RESEND_API_KEY`, `PASSWORD_RESET_FROM` |
| SMTP | `SMTP_HOST`, `SMTP_FROM`; optionally `SMTP_PORT`, matching `SMTP_USERNAME` and `SMTP_PASSWORD`, and `SMTP_USE_TLS` |

Any Gmail credential selects Gmail. Otherwise a Resend key selects Resend; SMTP
is the fallback. Store sender credentials in the server's private environment.
Recipients do not need accounts in this app and can use any email provider.

Check configuration without contacting the provider or exposing credentials:

```bash
cd app
../.venv/bin/python -m flask --app app password_reset check-mail
```

If no sender is configured, sending a code shows an unavailable message and does
not claim the email was sent. Working provider credentials and a valid sender
are required to send actual email. Local tests use isolated accounts, a temporary
database and a mail sink; they never send to real recipients.
