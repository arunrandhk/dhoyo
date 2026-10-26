# Service Verticals

These are target ownership boundaries. The current application is a browser-local prototype plus a sample Flask backend, not a functioning microservice deployment.

| Vertical | Frontend responsibility | Backend-owned data | First useful delivery |
| --- | --- | --- | --- |
| Social | Feed, composer, profiles, comments, follows, saved posts | Posts, media metadata, comments, reactions, follows, bookmarks | Create and read persisted posts |
| Ground Booking | Venue discovery, availability, booking confirmation, cancellations | Venues, courts, availability, reservations | Reserve an available court without double booking |
| Tournaments | Discovery, team registration, schedule, brackets, results | Events, teams/rosters, registrations, matches, standings | Register a team once while capacity remains |

## Social

Suggested API families: `/api/posts`, `/api/posts/{id}/comments`, `/api/follows`, `/api/bookmarks`.

Posts reference the shared identity user's ID. Social owns its community profile fields; credentials belong to identity. Decide visibility and deletion rules per feature. Uploaded media requires storage, type/size validation and permissions when introduced; the prototype's external images do not implement uploads.

Initial frontend entrypoints to inspect: `postHTML`, `compose`, `railHTML`, and comment handling in `app/static/sportspace/app.js`. Function names may evolve.

## Ground Booking

Suggested API families: `/api/grounds`, `/api/grounds/{id}/availability`, `/api/bookings`.

Treat a venue and a bookable court/ground resource separately when a venue has several courts. Specify venue timezone and transmit unambiguous start/end instants. Choose explicit reservation states and cancellation rules. Enforce conflicting intervals with database transactions/constraints; a browser availability check alone cannot protect inventory. If payments are introduced, define holds, expiration and payment failure behavior as part of that task.

Tournament organizers must reserve a venue through Booking rather than write booking tables directly. A failed reservation must not appear as a confirmed tournament venue.

Initial frontend entrypoints: `grounds`, `book`, and booking activity rendering.

## Tournaments

Suggested API families: `/api/tournaments`, `/api/tournaments/{id}/registrations`, `/api/tournaments/{id}/matches`.

Support online esports and physical sports with an explicit event type. Define event dates, timezone, capacity, roster requirements and registration deadlines. Enforce duplicate/capacity constraints transactionally. Verify organizer permissions for result changes. Pick the sport's competition format before implementing brackets; use a suitable established engine when appropriate.

The demo has illustrative recurring events and registration only. Scheduling, scores, brackets and standings remain future implementation work unless assigned.

Initial frontend entrypoints: `tournaments`, `register`, and tournament activity rendering.

## Shared Identity And Integration

One identity should work across the three verticals. Identity owns credentials and login; service authorization determines what a player, venue owner or organizer may do. Real authentication is a prerequisite for user-owned production APIs, not a feature already present in this repository.

For each assigned endpoint, record method/path, request fields, response example, authenticated role, errors and persistence behavior in its task. Initial API paths above are suggestions, not implemented guarantees. Follow an existing agreed contract when one exists.

Start cross-service integrations with explicit API calls and failure handling. Do not add queues, gateways or separate deployments unless the current task benefits from them.
