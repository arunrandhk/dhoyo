# Tournament reminders

Open **Reminders** (`/ring#reminders`) after completing account activation and the required profile details. The private inbox shows the next 100 upcoming tournament starts and registration closing deadlines for the signed-in account's active registrations, including membership saved under that account's normalized email. It never returns team rosters, other players' contact details, registration answers or captain notes.

In-app reminders start enabled; email starts disabled. Read/dismiss state and preferences persist on the server separately for every account. Users can choose any of 48, 24, 6 and 1 hours before each deadline (default: 24 and 1). Upcoming cards are available immediately, even before a selected threshold. The page formats dates in the device's local timezone, refreshes every minute while visible, and offers a Refresh button. It does not request browser notification permission or provide background push notifications.

Schedule changes replace the affected reminder with the new time and fresh read/dismiss state. Cancelled/draft tournaments, withdrawn teams, removed roster members and elapsed deadlines disappear on the next refresh. A registration-closing card is a reminder to finish team changes, not an invitation to register again.

## Optional email delivery

Email reminders use the existing configured Gmail OAuth, Resend or SMTP sender. Users must explicitly enable email; unverified accounts are excluded. Preferences can be saved before a sender is configured, and the page explains when delivery is unavailable. Dismissing a reminder also suppresses future emails for that specific deadline and schedule. Read state does not suppress email. In-app reminders can be disabled independently.

The website does not start a mail daemon. Run the following command against the same production database and private environment as the website, every five minutes using your scheduler:

```sh
cd app
flask --app app reminders send-due --limit 100
```

For example, if an application's working directory is `/srv/dhoyo/app` and its existing environment is available to cron:

```cron
*/5 * * * * cd /srv/dhoyo/app && /srv/dhoyo/.venv/bin/flask --app app reminders send-due --limit 100
```

Use your actual deployment paths. Gmail needs the existing `GMAIL_CLIENT_ID`, `GMAIL_CLIENT_SECRET`, `GMAIL_REFRESH_TOKEN` and `PASSWORD_RESET_FROM`; Resend needs `RESEND_API_KEY` and `PASSWORD_RESET_FROM`; SMTP needs `SMTP_HOST`, `SMTP_FROM`, and any required `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD` and `SMTP_USE_TLS`. Reminder messages do not need `PASSWORD_RESET_BASE_URL`. `flask --app app password_reset check-mail` checks sender configuration without sending mail. Do not put credentials in the cron line or repository.

Each run sends at most the requested limit (1–500). Each account is limited to 20 attempts per hour. If a job runs late or an account joins after an earlier threshold, it sends only the nearest already reached threshold: a first run 30 minutes before a tournament sends the 1-hour reminder, not both the 24-hour and 1-hour messages. A message is no longer eligible after its deadline. The remaining selected threshold can still send later in the normal way.

Delivery receipts are persisted before provider contact; concurrent workers cannot claim the same receipt. No provider network call occurs while the database row is locked. Immediately before sending, the worker checks current opt-in, verification, membership, schedule and dismissal. The sender reports only aggregate counts and never logs the roster or reminder content.

Successful receipts do not resend. Explicit delivery failures retry after five minutes, with a maximum of three attempts per account/deadline/threshold. An exception during delivery or an abandoned reservation older than 15 minutes becomes `uncertain` and is not retried automatically: the provider may already have accepted it. Delivery is best effort rather than an exactly-once guarantee; provider timeouts can leave an uncertain outcome, and changes made during an external send cannot recall an email already submitted. Receipts expire seven days after their deadline, with at most 512 retained receipts per account. State for obsolete reminders is removed on refresh.

## API

All routes require an activated, complete, signed-in account and the standard same-origin/JSON mutation protections.

| Request | Behavior |
| --- | --- |
| `GET /api/reminders` | Own account ID, own visible notices, own preferences, unread count, server time and sender configuration status. |
| `PATCH /api/reminders/preferences` | Partial update: `inApp` and `email` booleans and distinct `leadHours` from `[48,24,6,1]`. |
| `PATCH /api/reminders/<id>` | Update `read` or `dismissed` booleans for a currently joined, upcoming notice. Other accounts' notices return 404. |

Persistence uses `tournamentReminders.users` within the existing locked application state; no separate database or new external service is required.

## Verification

```sh
.venv/bin/python -m pytest app/tests/test_reminders.py -q
node --test app/tests/test_reminders_ui.cjs
```

Tests replace provider delivery with an in-memory stub; they do not send real email. Coverage includes authenticated captain/member privacy, state isolation, opt-in and validation, changed/cancelled/withdrawn events, deadline timing, idempotent concurrent reservations, bounded retries, uncertain outcomes and database-lock release during delivery.
