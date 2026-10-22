---

description: "Task list for Spec 016 — Watchlist Listening and Period Comparison"
---

# Tasks: Watchlist Listening and Period Comparison

**Input**: [spec.md](spec.md), [plan.md](plan.md), [research.md](research.md),
[data-model.md](data-model.md), [contracts/mcp-surface.md](contracts/mcp-surface.md),
[quickstart.md](quickstart.md)

**Tests**: Included and written first; each test task must be observed failing before its
implementation task.

**Prerequisite**: Spec 015 merged to `main` (migration 031, declared accounts, 48 tools). Rebase
this branch on it before T004.

## Phase 1: Setup

- [x] T001 Rebase on `main` after Spec 015 merges; record the base commit, latest migration
  (expected `031`) and tool count (expected 48) in `plan.md`. Stop and report if either differs.
  Done 21/10/2026: rebased on `main` at `1f4971e` (PR #57, Spec 015); latest migration `031_author_identity_at_rest.sql`; 48 tools.
- [ ] T002 [P] Create fixtures in `tests/fixtures/watchlist_fixtures.py`: a two-topic watchlist and
  observations spanning two complete weeks across all five channels, with one channel missing three
  days in one week, items observed twice, and one item without a publication date.

## Phase 2: Foundational

- [~] T003 [P] Write failing unit tests in `tests/unit/test_watchlist_domain.py`: definition limits
  and digest, period boundaries in Asia/Ho_Chi_Minh (day, Monday-to-Sunday week, month, across
  midnight and month ends), placement by publication date with the plausibility guard, coverage from
  probe outcomes, the 20 percent rule per topic and channel, and the 7-day counted observation.
- [x] T004 Implement `src/ignis/domain/watchlist.py` until T003 passes.
  Part A done 21/10/2026: `src/ignis/domain/watchlist.py` (definition, limits, digest). Period functions are on the Part B branch.
- [x] T005 Write `sql/032_watchlists.sql` (three owner-only tables, immutable versions, seeded
  `runtime_configs`) and the SQLite mirror in `_ensure_schema`; move the pinned newest-migration
  surfaces (`test_sql_packaging.py`, `tests/integration/conftest.py`, `test_compose_init.py`,
  `test_postgres_rls_coverage.py`, `test_public_distribution_contract.py`, README and USER_GUIDE
  migration paragraphs) to 032, with a SQLite upgrade rehearsal test.
  Done 21/10/2026: `sql/032_watchlists.sql`, SQLite mirror, pins moved to 032; `tests/unit/test_watchlist_schema.py`.
- [x] T006 Add repository methods for watchlists, versions and runs, and a period read of a
  watchlist's observations with their selected values and probe outcomes, on both backends;
  dual-backend tests in `tests/integration/test_watchlist_repository.py`.
  Done 21/10/2026: both repositories; `tests/integration/test_watchlist_repository.py` 12/12 on SQLite and PostgreSQL.

## Phase 3: US1 — Follow a watchlist across runs (P1)

- [x] T007 [US1] Failing tests, then `save_watchlist`, `get_watchlist` and `start_watchlist_run`
  per the contract, in `tests/integration/test_watchlist_mcp.py` and `server.py`; brands become the
  run's declared accounts.
  Done 21/10/2026: three tools; `tests/integration/test_watchlist_mcp.py` 16/16 on SQLite and PostgreSQL. Brands are declared through Spec 015.
- [x] T008 [US1] Raise every governed tool-count surface from 48 to 51 (Part A; Part B raises it to 52) and regenerate manifests
  with `scripts/sync_tool_manifests.py --write`.
  Done 21/10/2026: 48 → 51 on every governed surface; Hermes manifests regenerated.

## Phase 4: US2 — Compare two complete periods (P1)

- [x] T009 [US2] Failing tests in `tests/unit/test_watchlist_period.py` for the comparison cells,
  refusal of an incomplete period, no cross-channel sums, counter stability, and terms.
  Done 22/10/2026: `tests/unit/test_watchlist_period.py`, 23 tests, RED observed (module absent); negative controls: an unbounded counting window fails 2, a DEGRADED day counted as complete fails 1.
- [x] T010 [US2] Implement `src/ignis/application/use_cases/watchlist_period.py` and
  `get_watchlist_period_snapshot`; dual-backend integration test for SC-001–SC-004 and SC-006.
  Done 22/10/2026: `src/ignis/domain/watchlist_period.py`, `src/ignis/application/use_cases/watchlist_period.py`, tool `get_watchlist_period_snapshot` (51 → 52 tools); `tests/integration/test_watchlist_period_storage.py` 5/5 on SQLite and PostgreSQL. Reads existing repository methods; no migration.

## Phase 5: US3 — Read the period view (P2)

- [x] T011 [US3] Failing tests in `tests/unit/test_ignis_listen_guidance.py`: prompt and resource
  listed, guide packaged, SKILL body equal to the packaged guide, serving starts no read.
  Done 22/10/2026: `tests/unit/test_ignis_listen_guidance.py`, RED observed (prompt, resource and skill absent).
- [x] T012 [US3] Write `src/ignis/interfaces/mcp/guides/ignis_listen.md` and
  `.agents/skills/ignis-listen/SKILL.md`; register the prompt and resource; verify SC-005 on a
  fixture snapshot.
  Done 22/10/2026: guide, skill mirror, prompt, resource and `openclaw.json`. SC-005 on the unit fixture snapshot: a view rendered by the guide holds 70 numbers, none absent from the snapshot (`.handoff/spec016/sc005-view.md`).

## Phase 6: US4 — Bounded collection and finite history (P3)

- [ ] T013 [US4] Failing tests, then the per-channel daily request ceiling read from
  `runtime_configs` in the connector registry, with status `RATE_LIMITED`/`daily_ceiling`.
- [ ] T014 [US4] Failing tests, then `scripts/prune_expired_observations.py` with `--dry-run` and
  `--apply`, keeping referenced observations.

## Phase 7: Polish

- [x] T015 [P] Draft the constitution amendment (Principles I and III) as Proposed with its impact
  report; do not ratify. Drafted 21/10/2026 in [constitution-amendment.md](constitution-amendment.md)
  rather than in `.specify/memory/constitution.md`, so no agent reads a Proposed text as in force.
- [ ] T016 [P] Document watchlists and the period view in README.md, README.vi.md,
  docs/USER_GUIDE.md and docs/USER_GUIDE.vi.md; Vietnamese through the vietnamizer core workflow.
  Part A done 21/10/2026: watchlists in README.md, README.vi.md and both user guides; Vietnamese through the vietnamizer core workflow.
- [ ] T017 Run the quickstart, the full suite on SQLite and PostgreSQL, ruff, `git diff --check`,
  `uv lock --check`, the package build and `scripts/wheel_mcp_smoke.py`; record results in
  `.handoff/spec016/regressions.handoff.md`.
  Part A, 21/10/2026: full suite on SQLite 4231 passed, 1034 skipped, 3 failed; the same 3 fail on a `main`-based worktree locally (clean-checkout bootstrap and the missing worktree `.venv`) and pass in CI. Watchlist, RLS and Compose files on PostgreSQL 46/46 after rebasing on Spec 015.
- [ ] T018 Code and security review of the full diff; dispose of findings with evidence before the
  PR.
  Part A, 21/10/2026: self-review found unbounded definition text and an unreported declaration status, both fixed (`T018 finding` commit).

## Phase 8: Collection precision (from the golden-set baseline, 22/10/2026)

- [x] T019 Failing tests in `tests/unit/test_youtube_plugin.py` and
  `tests/unit/test_connector_registry*.py`, then the YouTube keyword check and its per-keyword
  dropped count on `SearchAttestation`, carried into the probe outcome's `scope_attestation`
  (clarification of 22/10/2026). Accept only after a same-day live golden-set rerun of `main` and
  this branch, both scored with `jev-1.14.0` at 0.60 over the first 50 signals, shows this branch
  no lower on any of the four watchlists; record both scores in the pull request.
  Done 22/10/2026 in PR #66: share G2 0.132→0.385, G3 0.167→0.250, G4 0.408→0.667, G5
  0.667→0.815 (main 10:32, branch 12:02 ICT); relevant items fall on G3, G4 and G5 (6→5, 20→16,
  30→22).

## Landing in two pull requests

- **Part A** (merges on green CI and review): T001–T008, T016 for US1, T017, T018. T003 and T004
  are split: definition tests and code here, period tests and code in Part B (`[~]`). Tool count
  48 → 51 (`save_watchlist`, `get_watchlist`, `start_watchlist_run`).
- **Part A2** (US4, T013–T014): the per-channel daily ceiling needs a persistent per-day request
  count that survives separate routine sessions, which `data-model.md` does not yet define
  (`youtube_quota_buckets` already does this for YouTube alone). Re-planned before implementation.
- **Part B** (opens after Part A merges; merges only after the owner ratifies the amendment): T009–T012,
  T015, T016 for US2 and US3, T017, T018. Tool count 51 → 52 (`get_watchlist_period_snapshot`).

## Dependencies

T001 gates everything. T003→T004; T005→T006; T006→T007, T009–T010; T007→T008; T011→T012; US4 after
T005. Polish last.
