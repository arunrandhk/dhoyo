# Player social network: focused competitor comparison

Research date: 3 October 2026. Scope: the repository's implemented beta mechanics, the user's proposed social/player-development model, and public product documentation and developer-authored app listings. No authenticated competitor accounts were created, and competitor internals, active-user counts, profitability and event delivery were not independently audited.

## Finding

No one-to-one match was verified for the complete proposed combination. Several products are substantially closer than venue-booking apps: Fitofan, Tropheo, SportsIn, Tryouts and SportsLife. The athlete social network, achievement record and competition-management components have direct precedents. The beta's precise captain-to-member feed-ranking rule was not verified elsewhere in the sources reviewed.

“Not verified” is an evidence gap, rather than proof a feature does not exist. A developer's feature description establishes a published product claim, not an independent functional test. A public ranking is also not evidence of a delivered national tournament.

## Exact comparison criteria

1. Player-authored social content, follows, comments and athlete discovery.
2. Persistent sporting identity with achievement history.
3. Organizer-issued recognition tied to competition participation/results.
4. Earned awards, community support and inherited visibility treated separately.
5. Accepted squad membership producing a bounded feed boost from the captain's award tier/support.
6. A company-operated national/international tournament offering connected to the social network.

Criteria 1–5 are represented to different degrees in the beta. Criterion 6 is the user's intended expansion; the current repository does not operate that tournament program. Current accounts and organizer access remain demo controls.

## Closest additional products

| Product | Published overlap | Remaining distinction / evidence limit |
| --- | --- | --- |
| Fitofan | Sports social network, personal medals/result history, event management and national/international federation workflows | Its documented breadth is close to the proposed ecosystem. A captain's award tier boosting accepted teammates' posts was not verified. |
| Tropheo | Organizer-issued achievements, athlete records, teams, followers, competition operations and organization-published home-feed notes | Strong recognition/competition overlap. An unrestricted player-authored social feed and the beta's captain influence were not verified. |
| SportsIn | Athlete feed, follows, communities, sport-tagged match records and city/state/country/world rankings | Strong social/performance overlap. Its published model includes user-entered scores and supporting proof; organizer-issued tier awards and a company-run national/international circuit were not verified. |
| Tryouts | Sports profiles, posts/photos, follows, player recruitment, trials/camps/tournament discovery and club tools | Strong social-to-opportunity overlap. The beta's award-tier propagation and a company-operated international circuit were not verified. |
| SportsLife | Multisport content, athlete messaging, video discovery and 24-hour stories | Strong social-interface overlap. Organizer-issued recognition and tournament progression were not verified. |
| Bharat Sports Olymps | Advertised physical-sport/esport profiles, recognition and local-to-national competition progression | Its roadmap identifies pre-launch status and its first tournament as coming soon. Treat as a competing concept, rather than proof of an operating circuit. |

Sources:

- Fitofan: [developer app description](https://play.google.com/store/apps/details?id=com.fitofan.mobile), [published social/competition experience](https://www.fitofan.ai/platform/experience).
- Tropheo: [official platform description](https://www.tropheo.com/), [developer description and release history](https://apps.apple.com/us/app/tropheo/id6747730894).
- SportsIn: [developer app description](https://play.google.com/store/apps/details?hl=en&id=com.sportsin.app). The website timed out during direct opening; the public search extract and app listing were available.
- Tryouts: [official social network description](https://tryoutssports.com/sports-social-network.php), [event discovery](https://tryoutssports.com/sports-events.php).
- SportsLife: [official features](https://sportslife.app/).
- Bharat Sports Olymps: [official concept and pre-launch roadmap](https://www.bsolymps.com/).

## Why the interfaces may look different

Products can overlap in user needs while organizing their interfaces around different workflows. Tropheo emphasizes competition records and organization operations; SportsIn emphasizes athlete-generated performance posts; Tryouts emphasizes connections and opportunities. These distinctions help explain why none necessarily feels identical to the beta's Ring/community/captain experience.

Some comparison products have mobile apps as their principal interface. A public marketing website is not a complete representation of their logged-in product. Published listings and release notes therefore informed this comparison, but they do not substitute for a full account-based audit.

## The narrower beta mechanism

The backend sets tier points to Star 4, Diamond 3, Gold 2, Silver 1. Capped captain support is added, and accepted non-owner members receive 20% of that score, with a maximum boost of 1. Pending requests receive no boost. Sources do not compound recursively, and boosts do not add together.

The feed uses the strongest source matching a post's sport for For You/Near You; Following receives no captain boost. Earned awards remain with their recipient. The boost affects post ranking, rather than guaranteeing impressions or improving every player-directory position.

References: [influence calculation](/root/byte-devops/app/arena.py:60), [feed consumer](/root/byte-devops/app/social.py:110).

This transparent relationship between recognition, accepted membership and feed ranking is the strongest narrowly defined differentiation candidate. No equivalent formula was verified in this search. It is not sufficient evidence to claim that no competing private implementation exists.

## Existing competition pathways also matter

- Challengermode documents esports communities/national leagues and reports use for international competition: [account/community guide](https://support.challengermode.com/en/start-here/how-to-sign-up-to-challengermode), [company description](https://careers.challengermode.com/).
- UTR Sports connects player ratings and event participation with its own Pro Tennis Tour: [ratings](https://www.utrsports.net/pages/how-utr-works), [tour](https://www.utrsports.net/pages/pro-tennis).

The company operating its own events is a business and delivery model. It can improve the product experience, but it is not itself evidence that social networks and competition circuits have never been connected.

## Defensible claims

- Supported: the beta demonstrates a particular separation of assigned awards, community support and captain-derived post visibility.
- Supported: the proposed product connects social participation, sporting identity, squad recruitment and company-hosted competitions.
- Supported: public sources reveal directly overlapping player-first products beyond the earlier booking-focused comparisons.
- Unverified: one existing competitor provides the complete proposed experience with the same mechanics.
- Unverified: the concept is globally unique or that the precise influence rule produces better recruiting/participation outcomes.
- Future work: authenticated organizer verification and an actual national/international competition program.

The most useful next product evidence is whether players use the social network to find suitable squads and enter competitions, and whether confirmed competition achievements create further opportunities. That evidence establishes an advantage beyond different badges or page layouts.
