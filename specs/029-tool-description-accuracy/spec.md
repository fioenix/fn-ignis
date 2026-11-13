# Feature Specification: Tool Description Accuracy

**Feature Branch**: `029-tool-description-accuracy`

**Created**: 2026-11-14

**Status**: Draft

**Input**: BACKLOG AGX-2: "Rewrite the stale descriptions: `discover_market_opportunities`,
`get_mission_analysis`, `execute_mission_ingress`, `get_current_session_mission`. Each description
states its preconditions, refusal cases and the tool to call next. Do it after the AGX-1 baseline.
Pass: wrong first calls on trap intents drop by at least 50%."

## Context

The Spec 028 baseline (13/11/2026, 46 intents, 16 traps, 3 runs per model) found that Sonnet and
Haiku both follow the stale descriptions. Asked for an Opportunity Index, white spaces or a
recommendation from an Attention mission, they call `get_mission_analysis` ("Scorecard, 10 White
Spaces, ... Action Plan") and `discover_market_opportunities` ("Identify high-demand, low-supply
market white spaces"). Neither tool returns those outputs for a mission with a surface: a MARKET
mission gets only its Claim Ledger or a Gap Report, and an ATTENTION mission gets no
opportunities. Two other descriptions misstate behaviour: `execute_mission_ingress` claims an
"idempotent replace mode" but refuses a finished mission as TERMINAL, and
`get_current_session_mission` claims a session or chat-thread lookup but matches only a mission id
or shortcode. The baseline also showed `verify_connectors_health` called when a read-only check
would do; its description does not say that it probes live sources and writes a sentinel row.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - A host agent stops choosing tools for outputs they do not give (Priority: P1)

A founder asks their agent for an Opportunity Index, white spaces or a product recommendation. The
agent reads the catalog and sees that these outputs exist only as permitted Claim Ledger claims, so
it reads the claims or explains the gap instead of calling an analysis tool that withholds them.

**Why this priority**: These are the trap calls both models made in nearly every baseline run.

**Independent Test**: Rerun the Spec 028 eval on both models and compare wrong first calls on trap
intents with the baseline.

**Acceptance Scenarios**:

1. **Given** the rewritten catalog, **When** the eval runs 3 times on Sonnet and 3 times on Haiku,
   **Then** pooled wrong first calls on trap intents fall by at least 50% on each model (Sonnet
   12/48 → at most 6/48; Haiku 11/48 → at most 5/48).
2. **Given** the same runs, **When** non-trap intents are scored, **Then** first-call accuracy on
   them does not fall by more than 5 points pooled on either model.

---

### User Story 2 - Descriptions match what each tool does (Priority: P2)

Every rewritten description states, as the code behaves: what the tool reads or writes, its
preconditions, its refusal statuses and what to call next.

**Why this priority**: A description that promises retired behaviour misleads every host, not only
the two measured models.

**Independent Test**: Read each description against its handler; every claim has a code path.

**Acceptance Scenarios**:

1. **Given** each of the five tools, **When** its description is compared with its handler,
   **Then** no description promises an output, lookup or mode the handler does not provide.

### Edge Cases

- A legacy mission with no surface still returns indexed topics from
  `discover_market_opportunities` and `get_mission_analysis`; the description says so without
  inviting it.
- Tool names, parameters and schemas do not change; only description text changes.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The descriptions of `discover_market_opportunities`, `get_mission_analysis`,
  `execute_mission_ingress`, `get_current_session_mission` and `verify_connectors_health` MUST state
  what the tool reads, writes or collects, its preconditions, its refusal statuses and the tool to
  call next.
- **FR-002**: No description MAY promise an Opportunity Index, white spaces, scorecard,
  recommendations or action plan outside what the Claim Ledger permits.
- **FR-003**: Tool names, parameters and input schemas MUST stay unchanged.
- **FR-004**: Every tool catalog derived from the server (Hermes manifests) MUST carry the new
  descriptions.
- **FR-005**: The AGX-2 pass criterion is measured with the Spec 028 eval, its intent set
  unchanged, on the same two models and repeat count as the baseline.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Pooled wrong first calls on trap intents fall by at least 50% on both models.
- **SC-002**: Pooled first-call accuracy on non-trap intents falls by no more than 5 points on
  either model.
- **SC-003**: All five descriptions survive a line-by-line check against their handlers.

## Assumptions

- The pooled count over three runs is the comparison, not a single run, because Sonnet's per-run
  trap metric spread 25 points in the baseline.
- Description text is not a signature change; OWN-4 asks only about parameter descriptions and
  annotations, and AGX-2 does not depend on it in the backlog.

## Clarifications

### Session 2026-11-14

- Q: Include `verify_connectors_health`, which AGX-2 does not name? → A: Yes (agent decided; basis:
  the Spec 028 baseline shows it called on T06, T14, T10 and W13, and its description omits that it
  probes live sources and writes a sentinel row).
- Q: Compare per run or pooled? → A: Pooled over three runs per model (agent decided; basis: the
  baseline's trap first-call spread on Sonnet was 25 points per run).
