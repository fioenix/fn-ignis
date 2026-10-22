# Research: Watchlist Listening and Period Comparison

Read from `main` at `4dc641e` on 21/10/2026. Not verified against live platforms.

## R1. A run is an Attention mission

**Decision**: `start_watchlist_run(watchlist_id)` creates an Attention mission whose keywords are
the union of the current version's topic keywords and brands, records a `watchlist_runs` row
binding mission and version, declares the version's brands as the mission's declared accounts
(Spec 015), and leaves execution to the existing ingress tool.

**Rationale**: Attention already withholds commercial verdicts and carries channel state; reusing
it keeps one collection path.

## R2. Period placement

**Decision**: A pure function places an observation by `published_at` converted to
Asia/Ho_Chi_Minh when it is present and plausible (not after collection, not before 2005-01-01);
otherwise by `observed_at`, flagged `collection_date`. Day, Monday-to-Sunday week and calendar
month boundaries are computed in Asia/Ho_Chi_Minh. A period is complete once its end has passed.

**Rationale**: The ADR decision; the plausibility guard stops a bad platform timestamp from moving
an item into another period.

## R3. Coverage per topic and channel

**Decision**: A channel-day is complete for a topic when some run of the watchlist recorded, for
that channel's surface, a probe outcome with status `HEALTHY` or `EMPTY_NO_DATA` whose
`queried_keywords` include at least one of the topic's keywords and whose `completed_at` falls on
that day in Asia/Ho_Chi_Minh. `AUTH_REQUIRED`, `RATE_LIMITED` and `DEGRADED` do not complete a day.

**Rationale**: Probe outcomes are already the record of what each surface actually measured
(Spec 008). A new coverage table would duplicate them.

## R4. Volume indicators

| Channel | Indicator | Source |
|---|---|---|
| Google Trends | mean interest of the topic's keywords over the period | observation `metric_value` |
| YouTube | count of relevant items published in the period | observations |
| TikTok, Threads, Reels | views and interactions of relevant items published in the period, on the collected sample | per-item selected observation |

"Relevant" means a current qualification of `QUALIFIED_SUPPORT` or `CONTEXT_ONLY` for the run's
mission; `EXCLUDED_IRRELEVANT` and unassessed items do not count. Channels are never summed.

## R5. Cumulative counters

**Decision**: For each item, the counted value is the latest observation with `observed_at` no
later than `published_at + 7 days`. An item without such an observation is listed and not counted.

**Rationale**: Fixes each item's exposure window, so earlier periods do not gain from longer
exposure and stay stable after later collections. Seven days is the agent's conservative choice.

## R6. Terms

**Decision**: Rising and new terms reuse the existing tokenisation and noise vocabulary from
`market_lexicons`; a term is new when absent from the earlier period and rising when its relevant
item count grew by at least two and by at least 50 percent. Thresholds are seeded in
`runtime_configs`, not code.

## R7. Snapshot and guide

**Decision**: `get_watchlist_period_snapshot(watchlist_id, period_kind, period_start)` returns the
current complete period against the previous one, with per topic and channel either both values
and the change, or `not_comparable` with reasons and missing days. The guide `ignis-listen`
mirrors `ignis-track`'s safeguards (local file by default, consent before publishing, nothing
shown that the snapshot lacks) and adds the per-channel labelling rules.

## R8. Request ceilings

**Decision**: `runtime_configs` keys `connector.<platform>.daily_request_ceiling`, seeded low
(YouTube 200, others 50). The registry counts requests per channel per day in Asia/Ho_Chi_Minh and
stops a channel at its ceiling with status `RATE_LIMITED` and reason `daily_ceiling`.

## R9. Retention

**Decision**: `scripts/prune_expired_observations.py --older-than-months 13 --dry-run` lists, then
deletes on `--apply`, observations older than 13 months that no retained claim, qualification or
research binding references. It is a script, not a tool, so the MCP surface is unchanged.

## R10. Constitution amendment

**Decision**: A MINOR amendment, Proposed: Principle I allows host-native routines started only on
the user's explicit request and keeps Ignis free of schedulers and workers; Principle III keeps the
ingestion clock for collection windows and evidence frames and allows publication time for
listening-period membership.

## R11. One indicator per channel needs one meaning of `metric_value` (decided 22/10/2026)

**Finding (21/10/2026, read from the connectors on the Spec 015 branch)**: `metric_value` does not
mean the same thing across channels. TikTok and YouTube store plays or views; Threads search stores
likes; Reels stores plays, or likes when a reel reports no plays; Threads trending topics store a
post count, or a placeholder of 1000 when the count is missing; the host-browser path stores none
(`metric_known = False`). R4's "views and interactions" therefore cannot be read from
`metric_value` alone without mixing units inside one channel.

**Decision (owner, 22/10/2026, as proposed)**: Part B reads each channel's indicator from the field that means it
(plays or views, likes, comments) where the connector records it in metadata, labels the unit, and
counts an item with no such field as listed but not counted, like an item without a counted
observation (FR-008). Placeholder values (the Threads 1000) never count. Snapshot assembly waits for
this decision; the pure period functions (`src/ignis/domain/listening_period.py`) do not depend on it.
