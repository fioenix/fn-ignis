# Feature Specification: Tool-Selection Eval

**Feature Branch**: `028-tool-selection-eval`

**Created**: 2026-11-13

**Status**: Draft

**Input**: BACKLOG AGX-1: "30–40 user intents across three journeys, plus traps ('find market
opportunities', 'show my Threads'). Score first-call accuracy, wrong calls, and calls to a terminal
state. Use the real `list_tools()` with simulated handlers. Cancel if results vary by more than 10
points between repeated runs. Depends on OWN-5."

## Context

Ignis exposes 41 MCP tools. The 11/11/2026 expert panel found that agents are likely to pick the
wrong tool: stale descriptions promise retired behaviour, 136/136 parameters lack a description and
no tool carries annotations. Nobody has measured how often a host agent actually goes wrong. AGX-2
(rewrite stale descriptions), AGX-3 (parameter descriptions and annotations) and AGX-7 (tool
profiles) each name an AGX-1 result as their pass or cancel condition, so this eval is the baseline
they compare against.

The eval measures the catalog a host agent sees, not Ignis's collection or analysis. It never
touches a real source, store, browser session or token.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Baseline how often a host agent picks the right first tool (Priority: P1)

A maintainer runs one command. A real host agent (Claude, headless) receives each user intent in
turn with the live Ignis tool catalog, unchanged names, descriptions, schemas and server
instructions, but every handler is simulated. The command reports, per intent and overall, whether
the agent's first tool call was acceptable.

**Why this priority**: First-call accuracy is the number AGX-2 must improve by 50% on trap
intents; without it no catalog change can be judged.

**Independent Test**: Run the eval once over the full intent set and read a report that lists
first-call accuracy overall, per journey, and for trap intents.

**Acceptance Scenarios**:

1. **Given** the intent set and the current catalog, **When** the maintainer runs the eval,
   **Then** each intent is scored as acceptable or not on its first tool call, and the report
   gives the accuracy overall, per journey and for traps.
2. **Given** an intent whose correct behaviour is to call no tool (for example, asking the user
   for missing scope), **When** the agent answers without a tool call, **Then** that counts as
   acceptable, and calling any tool counts as wrong.
3. **Given** a trap intent such as "find market opportunities", **When** the agent calls a tool
   that the intent lists as a trap (for example `discover_market_opportunities` without a
   confirmed mission), **Then** the call is counted as a wrong first call and named in the report.

---

### User Story 2 - Measure wrong calls and calls to a terminal state (Priority: P2)

For each intent the simulated handlers return scripted, realistic responses, so the agent can keep
going until it reaches the intent's terminal state, stops on its own, or hits a call cap. The
report counts wrong calls and the number of calls taken to reach the terminal state.

**Why this priority**: A catalog can have a good first call and still wander. AGX-4 and AGX-6 need
the multi-step numbers, but the first-call baseline is usable alone.

**Independent Test**: Run the eval on the watchlist journey only and read, per intent, the call
sequence, wrong calls, and whether and when the terminal state was reached.

**Acceptance Scenarios**:

1. **Given** an intent with a defined terminal state, **When** the agent reaches it, **Then** the
   report records the number of tool calls it took.
2. **Given** an agent that never reaches the terminal state, **When** it stops or hits the call
   cap, **Then** the intent is recorded as not reaching it, with the cap or stop reason.
3. **Given** any tool call outside the intent's acceptable set, **When** the run ends, **Then** it
   is counted as a wrong call and named in the report.

---

### User Story 3 - Know whether the eval is stable enough to trust (Priority: P3)

The maintainer runs the eval three times and gets the spread of each headline metric between
runs. If any headline metric varies by more than 10 percentage points, the report says the eval
fails its stability bar, as the backlog's cancel condition requires.

**Why this priority**: A noisy eval would make AGX-2's 50% target meaningless; this decides
whether AGX-1 stays or is cancelled.

**Independent Test**: Run three repeats and read the per-metric spread and a pass/fail stability
line.

**Acceptance Scenarios**:

1. **Given** three completed runs, **When** the report is built, **Then** it shows each headline
   metric's minimum, maximum and spread in percentage points.
2. **Given** a spread above 10 points on any headline metric, **When** the report is built,
   **Then** it marks the eval unstable.

### Edge Cases

- The host agent CLI is missing, signed out or out of quota: the run stops before scoring and says
  so; no partial run is reported as a baseline.
- The agent calls a tool with arguments the schema rejects: the call counts as made (for
  first-call scoring the tool choice is what is scored) and the simulated handler returns the
  validation error the real server would.
- The agent calls a tool the intent did not script: the handler returns a generic, neutral
  response and the call is counted as wrong.
- The live catalog changes (a tool is added, renamed or removed) and an intent names a tool that
  no longer exists: the eval refuses to run until the intent set is updated.
- An intent is in Vietnamese without tone marks: it is kept as written; the eval does not fold or
  correct it.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The intent set MUST hold 40–50 intents spread over three journeys: tactical
  collection (one bounded source question), watchlist follow-up (save, run, period view) and
  Market mission (brief, ingress, qualification, claims, report). At least 16 intents MUST be
  traps, including "find market opportunities" and "show my Threads", so one trap intent moves
  the trap metric by at most about 6 points.
- **FR-002**: Each intent MUST declare its journey, whether it is a trap, the acceptable first
  tools (or "no tool"), tools that count as trap calls, its terminal state and the scripted
  handler responses it needs.
- **FR-003**: Intents MUST be written the way a Vietnamese founder or operator would ask, mostly
  in Vietnamese with correct diacritics, with a few English and a few untoned Vietnamese ones.
- **FR-004**: The host agent MUST see the catalog exactly as the real server publishes it: tool
  names, descriptions, input schemas, server instructions and prompts read from the live
  registration, not copied by hand.
- **FR-005**: No handler call MAY reach a real source, store, browser, session, token or network
  endpoint; every handler is simulated.
- **FR-006**: The host agent MUST run without the maintainer's own MCP servers, plugins, hooks,
  memory or built-in file and shell tools, so only the Ignis catalog is available to it.
- **FR-007**: The eval MUST score first-call accuracy, the share of intents with any trap-tool
  call, wrong calls per intent, and calls to the terminal state, overall, per journey and for
  traps, and cap each intent at a fixed number of tool calls.
- **FR-007a**: A declared set of read-only orientation tools (listing missions or workspaces,
  reading a watchlist, auth status, health, logs, lexicons, runtime config) MUST count as neutral:
  never wrong, skipped when finding the first call that commits to a path, and answered with
  shared default responses. A neutral tool cannot be a trap tool.
- **FR-008**: The eval MUST support repeated runs and report each headline metric's spread, with
  an unstable verdict above 10 percentage points.
- **FR-009**: Each run MUST record the host model, the catalog fingerprint and the intent-set
  version, so two baselines can be compared only when they measure the same thing.
- **FR-010**: The scoring and the intent-set validation MUST be testable without calling any
  model, and those tests MUST run with the normal unit suite.
- **FR-011**: The eval MUST NOT run in CI or on a schedule; a maintainer starts each run.

### Key Entities

- **Neutral tool**: a read-only orientation tool that never counts as wrong.
- **Intent**: one user request with its journey, trap flag, acceptable first tools, trap tools,
  terminal state and scripted responses.
- **Run**: one pass of the host agent over the intent set, with model, catalog fingerprint and
  intent-set version, and one transcript of tool calls per intent.
- **Baseline report**: the scored result of one or more runs: headline metrics, per-intent detail
  and, for repeats, the spread and stability verdict.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: One command produces a baseline report over the whole intent set in under 30 minutes.
- **SC-002**: The report gives first-call accuracy overall, per journey and for traps, the
  trap-call rate, wrong and neutral calls per intent, and the share of intents that reach their
  terminal state with the median calls taken.
- **SC-003**: Three repeated runs give a spread for each headline metric and a stability verdict
  against the 10-point bar.
- **SC-004**: A baseline is recorded for the current catalog on two host models, so AGX-2 can
  test its target of at least a 50% drop in wrong first calls on trap intents.
- **SC-005**: Zero real sources, stores or sessions are touched during a run.

## Assumptions

- The host agent is Claude Code run headless on the maintainer's own subscription (owner,
  13/11/2026); no Anthropic API key is needed.
- A representative mid-tier model is the default host model; another model can be chosen per run
  and is recorded in the report.
- Three repeats is enough to test the 10-point stability bar at this stage.
- The baseline numbers are recorded in this spec's folder; raw transcripts stay in gitignored
  local output.
- Jev is not used for selection; OWN-5's approval stays available if a later scoring step needs a
  semantic judgment.

## Clarifications

### Session 2026-11-13

- Q: Which model plays the host agent that selects tools? → A: Claude Code headless on the
  owner's subscription, measuring real host behaviour including multi-step runs (owner, chat
  13/11/2026).
- Q: The first baseline (13/11/2026, Sonnet, 38 intents, 8 traps) spread 25 points on trap
  first-call accuracy, and 23 of 46 "wrong" calls were harmless orientation reads. Cancel, or fix
  the scoring and rerun? → A: Fix and rerun: neutral orientation reads, a trap-call rate, at least
  16 trap intents, and a second, smaller host model (owner, chat 13/11/2026). The intent range
  moves from 30–40 to 40–50 to hold the extra traps (agent decided; basis: one flip in 8 traps is
  12.5 points, above the 10-point bar by construction).
