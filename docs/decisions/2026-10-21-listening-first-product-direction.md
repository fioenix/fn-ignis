# Decision: Listening-First Ignis with Host-Scheduled Routines

**Status:** Accepted by the owner on 2026-10-21, including the review refinements in PR #54
(per-channel completeness; replaying one evidence frame unless a change touches collection)
**Date:** 2026-10-21
**Scope:** Default product behaviour, recurring collection, period analysis, product measurement and
delivery order

## Context

The 2026-09-29 decision made Ignis a mission-bound, evidence-grounded research agent and gave up
continuous monitoring. Since then the verdict machinery (Market Brief, evidence qualification, Claim
Ledger, Gap Report) has held its contracts, but the product has not yet answered a real market
question with supported evidence:

- On 2026-09-25, 2 of the first 50 direct-Market signals and 0 of 50 handoff signals were relevant
  to the Brief at 0.60, and 0 of 21 conclusions reached a citation-support probability of 0.70.
- The final Market UAT (136 TikTok and Threads observations) ended in a Gap Report.

What the target users (founders preparing or starting a business, operators and analysts without
business-platform access) consume regularly is a view of how the conversation about their topics
moves over time. That needs history, which a single mission does not accumulate.

The owner settled the direction in a structured interview on 2026-10-20 and 2026-10-21.

## Decision

### Default product: listening

- Ignis listens to social channels for a user-defined, versioned **watchlist** (categories,
  keywords and brands at brand level), plus a small discovery slice inside the watchlist's
  categories. Open, category-free discovery is not a goal.
- Analysis compares complete calendar periods in Asia/Ho_Chi_Minh: day, week (Monday to Sunday) and
  calendar month.
- Every observation is counted on its publication date. One without a publication date is counted
  on its collection date and flagged. This departs from Constitution III, which requires time-window
  queries to use the exact ingestion clock; the Spec 016 constitution amendment must state it.
  Period membership for listening uses publication time, while collection windows and evidence
  frames keep the ingestion clock.
- A day with no collection run is "no data", never zero. Completeness is judged per watchlist topic
  and channel: a channel-day is missing when that channel did not complete for that topic that day,
  and a channel is compared only when both periods have no more than 20 percent of their days
  missing for it.
- Per watchlist topic, the period view shows each channel's own volume indicator. Channels are never
  summed together. The indicators are Google Trends interest; YouTube new uploads in the period; and,
  for TikTok, Threads and Reels, views and interactions of relevant items published in the period,
  labelled as measured on the collected sample. The view also shows rising and new terms, three
  representative items (content only, no author) and each channel's status.
- Views and interactions are cumulative counters, and one source can be observed several times.
  Spec 016 must fix which observation counts, for example the value at a fixed age after
  publication, so that an older period does not gain from longer exposure and past figures do not
  change after later collections.
- The host agent filters relevance with the existing evidence-qualification tools. Ignis does not
  call an external model in its pipeline.
- The agent renders the period view as a local HTML artifact; nothing is sent elsewhere by default.
  `ignis-track` renders exactly one mission's snapshot, so Spec 016 defines a watchlist-period
  snapshot and its own rendering guide. That guide inherits the `ignis-track` display safeguards:
  local by default, consent before publishing, and nothing shown as permitted that the store does
  not permit. Sentiment and pain-point summaries are deferred.

### Verdict mode: kept and frozen

The Market Brief, Claim Ledger and Gap Report path stays available when a user asks a specific
decision question. It receives no new investment until listening is measured.

### Recurring collection runs in the host, not in Ignis

- The Ignis server has no worker, scheduler or background loop. This part of the 2026-09-29
  decision stands.
- A user who wants continuous listening asks for it, and an Ignis skill sets up a routine with the
  host's native scheduler. Each routine run is a separate Attention mission bound to one watchlist
  version. Analysis aggregates the missions of a watchlist, deduplicated by source.
- An agent never sets up a routine the user did not ask for.
- Ignis does not backfill missed days on its own. A re-run that the harness or the user starts
  collects what the platforms still return. Date-bounded channels (YouTube, Google Trends) can
  target the missed day. TikTok, Threads and Reels collect a window anchored to the run time, so
  their items reach the missed day only through their publication date, and that channel-day stays
  incomplete. A missed day therefore remains a visible gap unless a channel can target it.
- Each channel has a per-day request ceiling, low by default and raised by the user, so that daily
  collection does not put the user's personal account at risk.
- Collected data is retained for 13 months.
- Host order: Claude Desktop local scheduled tasks first, because they reach local MCP servers and
  local SQLite. Codex scheduled tasks follow after a probe, since their MCP access is undocumented.
  Cloud routines cannot reach a local server or the user's browser sessions, so they come later and
  only for API channels with a remote database.

### Measurement: a golden set as an acceptance gate

- Four watchlists (low-sugar bottled drinks for office workers; light sun- and rain-proof jackets
  for motorbike commuters; cat litter and food for urban apartments; matcha drinks) measure
  listening. Two decision questions (an AI operations assistant for small retailers; inventory
  software for small garment workshops, a negative control expected to end in a Gap Report) are
  regression tests for verdict mode.
- Primary metric: the share of the first 50 signals per watchlist that Jev rates relevant at 0.60.
  Hard constraint: no comparison is shown for a period that cannot be compared. The verdict-mode
  regression questions use 0.70 citation support, as in the 2026-09-25 review.
- Both 0.60 and 0.70 are benchmark criteria for scoring the golden set, not runtime thresholds.
  Spec 008 deliberately kept those review thresholds out of production, and its deterministic
  sufficiency policy is unchanged.
- Jev scores every run, pinned to one version per comparison (currently jev-1.14.0). The
  2026-09-25 fixture, scored with jev-1.13.0, is re-scored with the pinned version to give a
  baseline on the same scale. Jev scores and never filters, so the gate does not grade its own
  output.
- A change that affects conclusion quality is accepted only if its branch scores no lower than
  `main` on the same input and breaks no hard constraint. A change that does not touch collection
  (qualification, analysis, guides) replays one captured evidence frame on both revisions. A
  connector change cannot share input with `main`, so both revisions run live on the same day, and
  the result is read against collection variance; Spec 016 sets how much variance is tolerated.
- Numeric targets are set after the first baseline run.

### Order

1. Spec 015: no author identity at rest. Daily collection through personal accounts makes this a
   prerequisite.
2. Spec 016: versioned watchlists, period comparison, the period-view guide, and the constitution
   amendment below. Usable through manual runs.
3. The golden-set baseline run.
4. Spec 017: the routine-setup skill, Claude Desktop first.
5. A spike on public commerce demand signals (Shopee, Lazada).

## Consequences

### Benefits

- The default output is something a user can read every week, and its quality is measured rather
  than asserted.
- Continuous listening comes from the user's own agent, so Ignis carries no scheduler, worker or
  hosting cost, and the user stays in control of when their accounts are used.
- The evidence-grounding contracts remain; verdicts stay possible without being the default path.

### Costs

- History depends on the user's machine being awake and the host app running. Missed days are
  visible gaps.
- Per-channel indicators cannot be added up into one market number.
- Retaining 13 months of observations makes the local database grow.

## Relation to earlier decisions

This decision amends the 2026-09-29 Mission-Bound Evidence-Grounded Ignis decision in two places:

- "no scheduled discovery, daily auto-collection" now means "no scheduling inside Ignis";
  user-requested routines in the host are allowed;
- "gives up continuous monitoring and baseline trend accumulation" no longer holds for
  user-requested watchlists.

It also needs one constitution change beyond the scheduling boundary. For listening periods,
publication time decides which period an observation belongs to (Constitution III today requires
the ingestion clock for time-window queries).

Everything else in that decision stands, including mission-bound collection, fail-closed verdicts and the
`ATTENTION` and `MARKET` distinction. The constitution amendment that states these boundaries is
part of Spec 016.

## Implementation authority

This decision authorizes specification and planning of Specs 016 and 017. It does not by itself
authorize a migration, an MCP signature change, a constitution amendment, a release or sending
data outside the user's machine. Those keep their owner gates.
