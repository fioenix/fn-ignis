# Research: Goal-Driven Listening Period

All unknowns from the Technical Context are resolved below. Sources are the code on `main` at
`ba2e064` and the stored G3 runs in the caller store (26/10/2026).

## R1. Where the listening plan lives

- Decision: an append-only `watchlist_listening_plans` table keyed by watchlist and
  `effective_from`; the plan in effect for a period is the latest row whose `effective_from` is at
  or before the period's start.
- Rationale: versions are immutable and describe what a run collects (Spec 016 FR-001); the plan
  changes how results are read and how often to collect (spec Assumptions). FR-003 requires each
  period to be judged against the plan recorded for it, so history must survive a change.
- Alternatives considered: a field in the version definition (would mint a version for a cadence
  change and change `definition_digest`, which runs bind to); columns on `watchlists` (loses
  history, breaks FR-003).

## R2. What one snapshot is

- Decision: one snapshot is one run's latest completed collection of one channel whose outcome
  completes (`HEALTHY` or `EMPTY_NO_DATA`) and whose queried keywords meet the topic; its time is
  that outcome's `completed_at`; its items are the run's signals for that channel.
- Rationale: these are exactly the probe outcomes the period use case already reads per run
  (`get_latest_completed_probe_outcomes`), so coverage and partial-keyword rules carry over
  unchanged (spec Edge Cases). The exact ingestion clock satisfies Constitution III for the seen
  axis.
- Alternatives considered: one snapshot per run across channels (hides a channel that failed);
  per-signal `captured_at` (several timestamps per collection, no single snapshot time).

## R3. Seen-axis indicators

- Decision: per topic, channel and period, averages per snapshot of: relevant items shown;
  interactions and views visible at snapshot time, read with the existing `channel_values`;
  items first seen in that snapshot (the watchlist-wide `first_seen` the use case already
  computes); items whose publication falls in the period (spec FR-007); and rising and new terms
  over the items shown, reusing `_term_lists`.
- Rationale: averaging per snapshot keeps a period with more snapshots from reading higher
  (spec US2); every input already exists in the use case.
- Alternatives considered: sums per period (biased by snapshot count); medians (unstable at three
  snapshots a week).

## R4. Comparability on the seen axis

- Decision: missing = snapshots the plan calls for in the period − successful snapshots; a channel
  is comparable when missing ≤ 20 percent of the snapshots called for, in both periods. A period
  with no plan in effect is "not comparable" with reason `seen_period_without_cadence`.
- Rationale: spec FR-006 and Clarifications answer 2; reuses `MAX_MISSING_SHARE`.
- Alternatives considered: fixed minimums per period kind (rejected by the owner in clarification).

## R5. Judged snapshots

- Decision: a snapshot with any unassessed relevant-candidate observation on that channel leaves
  the channel unjudged for the period, reported as `seen_period_unjudged_snapshots`.
- Rationale: mirrors the judged-day rule (Spec 016 Clarifications 2026-10-26) so an unjudged run
  never reads as a measured zero.

## R6. MCP surface

- Decision: a new tool `set_watchlist_listening_plan` rather than new arguments on
  `save_watchlist`; `period_kind` on the snapshot tool becomes optional.
- Rationale: `save_watchlist` mints versions, and a cadence change must not (R1); keeping the
  write separate keeps `save_watchlist`'s idempotence contract intact. The caller-storage
  middleware already scopes tools whose name contains `watchlist`.
- Alternatives considered: optional arguments on `save_watchlist` (mixes a versioned and an
  unversioned write in one call).

## R7. Routine cadence on the host scheduler

- Decision: the routine guide turns "N snapshots per week" into a cron on N distinct weekdays
  spread across the week (for example 3 → Monday, Wednesday, Friday) and "per month" into distinct
  days of the month; it shows the requests per period from the channels' keyword counts.
- Rationale: Claude Code Desktop local tasks take a cron expression (Spec 017 FR-009); distinct
  days avoid weekday bias; no Ignis-side scheduling.
- Alternatives considered: an interval cron such as every 2 days (drifts across week boundaries,
  so a week can hold 3 or 4 snapshots).
