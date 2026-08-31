# Feature Specification: Core TimescaleDB Storage & Stable Ingress Feeds

**Feature Directory**: `specs/001-core-storage-stable-ingress`
**Created**: 2026-08-31
**Status**: Ready for Planning
**Input**: Pha 1 (Core Storage & Stable Ingress Feeds) - Postgres TimescaleDB Repository Adapter + YouTube Data API v3 Plugin + Google Trends RSS Plugin

---

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Time-Series Storage & Fast Retrieval (Priority: P1)

Là một AI Agent hoặc background service của `fn-ignis`, tôi cần một tầng lưu trữ chuỗi thời gian đáng tin cậy để lưu trữ hàng loạt `TrendSignal` và `TopicCluster`, đồng thời truy vấn các chủ đề có momentum cao nhất và lịch sử tín hiệu với độ trễ siêu thấp (< 50ms) nhằm phục vụ phản hồi tức thì cho người dùng.

**Why this priority**: Đây là nền móng của toàn bộ hệ thống lưu trữ theo Nguyên tắc III (Storage-First & Time-Series Rigor). Không có tầng Repository hoàn chỉnh, các Ingress Plugin không thể lưu dữ liệu và MCP Tool không thể truy vấn.

**Independent Test**:
- Khởi tạo PostgresTimescaleRepository với Connection Pool (`psycopg_pool`).
- Lưu 100 `TrendSignal` và 5 `TopicCluster`.
- Truy vấn `get_top_clusters` theo GeoCode và Timeframe trả về đúng thứ tự ranking dưới 50ms.
- Truy vấn `get_cluster_signals` trả về danh sách lịch sử tín hiệu chuỗi thời gian chính xác.

**Acceptance Scenarios**:
1. **Given** Cơ sở dữ liệu PostgreSQL đã cài đặt TimescaleDB và bảng `trend_signals` là hypertable, **When** gọi `save_signals(signals)`, **Then** toàn bộ bản ghi được batch insert an toàn và trả về số lượng bản ghi đã chèn thành công.
2. **Given** Danh sách các TopicCluster cần cập nhật, **When** gọi `save_clusters(clusters)`, **Then** các cluster được upsert (insert hoặc update theo `id`) mà không làm mất liên kết signals.
3. **Given** Dữ liệu tín hiệu đã được ghi nhận trong 24 giờ qua, **When** gọi `get_top_clusters(geo=VN, timeframe=LAST_24H, limit=10)`, **Then** hệ thống trả về tối đa 10 cụm chủ đề sắp xếp theo `cross_platform_score` giảm dần với thời gian thực thi < 50ms.

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
- **Tín hiệu trùng lặp trong cùng một chu kỳ cào**: Tầng lưu trữ TimescaleDB cho phép lưu time-series snapshot định kỳ hoặc áp dụng deduplication logic dựa trên `raw_title + platform + captured_at_bucket`.

---

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Hệ thống PHẢI cài đặt `PostgresTimescaleRepository` tuân thủ interface `ITrendRepository`, sử dụng `psycopg_pool.AsyncConnectionPool` để quản lý kết nối hiệu năng cao.
- **FR-002**: `PostgresTimescaleRepository` PHẢI hỗ trợ batch insert `save_signals()` vào hypertable `trend_signals` bằng câu lệnh SQL tối ưu (`executemany` hoặc `copy`).
- **FR-003**: `PostgresTimescaleRepository` PHẢI hỗ trợ upsert `save_clusters()` vào bảng `topic_clusters` kèm cập nhật thời gian `last_updated_at`.
- **FR-004**: `GoogleTrendsRssPlugin` PHẢI tuân thủ `IConnectorPlugin`, sử dụng `httpx` async và `feedparser` để cào RSS Google Trends theo `geo` (hỗ trợ VN, US, GLOBAL).
- **FR-005**: `YouTubeDataPlugin` PHẢI tuân thủ `IConnectorPlugin`, hỗ trợ cào trending videos qua Google API Client / `httpx` async REST endpoint, xử lý phân trang và giới hạn limit.
- **FR-006**: Mọi Connector Plugin PHẢI tích hợp chặt chẽ với `ConnectorPluginRegistry` và `CircuitBreaker` để đảm bảo cách ly lỗi hoàn toàn.
- **FR-007**: Hệ thống PHẢI cung cấp Use Case `IngestTrendsUseCase` điều phối việc cào từ tất cả plugin đã đăng ký và lưu vào repository trong một transaction an toàn.

### Key Entities

- **TrendSignal**: Tín hiệu xu hướng đơn lẻ từ một nền tảng (platform, raw_title, metric_value, growth_velocity, source_url, geo_code, metadata, captured_at).
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

- PostgreSQL 16 với extension `timescaledb` và `pgvector` đã sẵn sàng qua Docker (`docker-compose.yml`).
- Định dạng dữ liệu Google Trends Daily RSS duy trì cấu trúc XML chuẩn của Google Trends.
- YouTube Data API v3 yêu cầu API Key cấu hình qua biến môi trường `YOUTUBE_API_KEY`. Nếu không có key, plugin trả về trạng thái `is_healthy() == False` mà không làm crash ứng dụng.
