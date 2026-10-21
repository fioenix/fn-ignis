# Feature Specification: Watchlist Listening and Period Comparison

**Feature Branch**: `codex/spec016-watchlist-listening`

**Created**: 2026-10-21

**Status**: Draft

**Input**: The owner's accepted decision record
[`docs/decisions/2026-10-21-listening-first-product-direction.md`](../../docs/decisions/2026-10-21-listening-first-product-direction.md)
(Accepted 21/10/2026). Make listening the default product: a user names what to follow, Ignis
collects it on each run, and the user reads how the conversation about each topic moved between
complete calendar periods. Spec 017 (the routine-setup skill) and commerce channels are out of
scope.

## Outcome and audience

A founder preparing or starting a business, an operator or an analyst follows a handful of
categories, keywords and brands over weeks. Each time they (or their own agent's routine) run
Ignis, the run adds to that history. They then read, per topic and per channel, what rose, what
appeared and what faded between two complete periods, with every number labelled by where it came
from and with gaps shown as gaps.

The decision this supports is the owner's: listening is what users consume regularly, while a
market verdict is rarely supportable with today's evidence (0 of 21 conclusions supported on
25/09/2026). The observable proof is a period view that compares only what is comparable and never
shows a number for a period or channel that lacks the data.

## Context: current state (observed 21/10/2026 on `main` at `4dc641e`)

Read from the code, not from production data:

- An Attention mission collects for one title, seed and keyword list over one rolling timeframe
  (`create_attention_mission`, default `7d`). Nothing ties two missions to the same subject, so
  two runs cannot be compared.
- Observations record both an exact collection time and, when the platform reports it, a
  publication time. Time-window queries use the collection clock (Constitution III).
- The Threads and Reels connectors anchor their search window to the time of the run.
- `ignis-track` renders one mission's snapshot as a point-in-time artifact and refuses pages from
  another mission or frame.
- Spec 015 (on its own branch) removes author identity before storage; this feature assumes its
  identity-free observations.

## Clarifications

### Session 2026-10-21

Decided by the owner in the accepted decision record (20–21/10/2026):

- Q: What does a user follow? → A: A versioned watchlist of topics; each topic holds categories,
  keywords and brands at brand level, plus a small discovery slice inside the topic's categories.
  Open, category-free discovery is not a goal.
- Q: What is a run? → A: One Attention mission bound to one watchlist version.
- Q: Which periods? → A: Complete calendar day, week (Monday to Sunday) and month in
  Asia/Ho_Chi_Minh. Only complete periods are compared.
- Q: Which date places an observation in a period? → A: Its publication date; without one, its
  collection date, flagged.
- Q: What about missing days? → A: A day without a run is "no data", never zero. Completeness is
  judged per topic and channel; a channel is compared only when neither period misses more than
  20 percent of its days for it.
- Q: What does the view show? → A: Per topic and channel, the channel's own volume indicator
  (never summed across channels), rising and new terms, three representative items without
  authors, and channel status. Sentiment and pain-point summaries are deferred.
- Q: How is the view rendered? → A: By the host agent as a local HTML artifact from a dedicated
  watchlist-period snapshot and its own guide, inheriting `ignis-track`'s display safeguards.
- Q: Who filters relevance? → A: The host agent, with the existing evidence-qualification tools.
- Q: Retention? → A: 13 months.
- Q: Recurring collection? → A: Allowed only through the host's native scheduler on the user's
  explicit request; Ignis keeps no scheduler or worker. Setting it up is Spec 017.

Decided by the agent under the owner's delegation of 21/10/2026, conservative defaults, owner to
confirm (listed again under "Owner review"):

- Q: Which observation of a cumulative counter counts? → A: The latest observation collected no
  later than 7 days after publication. Items with no such observation are listed but not counted.
- Q: How many topics and keywords may a watchlist hold? → A: At most 10 topics and 20 keywords per
  topic, to keep runs inside the per-channel daily request ceilings.
- Q: How large is the discovery slice? → A: At most 20 percent of a run's requests per topic.
- Q: How much collection variance is tolerated when a connector change is compared live against
  `main`? → A: None is assumed: such a comparison is reported with both scores and is not an
  automatic pass; the golden-set procedure owns the decision.
- Q: How does this feature land while the constitution amendment (FR-015) awaits the owner? → A: In
  two pull requests. The first carries watchlists, versions, runs, the per-channel daily ceilings and
  the retention action (US1, US4), which current Principles I and III already allow. The second
  carries the period comparison, the period snapshot, the `ignis-listen` guide and the Proposed
  amendment (US2, US3); it merges only after the owner ratifies the amendment, because placing
  observations in periods by publication time conflicts with Principle III as ratified (agent
  decided; basis: Constitution Governance requires an explicit owner decision for an amendment and
  AGENTS.md section 8 leaves additive tools and migrations to the agent; cost if wrong: one merged
  pull request instead of two).
- Q: Does a run inherit the authority of an earlier run? → A: No. `start_watchlist_run` takes
  `allowed_resources` and `authority_boundary` on every call, as `create_attention_mission` does, so
  each mission's manifest states its own consent (agent decided; basis: Constitution I and the
  Spec 011 manifest contract; cost if wrong: a routine prompt restates two fields).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Follow a watchlist across runs (Priority: P1)

A user defines a watchlist ("low-sugar bottled drinks for office workers": two categories, eight
keywords, two brands) and runs it. A week later they run it again. Both runs belong to the same
watchlist version and their observations are available together.

**Why this priority**: Without a stable subject across runs there is no history and nothing to
compare.

**Independent Test**: Create a watchlist, run two missions bound to it on fixtures, and read the
watchlist's history: both runs and their observations are listed, deduplicated by source.

**Acceptance Scenarios**:

1. **Given** a watchlist, **When** the user starts a run, **Then** the run is an Attention mission
   bound to the watchlist's current version and collects only that version's topics.
2. **Given** a watchlist with two runs, **When** the user edits a topic, **Then** a new version is
   created, the earlier runs stay bound to the earlier version, and the history says which runs
   belong to which version.
3. **Given** a brand in a watchlist, **When** collection stores its content, **Then** only the
   brand is kept as a declared account (Spec 015); no other author is kept.

### User Story 2 - Compare two complete periods (Priority: P1)

The user asks for this week against last week. For each topic and channel, Ignis returns the
channel's own volume indicator for both weeks and the change, rising and new terms, and three
representative items, or says why that channel cannot be compared.

**Why this priority**: This is the product the owner chose as the default.

**Independent Test**: With fixture observations spanning two complete weeks and one channel
missing three days in one week, the comparison shows numbers for complete channels and "not
comparable" with the reason for the incomplete one.

**Acceptance Scenarios**:

1. **Given** two complete weeks with every channel present on every day, **When** the user compares
   them, **Then** each topic and channel shows both values and the change, and no value sums
   channels.
2. **Given** a channel missing more than 20 percent of its days in either period, **When** the user
   compares, **Then** that channel shows "not comparable" with the missing days, and no change is
   shown for it.
3. **Given** the current week, **When** the user compares it, **Then** the comparison refuses
   because the period is not complete, and says when it will be.
4. **Given** an observation without a publication date, **When** it is placed in a period, **Then**
   it uses its collection date and is flagged as such in the view.
5. **Given** posts collected several times, **When** engagement is counted, **Then** each post
   contributes the value from its latest observation collected within 7 days of publication, so a
   period's figures do not change after later collections.

### User Story 3 - Read the period view (Priority: P2)

The host agent reads one watchlist-period snapshot and renders a local HTML artifact that states
for every number its channel, its period, and whether it was measured on the collected sample.

**Why this priority**: The comparison is useful only when read correctly.

**Independent Test**: Render the period view from a fixture snapshot following the guide; check
that nothing absent from the snapshot appears and that "not comparable" channels show no change.

**Acceptance Scenarios**:

1. **Given** a snapshot, **When** the agent follows the guide, **Then** the artifact is written
   locally and nothing is published without the user's consent.
2. **Given** a snapshot whose watchlist version changed between the periods, **When** the agent
   renders it, **Then** the artifact states the version change.

### User Story 4 - Keep collection bounded and history finite (Priority: P3)

Each channel has a daily request ceiling the user can raise; collected data older than 13 months
is removed.

**Independent Test**: A run that would exceed a channel's ceiling stops that channel with status
"ceiling reached" and continues the others; a retention pass removes only observations older than
13 months that no other retained evidence references.

### Edge Cases

- A run that spans midnight: each observation is placed by its own date, not by the run's.
- Two runs on one day: their observations are deduplicated by source; the day is complete for a
  channel if either run completed it.
- A platform reports a publication time in the future or before 2005: the observation is placed by
  its collection date and flagged.
- A watchlist edited mid-period: the comparison states both versions and compares only topics
  present in both.
- A day re-run later: date-bounded channels may fill it; others stay incomplete (ADR).
- A channel that never ran for a topic: it is listed with status "not collected", never as zero.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Users MUST be able to create, read and revise a watchlist of at most 10 topics, each
  with categories, up to 20 keywords and brands; every revision creates a new immutable version.
- **FR-002**: A run MUST be an Attention mission bound to exactly one watchlist version and MUST
  collect only that version's topics, with at most 20 percent of a topic's requests spent on
  in-category discovery.
- **FR-003**: Brands in a watchlist MUST be recorded as declared accounts of each run (Spec 015);
  no other author identity is kept.
- **FR-004**: The system MUST place each observation in calendar periods (day, Monday-to-Sunday
  week, month) in Asia/Ho_Chi_Minh by publication date, and by collection date with a flag when no
  plausible publication date exists.
- **FR-005**: A day with no completed collection for a topic and channel MUST be "no data", never
  zero; a channel MUST be compared only when neither period misses more than 20 percent of its days
  for that topic.
- **FR-006**: Only complete periods MAY be compared; a request for an incomplete period MUST be
  refused with the time it completes.
- **FR-007**: Each channel's volume indicator MUST be reported separately and never summed:
  Google Trends interest; YouTube new uploads in the period; TikTok, Threads and Reels views and
  interactions of relevant items published in the period, labelled as measured on the collected
  sample.
- **FR-008**: A cumulative counter MUST count the value of the latest observation collected within
  7 days of the item's publication; an item without one is listed but not counted.
- **FR-009**: The comparison MUST return rising and new terms per topic and channel, and at most
  three representative items per topic, with content only.
- **FR-010**: Relevance MUST come from the existing evidence-qualification outcomes; an unassessed
  observation MUST NOT count toward a volume indicator.
- **FR-011**: The system MUST expose one read-only watchlist-period snapshot that holds everything
  the period view shows and nothing else, with the watchlist version(s) and completeness per topic
  and channel.
- **FR-012**: A packaged period-view guide MUST tell the host agent how to render the snapshot as a
  local artifact, inheriting `ignis-track`'s safeguards: local by default, consent before
  publishing, nothing shown that the snapshot lacks.
- **FR-013**: Each channel MUST have a per-day request ceiling with a low default the user can
  raise; reaching it MUST stop that channel for the day with a visible status.
- **FR-014**: Observations older than 13 months MUST be removable by an explicit retention action
  that keeps anything still referenced by retained claims or evidence; Ignis MUST NOT run it on a
  schedule of its own.
- **FR-015**: The constitution MUST be amended (Proposed for owner ratification) so that listening
  periods use publication time while collection windows and evidence frames keep the exact
  ingestion clock, and so that host-native routines are allowed only on explicit user request with
  no scheduler or worker inside Ignis.
- **FR-016**: Behaviour MUST be identical on SQLite and PostgreSQL.

### Key Entities

- **Watchlist**: a named subject the user follows; owns its versions.
- **Watchlist version**: immutable topics, categories, keywords, brands and discovery share.
- **Watchlist run**: the link between a mission and the version it collected.
- **Period**: a calendar day, week or month in Asia/Ho_Chi_Minh.
- **Channel-day coverage**: whether a channel completed collection for a topic on a day.
- **Period comparison**: per topic and channel, two periods' indicators or the reason they cannot
  be compared.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Two runs of one watchlist version on fixtures produce a combined history with zero
  duplicate sources.
- **SC-002**: On a fixture with one incomplete channel, 100 percent of comparisons for that channel
  show "not comparable" and none shows a change.
- **SC-003**: No comparison output contains a value summed across channels.
- **SC-004**: Re-running collection a week later leaves the earlier period's counted engagement
  unchanged.
- **SC-005**: The period view rendered from a fixture snapshot contains no number absent from the
  snapshot.
- **SC-006**: Every requirement passes on both backends.
- **SC-007**: On the golden set's four watchlists, the share of the first 50 signals Jev rates
  relevant at 0.60 is measured and recorded as the baseline; no target is set by this feature.

## Assumptions

- Spec 015 is merged first, so observations carry no author identity and brands map to declared
  accounts.
- The host agent performs relevance qualification; Ignis calls no external model.
- Spec 017 sets up recurring runs; until then users run watchlists by hand.
- Commerce channels, sentiment and pain-point summaries are out of scope.

## Owner review

Agent decisions under the owner's delegation of 21/10/2026, to confirm or change:

1. Cumulative counters use the latest observation within 7 days of publication (FR-008).
2. Watchlist limits: 10 topics, 20 keywords per topic (FR-001).
3. Discovery slice: at most 20 percent of a topic's requests (FR-002).
4. Live connector comparisons are reported with both scores and are never an automatic pass.
5. The constitution amendment text (FR-015) stays Proposed until ratified.
6. The landing: US1 merges first; US2 and US3 wait for the amendment; US4 is re-planned because the
   daily ceiling needs a persistent per-day request count.
7. A run restates `allowed_resources` and `authority_boundary` every time; nothing is inherited
   from an earlier run.
8. The discovery share is stored with each version but not spent by collection until a later part.
9. A revision keeps the watchlist's name; renaming is refused.
10. Brand accounts a user names stay in every immutable version that named them, also after a
    later version drops them; a run declares only the current version's brands (Spec 015 keeps
    withdrawal per mission). Deleting a watchlist is not offered yet.
