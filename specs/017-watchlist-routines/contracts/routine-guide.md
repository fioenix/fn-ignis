# Contract: Routine Guide Surface

No tool or signature changes. One prompt and one resource are added; tool count is unchanged.

## Resource `fn-ignis://guide/ignis-routine`

Returns the packaged guide `src/ignis/interfaces/mcp/guides/ignis_routine.md`, byte-identical to
the body of `.agents/skills/ignis-routine/SKILL.md`. Starts no read, collection or write.

## Prompt `ignis_routine(watchlist_id=None)`

Returns the guide, preceded by the watchlist identifier when one is given. Refuses a
`watchlist_id` that is not a UUID, like `ignis_track` refuses a non-UUID mission id. Reads nothing.

## Guide sections (required)

1. **When to use**: only after the user explicitly asks for a recurring run of a named watchlist.
2. **Before creating**: list host tasks; refuse a duplicate; refuse faster than daily; show watchlist
   name, channels, daily time, working folder, post-collection behaviour, the approvals the attended
   first run will ask for and how to pause;
   wait for confirmation.
3. **Create**: the host scheduling call with task identifier `ignis-watchlist-<first 8 characters of
   the watchlist id>`, daily cron and the routine prompt template filled in, from a session whose
   folder is the research workspace's repository (the host starts firings there; a home or root
   folder is refused). A task saved in an auto or bypass permission mode is paused until the
   person changes it. Setup ends with an attended "Run now" that approves only
   `start_watchlist_run` and `execute_mission_ingress`.
4. **Routine prompt template**: self-contained; one `start_watchlist_run`, collection via
   `execute_mission_ingress`, ceilings respected, stop at terminal state, report mission id and
   per-channel status; prohibitions: no backfill, no broadening, no watchlist edits, no publishing,
   no second run; period view only if requested at setup, local only.
5. **Change, pause, remove**: update time; disable to pause; delete only after confirmation; history
   untouched.
6. **Unsupported hosts**: say so and stop; no OS scheduler, no Ignis loop.
