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
