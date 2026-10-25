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
- Claude Code Desktop (the Code tab) local scheduled tasks, as their tool contract read in this
  repository's Claude Code Desktop session on 21/10/2026: a task is a self-contained prompt stored as
  `{taskId}/SKILL.md` under the user's `~/.claude/scheduled-tasks/`; it fires on a 5-field cron in
  local time with a small dispatch delay, runs as a fresh session with no memory of the
  conversation that created it, runs only while the app is open (a task due while the app is closed
  runs on next launch), may be saved with the creating session's permission mode, and starts in a
  working folder of its own. It reaches
  local MCP servers.
- Not verified: whether scheduled tasks created in the Claude app (Cowork) or other Claude surfaces
  still run locally for new tasks. A PR review on 21/10/2026 cited a vendor note that new tasks there
  run in the cloud; this spec does not rely on any surface other than the one above until a probe
  (T001) confirms it on current versions.
- Ignis mission tools resolve their authorized root from the MCP server's startup folder or an
  operator's `IGNIS_CALLER_ROOT`, and refuse a home or root folder with `ROOT_REQUIRED`
  (`docs/caller-storage.md`); only a Claude Code session opened in a repository folder is verified.
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
- Q: Which host first? → A: Claude Code Desktop local scheduled tasks; Codex after a probe; cloud
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
- Q: Which permission mode does the routine use? → A: Never an auto or bypass mode. Setup ends with an
  attended "Run now" in which the user approves exactly the two Ignis tools a firing needs
  (`start_watchlist_run`, `execute_mission_ingress`) for that routine; later firings reuse those
  approvals and anything else still asks. Without those approvals the routine is attended, and the
  guide says so (revised after PR review, 21/10/2026).
- Q: Where does a firing start? → A: In the research workspace's repository folder, set as the task's
  working folder at setup, or under an operator-set `IGNIS_CALLER_ROOT`; setup refuses a home or root
  folder, and acceptance runs a fresh firing in exactly that configuration (added after PR review).
- Q: What if the host has no scheduling capability? → A: The guide says so and stops. It never falls
  back to OS schedulers (cron, launchd, Task Scheduler) or to a loop inside Ignis.

### Session 2026-10-22

- Q: Are the agent decisions of 21/10 confirmed? → A: Yes, all five listed under "Owner review"
  (owner, 22/10/2026). The constitution amendment they waited on is ratified (2.2.0, 21/10/2026).
- Q: Where does a firing start, given the T001 probe? → A: In the folder of the session that
  created the task: `create_scheduled_task` takes no working folder. Setup therefore checks that
  its own folder is the research workspace's repository, or that `IGNIS_CALLER_ROOT` is set, before
  creating; a first run that reports `ROOT_REQUIRED` means the task is deleted and set up again
  from the right folder (agent decided; basis: `.handoff/spec017/host-probe.handoff.md`).
- Q: The probe showed a task saved in the creating session's Auto mode. How does FR-007 hold? →
  A: Setup reads the creation result; a task saved in an Auto or Bypass mode is paused at once
  and stays paused until the person changes its mode in the app (agent decided; basis: the probe
  and the owner's confirmation of FR-007).
- Q: Is the new prompt and resource (OG-2) accepted? → A: Yes, under the owner's go-ahead of
  22/10/2026 to implement Spec 017; no tool or signature changes.

### Session 2026-10-23

- Q: The T006 acceptance found Threads and Reels `AUTH_REQUIRED` inside the caller root while
  `verify_connectors_health` reported them healthy. Which store holds platform sessions? → A: The
  installation store. `authenticate_*` saves there, so a caller root's missions now read sessions
  there too, as does the self-content guard; the caller store keeps the caller's evidence and its
  own `YOUTUBE_API_KEY`. A caller root never creates an absent SQLite installation store; it then
  reads its own store as before (owner decided 23/10/2026: "Sửa code để caller scope thấy phiên
  đăng nhập").

### Session 2026-10-26

- Q: The owner accepted the T006 routine saved in Auto mode. Does FR-007 still refuse auto? → A: No.
  Bypass stays refused. Auto is allowed when the person explicitly accepts it for that routine; the
  guide tells them the routine will then run without asking before each tool, and pauses it
  otherwise (owner decided 23/10/2026: "Không cần thiết quá quan trọng việc này. Harness của Claude
  Code đã dư sức chống lại prompt injection rồi."; recorded by the agent on 26/10/2026).
- Q: Which T006 findings change the guide? → A: Before creating, the guide checks that each channel
  can collect for the workspace (the YouTube key in `.fnignis/.env`, a saved sign-in for browser
  channels), leaves out channels without keyword search (`tiktok_creative_center`) or keyword
  measurement (`google`), and names `CALLER_CONFIG_CHANGED` as the sign that the session's server
  needs a restart; the report mentions the app's dispatch delay (07:00 shown as 07:13) (agent
  decided; basis: `.handoff/spec017/acceptance.handoff.md` findings 1, 4, 5, 6 and 8).
- Q: A firing only collects, but Spec 016 FR-010 counts only judged evidence. Who judges? → A: The
  firing itself, as the host agent the 21/10 decision names: after collection it judges the run's
  evidence with `get_mission_evidence_qualification_batch` and
  `submit_mission_evidence_qualifications` until READY, and reports how many items were on the
  topics. Setup asks for those two approvals too (agent decided; basis: the G3 period views of
  23–25/10/2026 showed no figure or item until the 25/10 run was judged, after which three items
  appeared).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Set up a daily routine on request (Priority: P1)

The user asks their Claude Code Desktop agent to run their matcha watchlist every morning. The agent
reads the Ignis routine guide, shows what will run (watchlist name and version, channels, daily
time, what happens after collection, how to pause it) and creates the routine only after the user
confirms.

**Why this priority**: Without it, history depends on the user remembering to run the watchlist.

**Independent Test**: In Claude Code Desktop with a fixture watchlist, follow the guide: the routine is
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
  terminal state, judge that mission's evidence against the watchlist with the evidence-qualification
  tools until it is READY (Spec 016 FR-010 counts only judged items), and report the outcome. It MUST NOT backfill missed days, broaden the watchlist,
  create or revise watchlists, or publish anything.
- **FR-006**: Rendering a period view on a firing MUST happen only if the user asked for it at setup;
  the artifact MUST stay local.
- **FR-007**: The guide MUST refuse to let a routine run in a bypass permission mode (a task the host
  saved in it is paused until the person changes it), and MUST let a routine run in an auto mode only
  when the person explicitly accepts that for the routine, pausing it otherwise. It MUST end setup
  with an attended "Run now" that, in a mode that asks, grants approvals for only
  `start_watchlist_run`, `execute_mission_ingress`, `get_mission_evidence_qualification_batch` and
  `submit_mission_evidence_qualifications`; a routine without them MUST be described to the user as
  attended. *(Amended 26/10/2026 from "never auto or bypass" by the owner decision of
  23/10/2026.)*
- **FR-008**: Removing a routine MUST require the user's confirmation and MUST leave watchlist history
  untouched.
- **FR-020**: Each routine MUST start in a validated working folder that resolves the research
  workspace's caller root (the repository folder, or an operator-set `IGNIS_CALLER_ROOT`); since the
  host starts a firing in the creating session's folder, setup MUST check that folder and refuse a
  home or root folder.
- **FR-009**: Claude Code Desktop local scheduled tasks, as confirmed by the T001 probe on current
  versions, MUST be the supported host; any other host MUST be
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

- **SC-001**: In a Claude Code Desktop acceptance run, following the guide from a single explicit request
  creates exactly one routine, and following it without a request creates none.
- **SC-002**: Each manual "run now" of the routine produces exactly one watchlist run bound to the
  current version. Its only writes are those that run owns (the mission, its run journal, observations,
  mission evidence, channel outcomes and terminal state); it creates no other mission, watchlist,
  watchlist version or routine record.
- **SC-003**: The stored routine prompt contains the watchlist identifier and every FR-005
  prohibition, and no credential or author identity.
- **SC-004**: The repository still contains no scheduler, worker or background loop (existing
  convention tests stay green).
- **SC-005**: Over 14 consecutive days of a real routine on one golden-set watchlist, the share of
  days with a completed run is recorded; no target is set by this feature.

## Assumptions

- Spec 016 is merged first (watchlists, `start_watchlist_run`, ceilings, period snapshot).
- The golden-set baseline run, ordered before Spec 017 in the decision record, is complete and
  recorded before implementation starts.
- The owner ratifies the Spec 016 constitution amendment before this feature merges.
- The host's scheduled-task behaviour is as documented on 21/10/2026; if a firing missed while the
  app was closed runs once or several times on launch is not documented, and the guide does not
  depend on it.
- Real social sessions used by a routine are the user's own, configured outside this feature.

## Owner review

Agent decisions under the owner's delegation of 21/10/2026, confirmed by the owner on 22/10/2026:

1. No Ignis-side record of routines; no new tool or table (FR-011).
2. One routine per watchlist; at most daily; proposed default time 07:00 local (FR-004).
3. No period view on a firing unless asked at setup (FR-006).
4. Attended setup "Run now" granting only the two Ignis tools; never bypass, and auto only when the
   person accepts it (FR-007, amended 26/10/2026).
6. A routine's working folder is the workspace repository or an operator-set root (FR-020).
5. Merge waits for the constitution amendment (FR-012).
