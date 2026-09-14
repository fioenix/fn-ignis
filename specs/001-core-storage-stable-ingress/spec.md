# Feature Specification: Core TimescaleDB Storage & Stable Ingress Feeds

**Feature Directory**: `specs/001-core-storage-stable-ingress`
**Created**: 2026-08-31
**Status**: Shipped in `v0.4.0` on `main`. The storage model is live in the released runtime; migrating an existing PostgreSQL corpus and the SC-001/SC-004 convergence gaps remain open
**Input**: Pha 1 (Core Storage & Stable Ingress Feeds) - Postgres TimescaleDB Repository Adapter + YouTube Data API v3 Plugin + Google Trends RSS Plugin
**As-built amendment**: 2026-09-13 — source/observation/mission-evidence storage contract

---

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Time-Series Storage & Fast Retrieval (Priority: P1)

As an AI agent or background service, I need storage to distinguish an external source from each
time it was observed and from the missions that used that observation, so repeated polling and
cross-mission evidence remain auditable on both SQLite and PostgreSQL.

**Why this priority**: Đây là nền móng của toàn bộ hệ thống lưu trữ theo Nguyên tắc III (Storage-First & Time-Series Rigor). Không có tầng Repository hoàn chỉnh, các Ingress Plugin không thể lưu dữ liệu và MCP Tool không thể truy vấn.

**Independent Test**:
- Khởi tạo PostgresTimescaleRepository với Connection Pool (`psycopg_pool`).
- Save repeated sightings of one source from two missions and five `TopicCluster` records.
- Truy vấn `get_top_clusters` theo GeoCode và Timeframe trả về đúng thứ tự ranking dưới 50ms.
- Truy vấn `get_cluster_signals` trả về danh sách lịch sử tín hiệu chuỗi thời gian chính xác.

**Acceptance Scenarios**:
1. **Given** two sightings resolve to the same `(platform, external_id)`, **When**
   `save_signals(signals)` runs, **Then** storage keeps one `sources` row, writes one immutable
   `observations` row per sighting, attaches each mission through `mission_evidence`, and returns
   the number of observations recorded.
2. **Given** Danh sách các TopicCluster cần cập nhật, **When** gọi `save_clusters(clusters)`, **Then** các cluster được upsert (insert hoặc update theo `id`) mà không làm mất liên kết signals.
3. **Given** Dữ liệu tín hiệu đã được ghi nhận trong 24 giờ qua, **When** gọi `get_top_clusters(geo=VN, timeframe=LAST_24H, limit=10)`, **Then** hệ thống trả về tối đa 10 cụm chủ đề sắp xếp theo `cross_platform_score` giảm dần với thời gian thực thi < 50ms.
4. **Given** a legacy PostgreSQL corpus, **When** the production cutover runs, **Then** a baseline
   generated from the quiesced snapshot, the schema migration, the backfill, and the verifier must
   preserve the four source/observation/mission/cluster multisets before the new runtime starts.

---

### User Story 2 - Google Trends RSS Ingress Plugin (Priority: P2)

Là hệ thống thu thập dữ liệu xu hướng tự động, tôi cần một Ingress Plugin thu thập dữ liệu Google Trends Daily RSS cho khu vực chỉ định (mặc định Việt Nam - VN) mà không tiêu tốn API token hoặc chi phí tài chính (Zero-Token Ingress), tự động trích xuất các từ khóa tìm kiếm nổi bật, lưu lượng tìm kiếm ước tính và bài viết liên quan.

**Why this priority**: Google Trends RSS là nguồn dữ liệu thời sự chính thống, hoàn toàn miễn phí ($0), không cần API Key, cho phép kiểm chứng Ingress Pipeline và Circuit Breaker ngay lập tức.

**Independent Test**:
- Kích hoạt `GoogleTrendsRssPlugin.fetch_signals(geo=GeoCode.VN)`.
- Kiểm tra danh sách trả về là các `TrendSignal` với `platform=GOOGLE`, `metric_value` (ước tính approximate traffic), metadata chứa news snippet và source link.

**Acceptance Scenarios**:
1. **Given** Nguồn cấp RSS `https://trends.google.com/trending/rss?geo=VN` khả dụng, **When** plugin thực hiện `fetch_signals()`, **Then** trả về danh sách các `TrendSignal` với đầy đủ tiêu đề, lượng search ước tính, và `geo_code=VN`.
2. **Given** Nguồn cấp RSS bị gián đoạn mạng hoặc định dạng XML bị lỗi, **When** plugin thực thi, **Then** ngoại lệ được bắt, Circuit Breaker ghi nhận failure và không làm sập tiến trình Ingress chung.

---

### User Story 3 - YouTube Data API v3 Trending Ingress Plugin (Priority: P3)

Là hệ thống lắng nghe xu hướng đa kênh, tôi cần một Ingress Plugin kết nối với YouTube Data API v3 (`videos.list(chart='mostPopular')`) để thu thập các video đang thịnh hành tại Việt Nam kèm các chỉ số tương tác (views, likes, comments, velocity) và chuyển đổi thành `TrendSignal`.

**Why this priority**: YouTube là kênh video quan trọng nhất tại thị trường Việt Nam để đo lường độ lan tỏa truyền thông và sự quan tâm của công chúng.

**Independent Test**:
- Cung cấp mock hoặc API Key hợp lệ cho `YouTubeDataPlugin`.
- Gọi `fetch_signals(geo=GeoCode.VN, limit=50)`.
- Xác nhận các entity `TrendSignal` có `platform=YOUTUBE`, `metric_value` = viewCount, metadata chứa channelTitle, tags, likeCount, publishedAt.

**Acceptance Scenarios**:
1. **Given** Cấu hình `YOUTUBE_API_KEY` hợp lệ, **When** gọi `fetch_signals()`, **Then** hệ thống gọi endpoint `mostPopular`, trích xuất thông tin video và trả về danh sách `TrendSignal` chuẩn hóa.
2. **Given** API Key hết hạn ngạch (quota exceeded / 403 Forbidden), **When** plugin gọi API, **Then** ném ra `ConnectorQuotaExceededException`, Circuit Breaker chuyển sang trạng thái OPEN để tránh spam request vô ích.

---

## Edge Cases

- **Mất kết nối Database hoặc Connection Pool cạn kiệt**: Repository ném lỗi có kiểm soát, retry ngắn hạn trước khi báo lỗi về use case.
- **Dữ liệu RSS/API trả về rỗng hoặc sai cấu trúc**: Plugin bỏ qua bản ghi lỗi (bad record), ghi log cảnh báo và tiếp tục xử lý các bản ghi hợp lệ còn lại.
- **Repeated sightings in one collection cycle**: source identity is deduplicated by the database on
  `(platform, external_id)`, while every collection event remains a separate observation. No
  uniqueness constraint may collapse observations based on title, timestamp, metric, or payload.
- **Unknown legacy ingestion clocks**: `observed_at` remains `NULL` and
  `time_provenance=legacy_publish_only`; publication time must never be substituted for ingestion
  time.

---

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Hệ thống PHẢI cài đặt `PostgresTimescaleRepository` tuân thủ interface `ITrendRepository`, sử dụng `psycopg_pool.AsyncConnectionPool` để quản lý kết nối hiệu năng cao.
- **FR-002**: Both repositories MUST implement `save_signals()` as a database-enforced source
  upsert followed by one observation per sighting and mission attachment through
  `mission_evidence`. Runtime code MUST NOT write `trend_signals` or `signal_metrics`.
- **FR-003**: `PostgresTimescaleRepository` PHẢI hỗ trợ upsert `save_clusters()` vào bảng `topic_clusters` kèm cập nhật thời gian `last_updated_at`.
- **FR-004**: `GoogleTrendsRssPlugin` PHẢI tuân thủ `IConnectorPlugin`, sử dụng `httpx` async và `feedparser` để cào RSS Google Trends theo `geo` (hỗ trợ VN, US, GLOBAL).
- **FR-005**: `YouTubeDataPlugin` PHẢI tuân thủ `IConnectorPlugin`, hỗ trợ cào trending videos qua Google API Client / `httpx` async REST endpoint, xử lý phân trang và giới hạn limit.
- **FR-006**: Mọi Connector Plugin PHẢI tích hợp chặt chẽ với `ConnectorPluginRegistry` và `CircuitBreaker` để đảm bảo cách ly lỗi hoàn toàn.
- **FR-007**: Ingress use cases MUST persist observations through `ITrendRepository`, assign cluster
  membership to the observation, and replace mission evidence by writing new evidence before
  pruning old claims. This sequence is failure-safe but is not described as atomic.
- **FR-008**: `sources` MUST contain exactly `id`, `platform`, and `external_id`, with
  `UNIQUE(platform, external_id)`. Titles, URLs, identity resolution route, lifecycle clocks, and
  cluster membership belong to observations.
- **FR-009**: `observations` MUST preserve `identity_source` and `time_provenance`, permit multiple
  identical payloads, and allow one source to participate in multiple clusters through different
  observations.
- **FR-010**: Existing PostgreSQL corpora MUST be migrated by the reviewed `sql/016` schema,
  deterministic lineage-based backfill, and fail-closed post-migration verification. The tracked
  baseline is a policy review artifact, not the production reference.

### Key Entities

- **Source**: One external object identified by platform and namespaced external identifier.
- **Observation / TrendSignal**: One collection event for a source, including the observed title,
  URL, metrics, metadata, cluster membership, identity route, and clock provenance.
- **MissionEvidence**: A mission's claim on the exact observation it used. The unique key is
  `(mission_id, observation_id)`, never `(mission_id, source_id)`.
- **TopicCluster**: Cụm chủ đề xu hướng tổng hợp từ nhiều nền tảng (canonical_name, summary_text, category, cross_platform_score, embedding, first_seen_at, last_updated_at).

---

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Thời gian truy vấn `get_top_clusters` với 10,000+ tín hiệu mẫu trong database đạt độ trễ P95 < 50ms.
- **SC-002**: 100% Ingress Plugin hoạt động hoàn toàn ở chế độ Deterministic / 0 LLM Token.
- **SC-003**: Khi một plugin gặp sự cố mạng hoặc lỗi API, tiến trình Ingest tổng thể vẫn thu thập thành công 100% dữ liệu từ các plugin khỏe mạnh còn lại.
- **SC-004**: Toàn bộ unit tests & integration tests cho Repository, RSS Plugin, YouTube Plugin và Registry đạt độ phủ (test coverage) >= 85%.

---

## Assumptions

- SQLite is the zero-configuration default; PostgreSQL 16 with optional TimescaleDB is the
  production backend. `observations` is deliberately not a hypertable because honest legacy rows
  may have a `NULL` ingestion clock.
- Định dạng dữ liệu Google Trends Daily RSS duy trì cấu trúc XML chuẩn của Google Trends.
- YouTube Data API v3 yêu cầu API Key cấu hình qua biến môi trường `YOUTUBE_API_KEY`. Nếu không có key, plugin trả về trạng thái `is_healthy() == False` mà không làm crash ứng dụng.
