# Player achievements and seasonal rankings

Open **Progress** (`/ring#progress`) to see personal milestones and the quarterly player board. Google Play Games is not required: these features use dhoyo accounts and the organisation tournament service.

## What earns credit

- A captain earns registration credit for a saved, noncancelled team registration in a published tournament.
- A team member earns the same credit after the saved roster email has been verified with a code or the member has acknowledged their activation link. Email matching ignores case and surrounding whitespace. A pending invitation earns no credit.
- Members who create their dhoyo player account after their email was added are matched on the next reconciliation.
- Completion credit is recorded when the owning organisation marks a tournament completed. It confirms inclusion on the registered roster, not attendance verification, a match result, or a victory.
- Each player receives at most one registration credit and one completion credit per tournament, including a captain whose email also appears on the roster.
- Synthetic sample players, organisation accounts, legacy arena awards, profile win counts and client-submitted statistics do not earn progress.

Milestones are **Team ready** (first active registration), **First finish** (first completed tournament), **Keep showing up** (five completed tournaments), and **Across the field** (completed tournaments in two sports). Before completion, withdrawals, cancelled events and removed roster entries stop counting; the first-registration badge can become locked again if no valid registration remains. Completed credits and their achievement dates remain earned.

## Seasons and ordering

Seasons are calendar quarters in **UTC**, explicitly labelled `Q1 2035 · UTC` for example. A tournament belongs to the quarter containing its scheduled start instant converted to UTC, even if its venue's local calendar date falls in a different quarter. Registration and completion use this same quarter, so a tournament crossing a quarter boundary stays in one season.

The board orders players by completed tournaments, followed by registered tournaments. Equal counts share a competition rank (`1, 1, 3`). Player names and stable IDs only provide deterministic display order within a tied rank. Sport filtering considers the tournament sport, not the player's preferred sport. The first 100 players are shown; the response includes the full participant count and the viewer's rank even if they fall outside that window. Quarters without eligible registrations show an empty state.

## Persistence and reconciliation

`playerProgress` lives in the existing transactional state database. `sync_progress(data)` runs inside the source mutation transaction and on progress API reads. It requires no scheduler or external Google credentials. The integration calls it after successful team creation, roster changes, withdrawal, tournament lifecycle transitions and tournament-email acknowledgement.

Registration entries are keyed by stable tournament ID and account player ID. Their eligibility is reconciled with current source records. Verified roster email bindings are remembered per registration to preserve identity if the player's account email changes. Completion entries are written once using the same tournament/player key; their sport, season and earned timestamp are frozen. Renaming a profile or tournament and changing an email cannot create a second completion or erase an earned completion. Previously completed tournaments can be backfilled from their existing source registrations. If an older event has no `completedAt`, its scheduled start is used for the achievement date; new completion transitions record the actual timestamp.

## API and privacy

- `GET /api/progression/me` returns only the signed-in player's aggregate progress and achievement cards. Organisation accounts receive 403. Player IDs and filters are not accepted on this endpoint.
- `GET /api/progression/leaderboard?season=2035-Q1&sport=Football` returns the season board to signed-in accounts. Omit filters for the current UTC quarter and all sports. Seasons must use `YYYY-Q1` through `YYYY-Q4` (years 2000–9998); duplicate or unknown filters and unknown sports are rejected.
- The board contains registered player accounts with eligible activity only. It exposes display names, initials, preferred sport, photo permitted by existing photo privacy rules, participation counts and rank. Account emails, phone numbers, team rosters and registration answers are excluded.
- Existing friends-only photo settings and copied-photo redaction apply. Active image schemes, credentialed URLs and SVG data URLs are never emitted as leaderboard avatars.
- There is no public achievement-award or statistic-write endpoint. Requests made by a previous account or from a previous route are discarded by the UI, and private cached progress is cleared when the account identity changes.

## Validation

Run `python -m pytest -q app/tests/test_progression.py` and `node --test app/tests/test_progression_ui.cjs` from the repository root. The regressions exercise the real tournament lifecycle, normalized and late roster identity matching, acknowledgement, cancellation, immutable/idempotent completion history, quarter boundaries, tied and sport-filtered ranks, source and photo privacy, and stale account responses.
