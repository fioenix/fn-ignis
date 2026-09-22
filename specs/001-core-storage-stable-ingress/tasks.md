# Tasks: Core TimescaleDB Storage & Stable Ingress Feeds

**Input**: Design documents from `specs/001-core-storage-stable-ingress/`
**Prerequisites**: `plan.md`, `spec.md`

## Phase 1: Setup & Foundational

- [x] T001 Tạo module cấu hình hệ thống `src/ignis/config.py` sử dụng `pydantic-settings`
- [x] T002 Bổ sung các domain exceptions chuẩn mực trong `src/ignis/domain/exceptions.py`
- [x] T003 Thiết lập pytest setup và test fixtures trong `tests/conftest.py`

---

## Phase 2: User Story 1 (P1) - Postgres TimescaleDB Storage

**Goal**: Cài đặt `PostgresTimescaleRepository` kết nối PostgreSQL/TimescaleDB bằng `AsyncConnectionPool`, thực thi `save_signals`, `save_clusters`, `get_top_clusters`, và `get_cluster_signals` với độ trễ tối ưu.

- [x] T004 [P] [US1] Viết unit tests & mock tests cho `PostgresTimescaleRepository` trong `tests/unit/test_postgres_repository.py`
- [x] T005 [US1] Cài đặt `PostgresTimescaleRepository` trong `src/ignis/infrastructure/persistence/postgres_repository.py`
- [x] T006 [US1] Cài đặt Use Case `GetTopClustersUseCase` trong `src/ignis/application/use_cases/get_top_clusters.py`

**Checkpoint**: Tầng Storage & Retrieval hoạt động độc lập và hoàn thành unit tests.

---

## Phase 3: User Story 2 (P2) - Google Trends RSS Plugin

**Goal**: Cài đặt `GoogleTrendsRssPlugin` cào feed RSS hàng ngày của Google Trends, chuẩn hóa dữ liệu sang `TrendSignal` và cách ly lỗi.

- [x] T007 [P] [US2] Viết unit tests cho `GoogleTrendsRssPlugin` trong `tests/unit/test_google_trends_rss.py` (với mock feed XML)
- [x] T008 [US2] Cài đặt `GoogleTrendsRssPlugin` trong `src/ignis/infrastructure/connectors/google_trends/rss_plugin.py`

**Checkpoint**: Google Trends RSS Ingress thu thập và chuẩn hóa `TrendSignal` chính xác.

---

## Phase 4: User Story 3 (P3) - YouTube Data API v3 Plugin

**Goal**: Cài đặt `YouTubeDataPlugin` kết nối YouTube Data API v3, thu thập video thịnh hành và chuyển đổi sang `TrendSignal`.

- [x] T009 [P] [US3] Viết unit tests cho `YouTubeDataPlugin` trong `tests/unit/test_youtube_plugin.py` (với mock API response)
- [x] T010 [US3] Cài đặt `YouTubeDataPlugin` trong `src/ignis/infrastructure/connectors/youtube/youtube_plugin.py`

**Checkpoint**: YouTube Plugin thu thập và xử lý quota/errors đúng quy chuẩn.

---

## Phase 5: Integration & Ingest Orchestration

**Goal**: Tích hợp toàn diện các Ingress Plugins vào `ConnectorPluginRegistry`, kết nối `IngestTrendsUseCase` và chạy thử nghiệm.

- [x] T011 Cài đặt `IngestTrendsUseCase` trong `src/ignis/application/use_cases/ingest_trends.py`
- [x] T012 Viết integration test điều phối Ingestion với Circuit Breaker trong `tests/integration/test_ingest_orchestration.py`
- [x] T013 Viết CLI command runner mẫu trong `src/ignis/interfaces/cli/runner.py` để chạy thử nghiệm cào dữ liệu thực tế

---

## Phase 6: As-Built Source / Observation Contract (2026-09-13)

- [x] T014 [US1] Add dual-backend schema contracts for canonical sources, immutable observations,
  and mission evidence in `tests/integration/test_source_observation_schema_contract.py`
- [x] T015 [US1] Centralize platform object identity in
  `src/ignis/domain/source_identity.py` and enforce `UNIQUE(platform, external_id)`
- [x] T016 [US1] Cut both repositories over to `sources`, `observations`, and `mission_evidence`;
  stop all runtime writes to `trend_signals` and `signal_metrics`
- [x] T017 [US1] Add the shared legacy projection, read-only reconciliation audit, deterministic
  one-transaction backfill, and fail-closed verifier
- [x] T018 [US1] Make mission evidence replacement failure-safe by writing new claims before
  pruning old claims
- [x] T019 [US1] Add pre-backfill repository refusal and legacy-aware pruner protection
- [x] T020 [US1] Execute the production cutover runbook against the existing PostgreSQL corpus.
  The run completed on 20/09/2026 from a quiesced production snapshot. All four digests matched,
  the verifier returned `VERIFIED`, the new runtime started, and scheduled ingress reopened.

---

## Phase 7: Convergence Gaps (2026-09-13)

- [x] T021 [US1] Add a reproducible dual-backend benchmark with at least 10,000 observations and
  enforce `get_top_clusters` P95 < 50 ms. **Met on both backends on 22/09/2026.** Twenty enforced
  runs of `scripts/t021_read_path_benchmark.py` over 10,000 observations, ten per backend, zero
  failures: SQLite P95 23.662-29.496 ms (median run 27.066, median latency 20.541 ms), PostgreSQL
  P95 8.320-26.980 ms (median run 11.825, median latency 8.229 ms). The benchmark contract is
  unchanged -- same corpus floor, threshold, warm-up, iteration count, nearest-rank percentile and
  `--enforce` gate -- and every run returned 10 clusters / 50 signals. PostgreSQL evidence comes
  from a throwaway `timescale/timescaledb-ha:pg16` container reached only through
  `IGNIS_TEST_POSTGRES_DSN`.
  Two changes got it there, each measured on its own. `sql/019_observations_latest_per_source_index.sql`
  gives the latest-per-source ordering an index whose column list is the reader's ORDER BY term for
  term, partial on the two predicates the reader always applies; `EXPLAIN QUERY PLAN` no longer
  reports `USE TEMP B-TREE FOR LAST 5 TERMS OF ORDER BY` (SQLite median 39 -> 30 ms). Both readers
  then rank clusters from aggregates and read the payload only for the ones `limit` keeps, instead
  of building every cluster and slicing (SQLite median 30 -> 20.5 ms, PostgreSQL ~28 -> ~8 ms).
  `LIMIT` was deliberately **not** pushed below the aggregation and the score was **not** restated
  in SQL: `cross_platform_score` rounds half to even where both backends round half away from zero,
  and a SQL copy of that formula is the defect the scorer was consolidated to remove.
  One behaviour was deliberately changed: `cluster_rank_key` makes ties total by falling back to
  the cluster id, replacing an order that was previously undefined and could differ between
  backends and between runs. Behaviour is otherwise pinned by
  `tests/integration/test_top_clusters_characterization.py`, written before the rewrite, 24 cases
  per backend. Full evidence: `.handoff/T021-reader-optimization.handoff.md`
- [ ] T022 [US1] Define the coverage scope promised by SC-004, raise it to at least 85%, and enforce
  the threshold in CI; the 2026-09-13 SQLite-only run measured 73% overall and 71% across
  persistence/connectors, while the latest Timescale-backed CI run measured 75% overall without
  `--cov-fail-under`

---

## Phase 8: Production Cutover Tooling Hardening (2026-09-21)

- [x] T023 [US1] Make journal creation in `scripts/t020_cutover.py` collision-safe per FR-011:
  generate a unique path, create it exclusively, and add a clock-frozen test proving that two runs
  started in the same second cannot overwrite the first journal.
  Done 2026-09-21: `Journal.create()` names each run `t020-run-<stamp>-<NNN>.json` and opens it
  with `O_EXCL`; five clock-frozen tests in `tests/unit/test_t020_cutover.py`, including a
  negative control for a candidate path already on disk. `pytest tests/` 926 passed, 115 skipped
  (Postgres cases, `IGNIS_TEST_POSTGRES_DSN` absent).

---

## Phase 9: SC-001 CI Enforcement (2026-09-22)

- [x] T024 [US1] Publish the T021 benchmark as a CI gate for SC-001. This is enforcement, not new
  benchmark evidence: T021 measured the criterion and met it, and the number it produced describes
  22/09/2026 and nothing after it. `.github/workflows/performance.yml` re-runs
  `scripts/t021_read_path_benchmark.py --enforce` on both backends, so a regression turns a build
  red instead of going unnoticed until somebody re-reads a handoff.
  Deliberately not attached to `pull_request`: the benchmark seeds 10,000 observations per backend,
  and charging every contributor for that would catch on a feature branch a regression that only
  matters once it reaches a protected branch. It runs on pushes to `main`, `release/*` and
  `hotfix/*`, weekly on a schedule, and on manual dispatch. Ordinary PR CI is unchanged.
  The benchmark contract is untouched -- same corpus floor, threshold, warm-up count, iteration
  count, nearest-rank percentile, real repository reader and result-shape checks. The workflow
  passes two flags and nothing else; `tests/unit/test_t024_performance_workflow.py` (19 contracts)
  refuses a workflow that restates any of them, that drops `--enforce`, that swallows the exit
  code, that reaches PostgreSQL by any route other than `IGNIS_TEST_POSTGRES_DSN` against a
  throwaway `timescale/timescaledb-ha:pg16` service, that reads a repository secret, or that
  renames the job that a branch-protection rule would select.
  Known limit: this repository can publish a stable status name, but *requiring* it on `main` is a
  GitHub settings operation that no file here performs, and it has not been read back. Until it is,
  the workflow reports and does not block. Evidence and the remaining step:
  `.handoff/T024-sc001-ci-gate.handoff.md`
