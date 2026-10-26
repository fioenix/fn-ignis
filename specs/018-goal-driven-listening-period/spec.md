# Feature Specification: Goal-Driven Listening Period

**Feature Branch**: `claude/goal-driven-period`

**Created**: 2026-10-26

**Status**: Draft

**Input**: User description: "Watchlist lưu mục tiêu và kỳ so sánh, routine suy ra nhịp chạy từ kỳ so sánh và khoảng nhìn lại, phủ dữ liệu tính theo khoảng nhìn lại." (The watchlist keeps the user's goal and comparison period; the routine derives its cadence from the comparison period; coverage follows from it. The look-back framing was replaced in clarification by snapshots.)

## Outcome and audience

The person following a watchlist (Spec 016) decides how often they need an answer: "did demand
for sun-protection jackets rise this week against last week" is a weekly question; a seasonal
question is monthly. Today Ignis decides for them: Spec 017 fixes the routine at once a day, and
Spec 016 counts a day as covered only when a run completed that day, so the collection unit is
forced onto the analysis unit.

Each collection is a snapshot of what the social channels show for the watchlist's keywords at
that moment. What a snapshot shows today and when a post was created are two different facts, and
the view keeps both.

The decision this supports is the owner's: what the user wants to compare comes first, and the
cadence and the coverage rule follow from it. The observable proof is a watchlist whose stated
period drives its period view and its routine, and a period view that reports what the snapshots
of each period showed alongside what was created in it, each labelled.

## Context: current state (observed 26/10/2026 on `main` at `ba2e064`)

- A watchlist version holds topics, categories, keywords, brands and a discovery share
  (Spec 016 FR-001). It holds no goal and no comparison period. The period view takes the period
  kind (day, week, month) from each caller.
- Spec 016 FR-004 and Constitution Principle III place each observation in a listening period by
  its publication time when a plausible one exists. Spec 016 FR-005: a day with no completed
  collection for a topic and channel is "no data"; a channel is compared only when neither period
  misses more than 20 percent of its days.
- Spec 017 FR-004: one routine per watchlist, at most daily; the guide proposes 07:00 and asks the
  user only for a time.
- Observed on G3 (`d78e5ed9`): a preview of the 26/10 against 25/10 day view, made by moving the
  clock on a copy of the store, was comparable but held 0 to 6 relevant items per channel cell,
  because items are placed by publication date and most posts a run finds were published on
  earlier days (51 relevant sources, published from April to 26/10). Under the current coverage
  rule the first comparable pair of weeks for G3 is 2-8/11 against 26/10-1/11, readable on 9/11.

## Clarifications

### Session 2026-10-26

- Q: For channels whose search attests no look-back window, which rule decides that a publication
  day is covered? → A: The question's premise was replaced. A collection is not a look-back window
  but a snapshot of what the channels show now. Two listening axes coexist, because "seen today"
  and "created on day X" mean different things: a seen axis that places each observation at its
  snapshot time, and a created axis that places it by publication time as Spec 016 does today.
  Neither substitutes for the other, and every figure states its axis.
- Q: How many successful snapshots must a period hold before a channel is compared on the seen
  axis? → A: As many as the user's own research cadence calls for. The research cadence follows
  the user's goal and specification, and the watchlist records it; Ignis sets no fixed minimum per
  period kind. A period is comparable when it misses no more than 20 percent of the snapshots that
  cadence calls for (Spec 016's tolerance). A post's creation date is a separate matter: once data
  is collected, a known creation date enriches the analysis, but it does not decide coverage or
  cadence.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - State what to compare when following a watchlist (Priority: P1)

When a user creates or revises a watchlist, their agent asks what decision the listening supports,
over which period they want to compare (day, week or month) and how often they want a snapshot
taken in each period. The watchlist keeps the goal sentence, the comparison period and that
research cadence. The period view then compares that period by default.

**Why this priority**: every other change derives from the stated period; without it, cadence
and coverage have nothing to follow.

**Independent Test**: create a watchlist with goal "Track weekly demand for sun-protection jackets"
and period week, then read its period view without naming a period: it compares the last two
complete weeks.

**Acceptance Scenarios**:

1. **Given** a user who states a goal and the period week, **When** the watchlist is saved, **Then**
   reading it returns that goal and period, and the period view without a period kind compares
   weeks.
2. **Given** a saved watchlist with period week, **When** a caller asks for a month view, **Then**
   the month view is returned as before; the stated period is a default, not a restriction.
3. **Given** a user who changes the period from week to month, **When** the change is saved,
   **Then** earlier runs and evidence are unchanged and the next period view defaults to month.

---

### User Story 2 - Compare what the snapshots showed (Priority: P1)

The period view reports, per topic and channel, what the snapshots taken in each period showed:
how many relevant items they showed, the interactions visible on them, how many items appeared
that no earlier snapshot of the watchlist had shown, and the rising terms. Each figure is an
average per snapshot, so a period with more snapshots does not read higher for that reason.

**Why this priority**: it answers the user's question ("what is the market showing now, against
before") with every collected item, not only the few published inside the period.

**Independent Test**: on G3's stored runs, a week view on the seen axis counts every relevant item
of each snapshot in that week, including items published months earlier, and divides by the
number of snapshots.

**Acceptance Scenarios**:

1. **Given** two snapshots in a week that showed 40 and 30 relevant YouTube items, **When** the
   week is read on the seen axis, **Then** YouTube shows 35 relevant items per snapshot.
2. **Given** an item shown by a snapshot on 25/10 and again on 26/10, **When** the week of
   26/10 is read, **Then** it counts in each snapshot that showed it, and counts as newly seen only
   in the first.
3. **Given** a period whose snapshots for a channel are too few (see FR-006), **When** it is read,
   **Then** that channel shows "not comparable" with the number of snapshots it had, as today with
   missing days.

---

### User Story 3 - Creation dates enrich the analysis (Priority: P2)

When collected items carry a known creation date, the analysis uses it: the seen axis also reports
how many of the items a period's snapshots showed were created in that period, and the existing
created view (items placed by publication date, Spec 016) stays available unchanged, labelled as
created in the period.

**Why this priority**: what was created in a period measures new content supply, which a snapshot
does not; Spec 016's figures must not disappear or change meaning. It is analysis on collected
data, not a rule for when or how often to collect.

**Independent Test**: the created-axis figures of an existing week view are identical before and
after this feature.

**Acceptance Scenarios**:

1. **Given** a stored week, **When** it is read before and after this feature, **Then** its
   created-axis indicators and missing days are identical.
2. **Given** a period view, **When** it is rendered, **Then** every figure states whether it is
   seen or created.

---

### User Story 4 - The routine follows the user's research cadence (Priority: P2)

When a user asks their agent for a routine (Spec 017), the guide schedules the research cadence the
watchlist records. When the user has not stated one, the agent asks for it, and may suggest one
from the goal and period, before anything is scheduled. The guide shows the requests that cadence
spends per period and waits for the user's confirmation.

**Why this priority**: the routine is where cost is spent; the user, not Ignis, decides how often
their question needs a snapshot.

**Independent Test**: for a watchlist recording period week and three snapshots a week, the routine
guide schedules three firings a week on distinct days, states the requests they spend, and creates
the routine only after the user confirms.

**Acceptance Scenarios**:

1. **Given** a watchlist recording a research cadence, **When** the user asks for a routine,
   **Then** the agent shows that cadence and the requests it spends per period, and waits for
   confirmation.
2. **Given** a watchlist with no recorded cadence, **When** the user asks for a routine, **Then**
   the agent asks for the cadence before scheduling; any suggestion it makes is labelled as one.
3. **Given** a user who asks for a cadence faster than daily, **When** the guide is followed,
   **Then** it is refused as today.
4. **Given** a user who changes the cadence, **When** the change is saved, **Then** the watchlist
   records it and later periods are judged against it; earlier periods keep the cadence that was
   recorded for them.

---

### Edge Cases

- A watchlist saved before this feature has no goal, period or cadence. It keeps working; the
  period view still needs a period kind from the caller, the seen axis cannot judge it comparable
  without a cadence and says so, and the routine guide asks for all three before scheduling.
- A snapshot whose collection was partial for some keywords (Spec 016 2026-10-26 partial note)
  counts as a snapshot only for the keywords it queried.
- A snapshot that a failed or ceiling-limited collection produced is not a snapshot for that
  channel.
- A snapshot with an unjudged observation leaves its channel unjudged for the period, as the
  judged-day rule does today.
- Two runs within one day are two snapshots on the seen axis; the created view keeps one day per
  run, as today.
- A cadence slower than daily can make a channel comparable on the seen axis while the created
  view still shows missing days under Spec 016's rule; the view states each separately.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: A watchlist MUST be able to hold a goal (one sentence, the decision the listening
  supports), one comparison period (day, week or month) and a research cadence (the snapshots the
  user wants in each period), all stated by the user; Ignis MUST NOT infer any of them.
- **FR-002**: The period view MUST default to the watchlist's comparison period when the caller
  names none; a caller MAY still request any period kind.
- **FR-003**: Changing a watchlist's goal, comparison period or cadence MUST NOT change collected
  evidence, runs or versions' collection scope; each period is judged against the cadence recorded
  for it.
- **FR-004**: The period view MUST report per topic and channel a seen axis that places each
  observation at the time of the snapshot that collected it, and MUST keep the created view that
  places it by publication time as Spec 016 FR-004 does. Every figure MUST state which of the two
  it belongs to.
- **FR-005**: On the seen axis, each indicator MUST be an average per snapshot in the period:
  relevant items shown, interactions visible on them at snapshot time, items not shown by any
  earlier snapshot of the watchlist, and rising terms.
- **FR-006**: On the seen axis, a channel MUST be compared only when neither period misses more than
  20 percent of the snapshots the recorded cadence calls for, for that topic and channel; otherwise
  it MUST show "not comparable" with the snapshots it had and the snapshots the cadence called for.
- **FR-007**: Creation dates MUST serve the analysis only: the seen axis MUST report how many of the
  items shown were created in the period, and the existing created view MUST keep Spec 016's
  placement, coverage (FR-005), counting window (FR-008) and judged-day rules unchanged. Creation
  dates MUST NOT decide cadence or seen-axis coverage.
- **FR-008**: The routine guide MUST schedule the research cadence the watchlist records, ask the
  user for one when none is recorded (any suggestion labelled as such), show the requests it spends
  per period, and create the routine only after the user confirms. Cadences faster than daily MUST
  still be refused.
- **FR-009**: Relevance on both axes MUST come from evidence-qualification outcomes; an unassessed
  observation MUST NOT count (Spec 016 FR-010).
- **FR-010**: Watchlists saved before this feature MUST keep working without a goal or period.
- **FR-011**: Behaviour MUST be identical on SQLite and PostgreSQL.
- **FR-012**: Ignis MUST still keep no scheduler: the cadence is a proposal the host agent shows;
  the host's native scheduler runs it (Constitution I, Spec 017 FR-011).
- **FR-013**: The constitution MUST be amended (Proposed for owner ratification) so that a
  listening period offers a seen axis placed by the exact ingestion clock alongside the created
  view placed by publication time, each labelled, and so that a watchlist may record the user's
  research cadence without Ignis gaining a scheduler.

### Key Entities

- **Listening goal**: the user's one-sentence statement of the decision a watchlist supports.
- **Comparison period**: the period kind (day, week, month) the user wants to compare; default for
  the period view.
- **Research cadence**: the snapshots per period the user wants, recorded on the watchlist with the
  date it took effect; what the seen axis is judged against and what the routine schedules.
- **Snapshot**: one completed collection of one channel for a watchlist run, at its collection
  time, with the items it showed and their counters at that time.
- **Seen axis**: listening figures placed by snapshot time, averaged per snapshot.
- **Created view**: listening figures placed by publication time (Spec 016), an analysis aid that
  does not govern collection.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: On G3's stored runs, a seen-axis day or week view counts every relevant item of each
  snapshot in the period (51 relevant sources over 25/10 and 26/10, not the 0 to 6 per cell the
  created view shows).
- **SC-002**: A weekly watchlist whose user records three snapshots a week reaches a comparable week
  on the seen axis with those three snapshots, without needing a run on 6 of 7 days.
- **SC-003**: 100 percent of the figures in a period view state their axis.
- **SC-004**: Created-axis figures of every stored period are identical before and after this
  feature.
- **SC-005**: A user setting up a routine sees the proposed cadence, its reason and its request
  cost before confirming, in one exchange.
- **SC-006**: No watchlist saved before this feature fails to load, run or render.

## Assumptions

- The goal is stored as text for the user and the agent; Ignis does not interpret it, discover
  topics from it or change collection because of it (Constitution I).
- The comparison period and the research cadence are watchlist properties, not part of a version:
  they change how results are read and how often to collect, not what a run collects.
- Recording the cadence on the watchlist is not a scheduler: Ignis stores what the user stated and
  judges coverage against it; the host's native scheduler runs the routine (Constitution I).
- A snapshot's interactions are the counters the channel showed at collection time; they are
  labelled as measured on the collected sample, as Spec 016 FR-007 labels them.
- Daily request ceilings, partial-coverage notes and judged-day rules from Spec 016 apply
  unchanged.
