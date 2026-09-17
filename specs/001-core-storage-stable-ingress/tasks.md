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
- [ ] T020 [US1] Execute the production cutover runbook against the existing PostgreSQL corpus.
  The code half is done and released as `v0.4.0`, so what remains is the data migration itself --
  a baseline generated from the
  quiesced production snapshot, the backfill, and verifier status `VERIFIED` before the new runtime
  is pointed at that corpus. This blocks activation on an existing corpus; it does not block a
  fresh SQLite install, which has nothing to migrate.

---

## Phase 7: Convergence Gaps (2026-09-13)

- [ ] T021 [US1] Add a reproducible dual-backend benchmark with at least 10,000 observations and
  enforce `get_top_clusters` P95 < 50 ms; SC-001 currently has no benchmark evidence
- [ ] T022 [US1] Define the coverage scope promised by SC-004, raise it to at least 85%, and enforce
  the threshold in CI; the 2026-09-13 SQLite-only run measured 73% overall and 71% across
  persistence/connectors, while the latest Timescale-backed CI run measured 75% overall without
  `--cov-fail-under`
