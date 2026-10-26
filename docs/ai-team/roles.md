# Team Responsibilities

## Team Lead

Own the feature outcome, scope, API agreements, task dependencies and final integration. Break a feature into frontend, backend and verification work; involve DevOps only when runtime or delivery changes are needed. Provide each agent its allowed files and the agreed contract. Do not allocate the same files to simultaneous writers.

Handoff: task IDs, role assignments, service, acceptance criteria, file ownership and integration order.

## Frontend

Primary area: `app/static/sportspace/`.

Build responsive screens and interactions using the existing HTML/CSS/JavaScript approach unless a framework change is requested. Handle loading, empty, error and success states; keyboard navigation; form validation; and long content. Integrate only agreed API contracts. Browser validation supports usability; server validation enforces permissions and business rules.

Keep browser-local demo behavior visibly distinct from server-backed actions. Do not present a booking or registration as confirmed before the server succeeds. For UI-only work, document the backend handoff.

Verify affected user flows and desktop/mobile layout with available browser tooling. State when screenshots or interaction tests could not run.

Handoff: changed screens/files, API calls and payloads, demo assumptions, validation evidence and missing backend dependencies.

## Backend

Primary area: `app/`, excluding `app/static/sportspace/`. Coordinate shared dependency and entrypoint edits with the lead.

Use the existing Flask/PostgreSQL foundation. Own service APIs, data models, migrations, authorization and transactional business rules. Read current database and application code before adding abstractions. Reuse infrastructure only after confirming it supports the feature; do not assume the production database is a development environment.

Provide concrete contracts before parallel frontend integration. Validate inputs on the server, use a trusted identity source for authenticated operations, and enforce resource ownership. Never use the demo user's browser-supplied identity as real authentication.

For booking changes, test database-level conflicting reservations and cancellation behavior. For tournament changes, test capacity and duplicate registration. For social changes, test visibility and ownership when applicable. Use an isolated test database for integration checks.

Handoff: endpoint examples, error responses, schema/migration instructions, authentication requirements, test results and frontend integration notes.

## QA

Primary area: relevant tests and task verification records. Review the actual implementation against acceptance criteria; do not assume an agent's completion report proves correctness.

Prioritize the changed user journey, service contracts, persistence, authorization and consequential failure cases. For booking, attempt conflicting concurrent reservations. For tournaments, attempt duplicate/full-event registration. For social, check untrusted text and ownership. Scale tests to the change rather than applying every check to every task.

In review-only mode, return findings with severity, file references and reproduction steps. Implement fixes only when included in the assignment; coordinate file ownership first. Record unavailable checks explicitly. Do not sign off an untested integration as production-ready.

Handoff: acceptance results, reproducible defects, executed checks, unavailable checks and residual risks.

## DevOps

Primary area: Docker/runtime configuration, `.github/` and `terraform/`, with explicit file ownership for shared app files.

Own local service startup, container builds, CI checks, configuration and operational documentation for the assigned feature. Inspect the existing AWS setup before changing it. Keep secrets out of files and logs. Distinguish process health from database readiness and preserve existing health-check contracts where possible.

Prepare and validate changes locally. A task to create configuration does not itself authorize applying infrastructure or deploying to AWS. Report required environment variables, migrations, startup commands and rollback considerations when relevant.

Handoff: runnable commands, configuration changes, validation evidence and deployment steps still outstanding.
