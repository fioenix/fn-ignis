# Quickstart: Watchlist Routines

Validation guide; [tasks.md](tasks.md) is the acceptance authority.

1. **Offline** (CI): `.venv/bin/pytest tests/unit/test_ignis_routine_guidance.py
   tests/unit/test_ignis_skills.py` — guide packaged, mirrored, listed, serving starts no read,
   template carries every FR-005 prohibition.
2. **Claude Code Desktop acceptance** (manual, recorded in `.handoff/spec017/acceptance.handoff.md`):
   - With a fixture watchlist on local SQLite, ask "run this watchlist every morning at 7"; confirm;
     one task `ignis-watchlist-<prefix>` appears in the host's list.
   - Ask again: the agent offers to change the existing task.
   - Setup's attended "Run now" asks to approve only `start_watchlist_run` and
     `execute_mission_ingress`; one mission bound to the current version reaches a terminal state,
     and no other mission, watchlist version or routine record is written.
   - A second, unattended firing from the task's own working folder (the workspace repository)
     reaches the Ignis server with the right caller root and needs no new approval.
   - Pause, resume, change the time, remove after confirmation; the watchlist history is unchanged.
   - Ask for a period view only: no task is created.
