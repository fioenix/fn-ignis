# Research: Host-Scheduled Watchlist Routines

## R1. Which host capability creates the routine?

**Decision**: Claude Code Desktop's local scheduled tasks (the `scheduled-tasks` tools:
create, list, update, run now), with a daily 5-field cron in local time.

**Rationale**: Documented on 21/10/2026: tasks are stored as self-contained prompts under
`~/.claude/scheduled-tasks/{taskId}/SKILL.md`, run as fresh sessions, reach local MCP servers and
SQLite, run while the app is open and run on next launch when due while closed. The ADR names this
host first.

**Alternatives**: Codex and Antigravity scheduled tasks (MCP access undocumented; need a probe,
FR-009); cloud routines (cannot reach a local server or browser sessions; later, API channels with
a remote database only); OS schedulers (rejected: outside the host's visible control and contrary
to "host-native").

## R2. Does Ignis record the routine?

**Decision**: No.

**Rationale**: The host already lists, pauses and removes routines in its own interface; a copy in
Ignis would drift (the user can delete the task in the host without telling Ignis). Each firing is
an ordinary watchlist run, which Spec 016 already records.

**Alternatives**: a `watchlist_routines` table or a `trigger` field on `start_watchlist_run`
(rejected: new surface for no reader).

## R3. How is "one routine per watchlist" enforced without an Ignis record?

**Decision**: By convention in the guide: the task identifier is `ignis-watchlist-<watchlist id
prefix>`, and setup lists the host's tasks first and refuses a duplicate identifier.

**Rationale**: The host refuses a duplicate identifier and suggests another; the guide treats that
as "a routine already exists" and offers to change it instead.

## R4. What does the routine prompt contain?

**Decision**: A fixed template in the guide with three substitutions (watchlist id, watchlist name,
whether to render the period view). It tells the fresh session to: call `start_watchlist_run`, run
the mission's collection with `execute_mission_ingress`, respect `RATE_LIMITED`/`daily_ceiling`,
stop at a terminal state, report the mission id and per-channel status, and never backfill,
broaden, edit watchlists or publish.

**Rationale**: Each firing starts with no memory, so the prompt must be complete; a fixed template
is testable (SC-003).

## R5. Cadence

**Decision**: At most daily; default proposal 07:00 local time.

**Rationale**: Spec 016 judges coverage per day and ceilings are per day; a faster cadence adds
requests without adding coverage. Morning collection gives a complete previous day for date-bounded
channels.

## R6. Permission mode and approvals

**Decision**: Refuse auto and bypass modes; end setup with an attended "Run now" that approves only
`start_watchlist_run` and `execute_mission_ingress` for the routine.

**Rationale**: The host may save the routine with the creating session's mode; an auto or bypass
routine would approve every tool unattended, including real-session connectors. In the default mode
the first unattended firing would instead stop at its first approval prompt and add no history
(PR review, 21/10/2026). Narrow approvals granted once while the user watches keep both properties.

## R7. Missed firings

**Decision**: The guide does not rely on how many missed firings the host replays on launch; each
firing is one run of "now", and Spec 016 places observations by their own dates.

## R8. Working folder

**Decision**: The task's working folder is the research workspace's repository folder, or the
operator sets `IGNIS_CALLER_ROOT`; acceptance runs a fresh firing in that configuration.

**Rationale**: Ignis resolves its caller root from the server's startup folder and refuses a home or
root folder (`docs/caller-storage.md`); a firing started in the host's default folder would fail with
`ROOT_REQUIRED` before creating a run.
