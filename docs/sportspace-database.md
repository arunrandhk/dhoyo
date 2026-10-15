# Sportspace database

PostgreSQL now stores players, teams, matches, awards, communities, posts, stories,
and preferences in `public.sportspace_state`, row 1, as a JSONB document.
The original `/users` table is independent; it is not the player directory.
Requests lock the state row so concurrent app workers cannot lose updates.
Separate player accounts and revocable login sessions are now supported. See accounts-and-photos.md for setup and limitations.

The normal runtime uses `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, and
`DB_PASSWORD` (see `db.py`). An explicit `SPORTSPACE_SOCIAL_DB` path selects
SQLite for tests/offline development. Do not set it when using PostgreSQL.

Import an existing SQLite file once before starting the updated app:

```bash
cd app
venv/bin/python migrate_sportspace.py /tmp/sportspace-social.sqlite3
```

Existing PostgreSQL state is preserved; the SQLite file is left untouched.
New databases are seeded on first access. The local PostgreSQL container uses
the persistent Docker volume `byte-devops-local-pgdata`.

Sign in, open **Profile**, and select **Edit profile** (also available on Home).
Name, location, sport, bio and photo privacy persist in the selected database.
Feed author names use player identity.
Reload the browser after direct SQL edits; the UI does not poll for changes.
Organisation grounds, bookings, tournaments and team registrations use the same
database through `/api/grounds`, `/api/bookings` and `/api/tournaments`.
They are stored under `payload.organisationService`; player profiles are stored
under `payload.arena.players`. Browser demo data is not their source of truth.

## Tournament visibility and saved records

A tournament saved as a draft is visible only to its owning organisation.
Choose **Publish for players** when creating a tournament, or open
**Organisation → Your tournaments → Publish event** for an existing draft.
Published tournaments appear under **Tournaments** for regular player accounts.
Players register their own team there and can edit its name, answers and optional
notes before registration closes. **Saved & activity** shows their saved registration.

Tournaments store `requirePlayerEmailVerification`, enabled by default in the
new-event form. Existing events default to `false` to preserve saved
registrations. When enabled, a captain must supply exactly `teamSize` different
player emails and verify a separately emailed code for each before registration.
Verification proofs are bound to the captain's account, tournament and email;
expired, unverified, reused or mismatched proofs cannot create a registration.
Saved registration `playerEmails` contain each verified email and its
verification time. Only the captain's own registration response and the owning
organisation's roster expose these private addresses. Public tournament listings
and other players' registrations do not include them. Changing a roster email
requires fresh verification; editing other team details keeps saved verified
addresses. See [tournament email verification](tournament-email-verification.md)
for delivery setup and the request/verification endpoints.

Tournament setup groups event basics, venue and schedule, teams and rewards,
participation rules, custom event details and registration questions. Organisers
can select a format or explain their own, set team size, describe prizes and
entry fees, and add eligibility, rules, contact and online platform information.
Ground setup provides the same structured public details and custom fields:
description, surface, capacity, amenities, rules and contact information. Custom
booking questions support required text or choice answers. Booking answers and
player notes are visible only to the booking player and the owning organisation.

## Money and payment records

Grounds store their hourly price, refundable deposit, payment method, payment
instructions and cancellation/refund policy. The booking form shows an itemized
hourly price, deposit and total. Tournaments store the team entry fee, cash prize
pool and the same payment terms. Supported payment methods are arrange with the
organiser, cash, UPI and bank transfer. The app records money paid directly to the
organiser; it does not collect or transfer payments.

Player bookings and tournament registrations save a snapshot of their agreed
amounts and payment terms. Subsequent ground or event edits do not reprice those
records. The server computes booking totals and registration fees; clients cannot
supply an amount or mark their own payment as received. Existing records receive
compatible defaults without replacing saved account or service data.
Booking question definitions are also snapshotted, preserving the labels and
answers even if an organiser later edits the ground's booking form.

Availability responses include the current public ground and a `quoteToken` for
its amount, deposit, payment terms and booking questions. The booking dialog
refreshes that information before confirming and submits the displayed token.
If an organiser changes those terms while the dialog is open, the server returns
409 without reserving the slot. The dialog refreshes the changed terms and asks
the player to choose a slot again. Token validation occurs in the same database
transaction as reservation creation. Existing API clients can omit the token
for compatibility; they receive the current server-calculated amount.

Only the owning organisation can record received payments or completed refunds.
Payment states are `unpaid`, `paid`, `not_required`, `refund_due`, `refunded`, and
`cancelled`. Cancelling an unpaid record cancels its payment; cancelling a paid
record marks its full amount as refund due. Recording a refund updates the ledger
and does not transfer money. The published refund policy explains the external
arrangement, while the ledger conservatively retains the full cancelled amount
until a completed refund is recorded.

After a confirmed paid ground booking ends, the owner can record the deposit
return using `paymentStatus: "deposit_refunded"`. The booking remains `paid`,
with `depositRefunded`, `depositRefundedAt`, and `depositRefundReference` recording
that separate transaction. Ground collected totals then retain only the ground
hire. A future, unpaid, cancelled, already returned or zero-deposit booking
cannot use this action.

| Method | Endpoint | Request or response |
| --- | --- | --- |
| PATCH | `/api/bookings/{id}/payment` | `{ "paymentStatus": "paid", "paymentReference": "optional reference" }`, `refunded` for a refund due, or `deposit_refunded` after a paid booking ends |
| PATCH | `/api/tournaments/{id}/registrations/{registrationId}/payment` | Owner-only `{ "paymentStatus": "paid", "paymentReference": "optional reference" }`, or `refunded` for a refund due; tournament registrations do not support `deposit_refunded` |
| GET | `/api/organisations/me` | Includes `payments` with `groundCollected`, `groundOutstanding`, `tournamentCollected`, `tournamentOutstanding`, `refundDue`, `depositReturnDue`, and `currency` |

`depositReturnDue` totals deposits on confirmed paid player bookings that have
ended and have not had their deposit returned. It is separate from cancellation
refunds in `refundDue`.

An organisation's booking of its own ground for a physical tournament is inventory
reservation only and is excluded from player payment totals. Player booking
answers/notes and tournament registration answers/notes are private, while ground
and tournament payment instructions are public.

## Custom tournament setup

**Add custom detail** adds a label and value chosen by the organiser (up to 12).
**Add registration question** adds a text or choice question (up to 8), with an
optional required setting. The event details view shows the organiser's public
information to players. Answers and player notes are visible only to the player
who registered and the owning organisation through **View teams**.

Drafts allow full editing. For a published event that has not started, **Edit
details** updates informational fields while preserving its schedule, venue,
capacity, entry fee, team size, format and registration questions. Existing events without
these new fields continue to load with defaults; no migration replaces data.

Verify actual local records with a separate read-only database connection:

```bash
cd /root/byte-devops
python3 scripts/inspect_app_data.py --sqlite /tmp/dhoyo-local.sqlite3
```

Use the exact SQLite path supplied to the server in `SPORTSPACE_SOCIAL_DB`.
Add `--tournament-id <id>` to inspect one event and its registrations, or
`--player-id <id>` to inspect a particular player's profile and registrations.
The output includes tournament IDs, names, status and player visibility; it
excludes account credentials, sessions and photos. A saved record with
`"status": "draft"` and `"visibleToPlayers": false` exists in the database but
has not been published.

Add `--include-details` to include the stored tournament options, custom details,
question definitions and private registration answers/notes in this local
administrator report. Combine it with `--tournament-id` or `--player-id` to limit
the report to the records being checked.

For PostgreSQL, activate the app virtual environment, supply the same `DB_*`
environment variables as the server, and run the script without `--sqlite`
with `SPORTSPACE_SOCIAL_DB` unset. PostgreSQL inspection uses a read-only
transaction. The script does not create tables or change records.

Connect locally:

```bash
docker exec -it byte-devops-local-db psql -U postgres -d devopsdb
```

List players:

```sql
SELECT p->>'id' AS id, p->>'name' AS name, p->>'city' AS city,
       p->>'sport' AS sport, p->'awards' AS awards
FROM sportspace_state s,
     LATERAL jsonb_array_elements(s.payload #> '{arena,players}') p;
```

List feed posts (joining the current author name):

```sql
SELECT post->>'id' AS post_id, player->>'name' AS author,
       post->>'text' AS text, post->>'sport' AS sport
FROM sportspace_state s
CROSS JOIN LATERAL jsonb_array_elements(s.payload->'posts') post
LEFT JOIN LATERAL jsonb_array_elements(s.payload #> '{arena,players}') player
  ON player->>'id' = post->>'authorId';
```

Update a player's name, city, sport and initials directly (replace the example
values and ID). Prefer the profile form/API because it also updates preferences
and existing story names. Back up before manual database changes.

```sql
BEGIN;
SELECT id FROM sportspace_state WHERE id = 1 FOR UPDATE;
UPDATE sportspace_state
SET payload = jsonb_set(payload, '{arena,players}', (
    SELECT jsonb_agg(CASE WHEN p->>'id' = 'demo-user'
      THEN p || '{"name":"Alex Kumar","initials":"AK","city":"Delhi","sport":"Tennis"}'::jsonb
      ELSE p END ORDER BY position)
    FROM jsonb_array_elements(payload #> '{arena,players}') WITH ORDINALITY AS players(p, position)
)), updated_at = now()
WHERE id = 1;
COMMIT;
```

View teams, matches, or stored preferences:

```sql
SELECT jsonb_pretty(payload #> '{arena,teams}') FROM sportspace_state;
SELECT jsonb_pretty(payload #> '{arena,matches}') FROM sportspace_state;
SELECT jsonb_pretty(payload->'preferences') FROM sportspace_state;
```
