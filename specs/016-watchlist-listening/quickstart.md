# Quickstart: Watchlist Listening

Validation guide; [tasks.md](tasks.md) is the acceptance authority.

1. **Watchlist and runs** (US1): `save_watchlist` with two topics; revise one topic; check two
   versions. `start_watchlist_run` twice on fixtures; `get_watchlist` lists both runs on the right
   versions.
2. **Comparison** (US2): load fixture observations for two complete weeks, with TikTok missing three
   days in the earlier week; `get_watchlist_period_snapshot(..., "week")` shows comparable YouTube,
   Google and Threads cells and `not_comparable` TikTok with its missing days.
3. **Incomplete period**: request the current week; expect a refusal naming when it completes.
4. **Counter stability**: add a later observation of an earlier item with higher views; the earlier
   period's counted value is unchanged.
5. **Period view** (US3): follow `ignis-listen` on a fixture snapshot; the artifact is local and
   contains no number absent from the snapshot.
6. **Ceilings and retention** (US4): set a ceiling of 1 for a channel; a run stops that channel with
   `daily_ceiling`; `scripts/prune_expired_observations.py --dry-run` lists only unreferenced
   observations older than 13 months.

Run on SQLite, and on PostgreSQL with `IGNIS_TEST_POSTGRES_DSN` set.
