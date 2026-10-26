# Quickstart: validating Goal-Driven Listening Period

Prerequisites: a confirmed research workspace with the G3 watchlist (`d78e5ed9`) and its stored
runs; the MCP server built from the feature branch.

1. **Record a plan (Part A)** — `set_watchlist_listening_plan` with goal "Theo dõi nhu cầu áo khoác
   chống nắng, chống nước theo tuần", period `week`, 3 snapshots. Expect `SAVED`; calling it again
   unchanged returns `UNCHANGED`; `get_watchlist` shows one plan row.
2. **Refusals** — period `hour`, cadence 0, cadence 8 on `week`, an empty goal: each returns
   `INVALID` with `INVALID_LISTENING_PLAN` and writes nothing.
3. **Routine guide** — ask the agent for a routine on G3: it shows 3 firings a week on distinct
   days and the requests per week, and waits for confirmation. On a watchlist without a plan it
   asks for goal, period and cadence first.
4. **Seen axis (Part B)** — with the clock moved past a complete week that holds at least 3
   snapshots (as in the 26/10 preview on a store copy), `get_watchlist_period_snapshot` without
   `period_kind` returns a week view whose `seen` cells count every relevant item each snapshot
   showed, averaged per snapshot (spec SC-001).
5. **Created view parity** — the same call's `axis: "created"` cells equal the pre-feature output
   field for field (spec SC-004).
6. **Both backends** — `pytest tests/unit/test_watchlist_listening_plan.py
   tests/unit/test_watchlist_seen_axis.py tests/integration/test_watchlist_listening_plan_storage.py`
   passes on SQLite and PostgreSQL.
