# Feature Specification: Host-Scheduled Watchlist Routines

**Feature Branch**: `codex/spec017-routine-setup`

**Created**: 2026-10-21

**Status**: Draft

**Input**: The owner's accepted decision record
[`docs/decisions/2026-10-21-listening-first-product-direction.md`](../../docs/decisions/2026-10-21-listening-first-product-direction.md)
(Accepted 21/10/2026), item 4 of its order: "the routine-setup skill, Claude Desktop first". A user
who wants continuous listening asks their own agent for it, and an Ignis skill sets up a routine in
the host's native scheduler that runs one watchlist on a cadence. Ignis itself keeps no scheduler,
worker or background loop.

## Outcome and audience

A user who already follows a watchlist (Spec 016) by running it by hand wants it to run every day
without remembering to. They ask their agent ("run my matcha watchlist every morning"), confirm
what will run and when, and from then on each day adds one run to the watchlist's history. The
period view (Spec 016) then has the daily coverage it needs to compare weeks and months.

The decision this supports is the owner's: history comes from the user's own agent, so the user
stays in control of when their accounts are used, and Ignis carries no hosting or scheduling cost.
The observable proof is a routine that exists only because the user asked, that runs exactly one
watchlist run per firing, and that the user can see, pause and remove in the host's own interface.

## Context: current state (observed 21/10/2026 on `main` at `55d3eef`)

Read from the code and from the host's documented tool contract, not from production data:

- Ignis has no scheduler, worker or background loop (Constitution I; ADR 2026-09-29, kept by the
  2026-10-21 ADR).
- Spec 016 (on its own branch, not merged) adds watchlists, `start_watchlist_run`, per-channel
  daily request ceilings and the period snapshot. This feature assumes them.
- Ignis already serves packaged guides as MCP prompts and resources (`ignis_track`,
  `fn-ignis://guide/ignis-track`) with an identical `.agents/skills/` copy.
- Claude Desktop local scheduled tasks: a task is a self-contained prompt stored as
  `{taskId}/SKILL.md` under the user's `~/.claude/scheduled-tasks/`; it fires on a 5-field cron in
  local time with a small dispatch delay, runs as a fresh session with no memory of the
  conversation that created it, runs only while the app is open (a task due while the app is closed
  runs on next launch), and may be saved with the creating session's permission mode. It reaches
  local MCP servers.
- Codex and Antigravity scheduled tasks have no documented access to local MCP servers; cloud
  routines cannot reach a local server or the user's browser sessions (ADR).

## Clarifications

### Session 2026-10-21

Decided by the owner in the accepted decision record:

- Q: Who schedules? → A: The host's native scheduler, set up by an Ignis skill, only on the user's
  explicit request. An agent never sets up a routine the user did not ask for.
- Q: What does one firing do? → A: One Attention mission bound to one watchlist version (a watchlist
  run).
- Q: Missed days? → A: Ignis does not backfill on its own; a re-run the user or the harness starts
  collects what platforms still return, and a missed day otherwise stays a visible gap.
- Q: Which host first? → A: Claude Desktop local scheduled tasks; Codex after a probe; cloud
  routines later and only for API channels with a remote database.

Decided by the agent under the owner's delegation of 21/10/2026, conservative defaults, owner to
confirm (listed again under "Owner review"):

- Q: Does Ignis need a new tool to record routines? → A: No. The routine lives only in the host;
  Ignis sees ordinary watchlist runs. No MCP tool, signature or table changes.
- Q: How many routines per watchlist? → A: One. Setup refuses a second and offers to change the
  existing one.
- Q: What cadence is offered? → A: Daily at a time the user chooses; the guide proposes 07:00 local
  time. Faster than daily is refused, because coverage is judged per day and the daily request
  ceilings are per day.
- Q: What does a firing do after collection? → A: Nothing by default: it stops when the mission
  reaches a terminal state. Rendering a period view on a firing happens only if the user asked for
  it at setup, and the artifact stays local.
- Q: Which permission mode does the routine use? → A: The guide tells the user that the host may save
  the routine with the current session's permission mode and recommends creating it from a session
  in the host's default mode, so the first firing asks for each tool approval.
- Q: What if the host has no scheduling capability? → A: The guide says so and stops. It never falls
  back to OS schedulers (cron, launchd, Task Scheduler) or to a loop inside Ignis.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Set up a daily routine on request (Priority: P1)

The user asks their Claude Desktop agent to run their matcha watchlist every morning. The agent
reads the Ignis routine guide, shows what will run (watchlist name and version, channels, daily
time, what happens after collection, how to pause it) and creates the routine only after the user
confirms.

**Why this priority**: Without it, history depends on the user remembering to run the watchlist.

**Independent Test**: In Claude Desktop with a fixture watchlist, follow the guide: the routine is
created once, appears in the host's task list, and its stored prompt names exactly that watchlist
and contains the safeguards.

**Acceptance Scenarios**:

1. **Given** a user request naming a watchlist and a daily time, **When** the agent follows the
   guide, **Then** it confirms the details with the user before creating anything, and creates
   exactly one host routine.
2. **Given** no explicit user request (for example, the user only asked for a period view), **When**
   the agent follows any Ignis guide, **Then** no routine is created or proposed as already done.
3. **Given** an existing routine for the watchlist, **When** the user asks again, **Then** the agent
   offers to change the existing routine instead of creating a second one.
4. **Given** a request for a cadence faster than daily, **When** the agent follows the guide,
   **Then** it refuses that cadence and explains why.

### User Story 2 - Each firing adds one bounded run (Priority: P1)

When the routine fires, a fresh agent session starts one watchlist run, collects within each
channel's daily request ceiling, and stops at the mission's terminal state.

**Why this priority**: A firing that does more than one bounded run would break Constitution I and
the user's control over their accounts.

**Independent Test**: Trigger the routine once with the host's "run now" on a fixture watchlist:
exactly one mission bound to the watchlist's current version is created and reaches a terminal
state; a channel at its ceiling reports `daily_ceiling` and the others continue.

**Acceptance Scenarios**:

1. **Given** a firing, **When** it runs, **Then** it creates one watchlist run on the current version
   and nothing else (no new watchlist, no version change, no extra mission).
2. **Given** a channel whose daily ceiling is already reached, **When** the firing collects, **Then**
   that channel stops with its status and the run continues with the others.
3. **Given** yesterday was missed (the host was closed), **When** today's firing runs, **Then** it
   collects today's run only and does not try to backfill yesterday.
4. **Given** the watchlist was deleted or Ignis is unreachable, **When** the firing runs, **Then** it
   stops and reports the reason without creating anything.

### User Story 3 - See, change and stop the routine (Priority: P2)

The user asks what routines exist, changes the time, pauses it or removes it.

**Why this priority**: The user stays in control only if stopping is as easy as starting.

**Independent Test**: Following the guide, pause the routine (host state disabled), resume it,
change its time, and remove it after the user's confirmation.

**Acceptance Scenarios**:

1. **Given** a routine, **When** the user asks to pause it, **Then** the agent disables it in the
   host without deleting it.
2. **Given** a routine, **When** the user asks to remove it, **Then** the agent confirms first and
   then deletes only that routine; watchlist history is untouched.

### User Story 4 - Hosts without a verified scheduler (Priority: P3)

In Codex, Antigravity or a cloud routine, the guide says the host is not supported yet and stops.

**Independent Test**: Follow the guide where no supported scheduling tool is present: no routine,
no OS scheduler entry, no Ignis-side loop; the agent tells the user to run the watchlist by hand.

### Edge Cases

- The host fires a routine late (dispatch delay, app opened late): the run is placed by its own
  observations' dates (Spec 016), so lateness changes nothing but coverage.
- Two firings land on one day (manual "run now" plus the scheduled one): both are ordinary runs;
  Spec 016 deduplicates by source, and the ceilings bound the requests.
- The watchlist gets a new version: the next firing runs the current version; the routine prompt
  names the watchlist, not a version.
- The routine was saved in an auto or bypass permission mode: the guide warns before creation.
- The user's machine sleeps for a week: the days stay gaps; nothing is backfilled.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Ignis MUST ship a packaged routine guide, served as an MCP prompt and resource and as
  an identical `.agents/skills/` skill, that tells the host agent how to set up, list, change, pause
  and remove a watchlist routine.
- **FR-002**: The guide MUST allow routine creation only after an explicit user request naming the
  watchlist and cadence, and only after the agent shows the details and the user confirms.
- **FR-003**: The guide MUST use only the host's native scheduler and MUST NOT fall back to OS
  schedulers or to any loop inside Ignis.
- **FR-004**: Each routine MUST run one watchlist; at most one routine per watchlist; cadence at most
  once per day.
- **FR-005**: The routine prompt MUST be self-contained and MUST, on each firing: start exactly one
  watchlist run on the current version, collect within the daily ceilings, stop at the mission's
  terminal state, and report the outcome. It MUST NOT backfill missed days, broaden the watchlist,
  create or revise watchlists, or publish anything.
- **FR-006**: Rendering a period view on a firing MUST happen only if the user asked for it at setup;
  the artifact MUST stay local.
- **FR-007**: The guide MUST warn that the host may save the routine with the current permission mode
  and recommend the host's default mode.
- **FR-008**: Removing a routine MUST require the user's confirmation and MUST leave watchlist history
  untouched.
- **FR-009**: Claude Desktop local scheduled tasks MUST be the supported host; any other host MUST be
  reported as unsupported until a recorded probe shows it reaches the local Ignis server.
- **FR-010**: Serving the guide MUST start no read, collection or write.
- **FR-011**: Ignis MUST NOT gain a scheduler, worker, background loop or routine table; no MCP tool or
  signature changes.
- **FR-012**: The constitution amendment drafted in Spec 016 (host-native routines only on explicit
  user request) MUST be ratified by the owner before this feature merges.

### Key Entities

- **Routine**: a host-owned scheduled task whose prompt runs one watchlist; Ignis does not store it.
- **Firing**: one execution of the routine; produces at most one watchlist run.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: In a Claude Desktop acceptance run, following the guide from a single explicit request
  creates exactly one routine, and following it without a request creates none.
- **SC-002**: Each manual "run now" of the routine produces exactly one watchlist run bound to the
  current version, and zero other writes.
- **SC-003**: The stored routine prompt contains the watchlist identifier and every FR-005
  prohibition, and no credential or author identity.
- **SC-004**: The repository still contains no scheduler, worker or background loop (existing
  convention tests stay green).
- **SC-005**: Over 14 consecutive days of a real routine on one golden-set watchlist, the share of
  days with a completed run is recorded; no target is set by this feature.

## Assumptions

- Spec 016 is merged first (watchlists, `start_watchlist_run`, ceilings, period snapshot).
- The owner ratifies the Spec 016 constitution amendment before this feature merges.
- The host's scheduled-task behaviour is as documented on 21/10/2026; if a firing missed while the
  app was closed runs once or several times on launch is not documented, and the guide does not
  depend on it.
- Real social sessions used by a routine are the user's own, configured outside this feature.

## Owner review

Agent decisions under the owner's delegation of 21/10/2026, to confirm or change:

1. No Ignis-side record of routines; no new tool or table (FR-011).
2. One routine per watchlist; at most daily; proposed default time 07:00 local (FR-004).
3. No period view on a firing unless asked at setup (FR-006).
4. Permission-mode warning and default-mode recommendation (FR-007).
5. Merge waits for the constitution amendment (FR-012).
