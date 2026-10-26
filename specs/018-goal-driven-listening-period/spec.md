# Feature Specification: Goal-Driven Listening Period

**Feature Branch**: `claude/goal-driven-period`

**Created**: 2026-10-26

**Status**: Draft

**Input**: User description: "Watchlist lưu mục tiêu và kỳ so sánh, routine suy ra nhịp chạy từ kỳ so sánh và khoảng nhìn lại, phủ dữ liệu tính theo khoảng nhìn lại." (The watchlist keeps the user's goal and comparison period; the routine derives its cadence from the comparison period and each source's look-back; coverage is judged by look-back.)

## Outcome and audience

The person following a watchlist (Spec 016) decides how often they need an answer: "did demand
for sun-protection jackets rise this week against last week" is a weekly question; a seasonal
question is monthly. Today Ignis decides for them: Spec 017 fixes the routine at once a day, and
Spec 016 counts a day as covered only when a run completed that day, so the collection unit is
forced onto the analysis unit.

The decision this supports is the owner's: what the user wants to compare comes first, and the
cadence and the coverage rule follow from it. The observable proof is a watchlist whose stated
period is used by its period view and its routine, and whose first comparable pair of periods
arrives as soon as the collected data can support it, not when a daily run calendar happens to
fill up.

## Context: current state (observed 26/10/2026 on `main` at `ba2e064`)

- A watchlist version holds topics, categories, keywords, brands and a discovery share
  (Spec 016 FR-001). It holds no goal and no comparison period. The period view takes the period
  kind (day, week, month) from each caller.
- Spec 016 FR-005: a day with no completed collection for a topic and channel is "no data"; a
  channel is compared only when neither period misses more than 20 percent of its days.
- Spec 017 FR-004: one routine per watchlist, at most daily; the guide proposes 07:00 and asks the
  user only for a time.
- Each collection searches back over a window. On the caller store, only YouTube attests its
  window (`7d`, one run `30d`); Threads, Reels and the TikTok grid attest none.
- Observed on G3 (`d78e5ed9`): a preview of the 26/10 against 25/10 day view, made by moving the
  clock on a copy of the store, was comparable but held 0 to 6 relevant items per channel cell,
  because items are placed by publication date and most posts a daily run finds were published on
  earlier days. Under the current coverage rule the first comparable pair of weeks for G3 is
  2-8/11 against 26/10-1/11, readable on 9/11, because only 23/10 and 25/10 had runs in 19-25/10.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - State what to compare when following a watchlist (Priority: P1)

When a user creates or revises a watchlist, their agent asks what decision the listening supports
and over which period they want to compare (day, week or month). The watchlist keeps the goal
sentence and the comparison period. The period view then compares that period by default.

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

### User Story 2 - A routine cadence proposed from the period (Priority: P1)

When a user asks their agent for a routine (Spec 017), the guide proposes a cadence derived from
the watchlist's period and the look-back of its channels, explains why, and lets the user confirm
or choose another cadence no faster than daily.

**Why this priority**: the routine is where cost is spent; a weekly question answered by daily
runs spends daily request ceilings and personal-account sessions without a better answer.

**Independent Test**: for a watchlist with period week whose channels search back 7 days, the
routine guide proposes a cadence slower than daily that still observes every publication day of
the week at least twice, and creates the routine only after the user confirms it.

**Acceptance Scenarios**:

1. **Given** a watchlist with period week, **When** the user asks for a routine, **Then** the agent
   shows the proposed cadence, the reason (period and look-back) and the requests it spends per
   week, and waits for confirmation.
2. **Given** a watchlist with period day, **When** the user asks for a routine, **Then** the
   proposed cadence is daily.
3. **Given** a user who asks for a cadence faster than daily, **When** the guide is followed,
   **Then** it is refused as today.
4. **Given** a user who chooses a cadence different from the proposal, **When** it is no faster
   than daily, **Then** the routine uses it and the guide states which periods it can cover.

---

### User Story 3 - Coverage judged by what the collections searched (Priority: P1)

A publication day counts as covered for a topic and channel when a completed collection of that
channel searched a window that reached back to that day, not only when a run completed on that
day. The period view states which basis each channel's coverage used.

**Why this priority**: it is what lets a week with runs on two or three days be compared, and it
moves G3's first comparable weeks from 9/11 to 2/11.

**Independent Test**: on stored runs that completed on 23/10, 25/10 and 26/10 with an attested
7-day window, the week 19-25/10 reads as covered for YouTube; a channel with no attested window
keeps its current per-run-day coverage.

**Acceptance Scenarios**:

1. **Given** YouTube runs that completed on 23/10 and 26/10 with an attested 7-day window, **When**
   the week 19-25/10 is read, **Then** YouTube shows no missing days for that week.
2. **Given** a channel whose collections attest no window, **When** a period is read, **Then** its
   coverage follows the current rule (the day a collection completed) and the view says so.
3. **Given** a day that only a failed or ceiling-limited collection reached, **When** coverage is
   judged, **Then** that day stays missing, as today.
4. **Given** a covered day whose collections found nothing relevant, **When** the period is read,
   **Then** the channel shows a measured zero, not "no data".

---

### Edge Cases

- A watchlist saved before this feature has no goal or period. It keeps working; the period view
  still needs a period kind from the caller, and the routine guide asks for the period before
  proposing a cadence.
- An attested window longer than the comparison period (YouTube `30d` for a week) covers every day
  it reaches, no more.
- A run whose collection completed but whose search was cut short for some keywords (a partial
  note, Spec 016 2026-10-26) covers a day only for the keywords it queried, as today.
- A day covered only by look-back but judged by an unjudged run stays in `unjudged_days`
  (Spec 016 2026-10-26).
- The engagement counter (Spec 016 FR-008) still counts the latest observation within 7 days of
  publication; a slower cadence can leave an item observed once, early in that window.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: A watchlist MUST be able to hold a goal (one sentence, the decision the listening
  supports) and one comparison period (day, week or month), stated by the user; Ignis MUST NOT
  infer either.
- **FR-002**: The period view MUST default to the watchlist's comparison period when the caller
  names none; a caller MAY still request any period kind.
- **FR-003**: Changing a watchlist's goal or comparison period MUST NOT change collected evidence,
  runs or versions' collection scope.
- **FR-004**: The routine guide MUST propose a cadence derived from the comparison period and the
  look-back of the watchlist's channels, show the reason and the requests it spends per period, and
  create the routine only after the user confirms. Cadences faster than daily MUST still be
  refused.
- **FR-005**: For a channel whose completed collection attests a look-back window, a publication
  day MUST count as covered for a topic when a completed collection that queried that topic's
  keywords searched a window reaching back to that day.
- **FR-006**: For a channel whose collection attests no window, coverage MUST follow the current
  rule: the day the collection completed.
- **FR-007**: Each channel cell of the period view MUST state its coverage basis (look-back window
  or run day).
- **FR-008**: The 20 percent missing-day threshold (Spec 016 FR-005), the judged-day rule and the
  daily request ceilings MUST be unchanged.
- **FR-009**: Watchlists saved before this feature MUST keep working without a goal or period.
- **FR-010**: Behaviour MUST be identical on SQLite and PostgreSQL.
- **FR-011**: Ignis MUST still keep no scheduler: the cadence is a proposal the host agent shows;
  the host's native scheduler runs it (Constitution I, Spec 017 FR-011).

### Key Entities

- **Listening goal**: the user's one-sentence statement of the decision a watchlist supports.
- **Comparison period**: the period kind (day, week, month) the user wants to compare; default for
  the period view and basis of the proposed cadence.
- **Look-back window**: the span a channel's completed collection attests it searched, per run.
- **Coverage basis**: per channel cell, whether coverage came from look-back windows or run days.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: For G3 with period week, the first comparable pair of weeks for YouTube is
  26/10-1/11 against 19-25/10, readable on 2/11, instead of 9/11.
- **SC-002**: A weekly watchlist whose channels search back 7 days reaches a comparable week with
  at most 3 runs in that week (not 6 or 7).
- **SC-003**: Every period view states a coverage basis for 100 percent of its channel cells.
- **SC-004**: A user setting up a routine sees the proposed cadence, its reason and its request
  cost before confirming, in one exchange.
- **SC-005**: No watchlist saved before this feature fails to load, run or render.

## Assumptions

- The goal is stored as text for the user and the agent; Ignis does not interpret it, discover
  topics from it or change collection because of it (Constitution I).
- The comparison period is a watchlist property, not part of a version: it changes how results are
  read and how often to collect, not what a run collects.
- Only YouTube attests a look-back window today; making other channels attest one is outside this
  feature.
- The proposed cadence uses the shortest attested look-back among the watchlist's channels; the
  exact derivation rule is settled in clarification.
- Daily request ceilings, partial-coverage notes and judged-day rules from Spec 016 apply
  unchanged.
