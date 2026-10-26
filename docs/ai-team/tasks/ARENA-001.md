# ARENA-001: Player Achievement Arena

Status: DONE (shared-account demo scope)
Team: Lead coordinating Backend and Frontend
Service: Social / player achievements

## User Outcome

Replace the post-popularity ranking model with player achievements earned through
sport. The main page should feel like an active sporting competition, with links
to Star, Diamond, Gold and Silver categories, game results and teams.

## Interpreted Rules

The example 3 Star, 20 Diamond, 30 Gold, 40 Silver is treated as a player's
organizer-awarded medal collection, not a threshold or a number of leaderboard
positions. Clarification was requested; this is the stated working assumption.

- Organizer awards reference a completed match and an eligible participant.
- The highest organizer-awarded category is the player's badge.
- Each distinct supporter contributes 0.2 community points to that player.
- Repeated clicks toggle support; they cannot accumulate duplicate points.
- Community support does not mint organizer awards or change the official tier.
- Each category lists players with at least one organizer award in that category.
  Their category rating is organizer award count plus community points.
- Games and wins are displayed as performance context, not converted using an
  invented sport-independent formula.

## Ownership

Backend agent: arena API, social ranking migration, backend integration and tests.
Frontend agent: arena interface, player/category/team views and social UI correction.
Lead: API/UI integration verification, documentation and Docker packaging.

## Acceptance Criteria

- Main page has sport fixtures/results and working category subsection links.
- Player profile separates all four award counts and community contribution.
- Support changes by precisely 0.2 per distinct demo actor and persists.
- Organizer demo rejects unfinished matches, ineligible players and duplicates.
- Team join requests, roster addition and owner request review work with server checks.
- Post likes/comments/saves no longer award player badges.
- Existing stories, match updates, bookings and tournament pages remain reachable.
- Desktop/mobile layout, API errors, persistence and access checks are verified.

## Limitations

This remains a shared-account development demo. Fixtures and sporting results are
illustrative, not a real-time sports data source. The organizer header is a demo
role simulation, not production authorization. Real accounts and authenticated
organizer credentials are needed before public use.

## Verification

18 backend tests passed: unique support, persistence, identity migration, award
validation, duplicate protection, role/ownership checks, per-sport memberships,
team capacity, social ranking and existing API behavior.

Playwright verified the main arena, all four category links, exact 3/20/30/40
award counts, 0.2 support persistence/toggling, member addition, request approval,
join requests, organizer awards, self-support prevention, old page navigation,
story viewer and connection-error handling. Screenshots inspected on desktop and
mobile. No horizontal overflow in arena, rankings, teams or profiles at 360,
390 and 768 pixels (plus 1440-pixel arena check).

Dockerfile now includes arena/social Python modules and static files. A Docker
image build was not run. The local Flask preview runs on port 8002.
