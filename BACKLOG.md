# 📋 FN-IGNIS BACKLOG & SYSTEM STATUS

> **Cập nhật lần cuối:** 03/09/2026  
> **Phiên bản:** `v0.3.5`  
> **Kiến trúc:** Clean Architecture + Dual-Backend (Postgres TimescaleDB & Zero-Docker SQLite) + FastMCP Server (34 Handlers & Tools)  
> **Trạng thái Tests:** 147/147 unit & integration tests PASSED (100%) | Ruff Linter Clean


---

## 🚀 1. Hiện Trạng Hệ Thống Đã Hoàn Thành (Current Accomplishments)

### A. Hạ Tầng & Cơ Sở Dữ Liệu
- [x] **Supabase Cloud Pooler (Region ap-southeast-1):** Kết nối qua pooler endpoint `aws-0-ap-southeast-1.pooler.supabase.com:5432` với `psycopg_pool.AsyncConnectionPool`.
- [x] **Schema Bền Vững:** `research_missions`, `topic_clusters`, `trend_signals`, `system_audit_logs`, `platform_credentials`.
- [x] **Lightweight Worker Container:** Dockerfile tối ưu (~90MB, multi-stage uv build) chạy nền 24/7 trên OrbStack.
- [x] **Credentials Hardening:** `CryptoService` áp dụng Fernet AES-128-CBC + HMAC-SHA256, có fail-fast (`assert_persistent_key`) và hỗ trợ `key_version` ("v1") sẵn sàng cho key rotation.

### B. Ingress Connectors & Authentication
- [x] **YouTube Data API v3:** 
  - Batch call `videos.list?part=snippet,statistics` lấy views, likes, comments thật.
  - Tốc độ tăng trưởng thật: `velocity = views / hours_since_published`.
  - Bộ lọc thời gian: Áp dụng `publishedAfter` (RFC 3339) theo timeframe yêu cầu.
  - Bản địa hóa: Bộ lọc `relevanceLanguage` và `regionCode`.
- [x] **Google Trends RSS & Suggest API:** 
  - Dynamic interest score & traffic volume thật, lấy cụm từ khóa tìm kiếm liên quan theo thời gian thực.
- [x] **TikTok Ingress & Creative Center:**
  - `TikTokAuthManager` với khả năng bắt tự động `storageState` (cookies, tokens) mà end-user không cần DevTools.
  - Hỗ trợ cào Trending và Tìm kiếm theo từ khóa (`search_signals`) bóc tách Play Count, Digg Count, Comment Count, Share Count thật.
  - Tích hợp TikTok Creative Center Macro Trends (`get_tiktok_creative_center_trends`).
- [x] **Meta Threads Graph API (OAuth 2.0 - Epic 1 Hoàn Tất trong v0.2.0):**
  - Tích hợp Threads Graph API OAuth với luồng đổi Long-Lived Token (60 ngày).
  - Tự động refresh token khi còn $\le 10$ ngày mà không làm gián đoạn hệ thống.
  - FastMCP Tools: `authenticate_threads`, `get_threads_auth_status`, `clear_threads_auth`.
- [x] **Instagram Reels Ingress (Graph API - Epic 1 Hoàn Tất trong v0.2.0):**
  - `ReelsPlugin` hỗ trợ bóc tách qua `ig_hashtag_search` $\rightarrow$ `top_media`, lọc `media_product_type == "REELS"`.
  - Bóc tách play_count, like_count, comment_count, caption, published_at.
- [x] **Error Isolation & Observability:** Circuit Breaker độc lập cho từng kênh kết nối, phân loại lỗi 401/403/429 chuẩn mực.

### C. Agent Harness & Multi-Region Quality Evaluation
- [x] **Autonomous Refinement Loop (`AutonomousRefinementOrchestrator`):** Tự động phát hiện dữ liệu mỏng hoặc độ tin cậy thấp để cào bổ sung đợt 2 (Pass 2) theo từ khóa phụ.
- [x] **ILanguageDetector & Subtractive Filtering:** Nhận diện ngôn ngữ chuẩn xác không dùng rubber-stamp:
  - Hỗ trợ 6 vùng: `VN`, `US`, `JP`, `KR`, `TH`, `BR`.
  - Cơ chế Subtractive Filtering: Chấp nhận 100% tiêu đề công nghệ chứa tên thương hiệu (`n8n Zapier Make Comparison`, `Kubernetes Helm Terraform DevOps`), từ chối triệt để ký tự ngoại ngữ, CJK không có Kana ở Nhật, tiếng Việt ở Brazil, và chuỗi rác vô nghĩa.
  - Dynamic Lexicon whitelist (`register_domain_lexicon`) và noise blacklist (`register_noise_blacklist`).
- [x] **White Space Discovery (`StrategicMarketReasoner`):**
  - So sánh Nhu cầu tìm kiếm vs Nguồn cung video/thảo luận.
  - Bóc tách các phân khúc: `HIGH_DEMAND_LOW_SUPPLY`, `ENTERPRISE_GAP`, `SATURATED_SEGMENT`.
  - Đánh giá giai đoạn xu hướng (Trend Maturity Stage: `EMERGING`, `HYPING`, `MATURE`).
- [x] **Deterministic Artifact Builder:** Single-file HTML Report (Tailwind CSS) trực quan hóa Scorecard, Ma trận Cung-Cầu và Bằng chứng đa kênh.

### D. Tối Ưu Hóa Giao Tiếp & FastMCP Catalog
- [x] **Danh mục 31 FastMCP Tools:** Hoàn thiện và đồng bộ đối xứng giữa `server.py`, `openclaw.json`, `hermes_manifest.json`, `.hermes/tools.json` và `setup_bundle.py`.
- [x] **Cross-Agent Session Tracing:** Lưu trữ trường `agent` và `session_id`. Tool `get_current_session_mission` tự động khôi phục ngữ cảnh làm việc mà không cần nhập lại ID.
- [x] **Tài liệu Tích hợp Meta Dedicated:** [docs/META_INTEGRATION_GUIDE.md](docs/META_INTEGRATION_GUIDE.md) định nghĩa toàn diện mô hình Dual-UX và kịch bản tự động hóa cho AI Agent.

---

## 📌 2. Danh Mục Backlog Cho Các Session Tiếp Theo (Upcoming Roadmap)

### ✅ Epic 1.5: Dual-UX Meta Ingress & Instagram Parity (Đã hoàn thành)
*Mục tiêu: Đạt tỷ lệ kích hoạt 100% cho cả người dùng phổ thông (Non-tech) lẫn chuyên gia (Tech-heavy).*
- [x] **Tier 1 (Non-Tech) 1-Click Browser Session Capture:** Bổ sung luồng Playwright browser login cho Threads và Instagram tương tự `authenticate_tiktok()`, cho phép người dùng phổ thông đăng nhập bằng tài khoản cá nhân thông thường để quét dữ liệu công khai (public search, hashtags) mà không cần Meta Developer Portal.
- [x] **FastMCP Instagram Tools Parity:** Bổ sung 3 công cụ FastMCP:
  - `authenticate_instagram(auth_code, client_id, client_secret, redirect_uri)` — hợp nhất luôn cả luồng `browser_login` của Tier 1
  - `get_instagram_auth_status()`
  - `clear_instagram_auth()`
- [x] **Insights TTL Caching (2 giờ):** Caching in-memory cho post metrics của Threads/Reels để giải quyết triệt để bài toán N+1 request và bảo vệ hạn mức 200 reqs/user/hour của Meta Graph API.
- [x] **Registry Multi-Plugin Coexistence (Tech Debt):** Đảm bảo `TikTokPlugin` (Search Video Grid & Comments) và `TikTokCreativeCenterPlugin` (Macro Trends Radar) cùng tồn tại song song trong `ConnectorPluginRegistry` mà không bị ghi đè.

### 🎯 Epic 2: Data Provenance, Ingress Health Audit & Citation Attribution Engine (Sprint Ready)
*Mục tiêu: Xóa bỏ nhận định mơ hồ và ảo giác; minh bạch hóa nguồn gốc dữ liệu (Data Provenance) và phát hiện kênh ingress bị rỗng/lỗi.*
- [ ] **Channel Ingress & Health Summary Table:** Tổng hợp trạng thái (`HEALTHY`, `EMPTY_NO_DATA`, `AUTH_REQUIRED`, `RATE_LIMITED`) và số lượng tín hiệu của từng kênh kết nối (Google Trends, YouTube, TikTok Video Grid, TikTok Comments, Threads, Instagram Reels), đính kèm mẫu tín hiệu tiêu biểu.
- [ ] **Citation Attribution Engine:** Tự động gắn thẻ dẫn chứng cụ thể (`CitationEvidence`: platform, title, metrics, author, excerpt) vào từng `StrategicInsight`, `MarketOpportunity` và `ActionableTakeaway`.
- [ ] **HTML Dashboard Visualization:** Trực quan hóa Bảng Kiểm Toán Kênh Dữ Liệu (Ingress Audit Table) và các huy hiệu Citation Badges (Pill Badges) trong báo cáo HTML.
- [ ] **FastMCP & Agent Reporting Protocol:** Cập nhật payload `get_mission_analysis` và chuẩn hóa quy trình xuất báo cáo bắt buộc có bảng audit và inline citations theo [docs/DATA_PROVENANCE_AND_CITATION_SPEC.md](docs/DATA_PROVENANCE_AND_CITATION_SPEC.md).

### 🎯 Epic 3: Live Alerts & Notification Webhooks
*Mục tiêu: Đẩy thông báo chủ động cho người dùng khi xu hướng bùng nổ.*
- [ ] **Persisted Discovery State:** Lưu trữ `last_discovery_time` vào cơ sở dữ liệu thay vì biến in-memory, tránh tình trạng khởi động lại daemon worker gửi lại toàn bộ alert cũ.
- [ ] **Webhook Deliveries & Idempotency:** Thiết kế bảng `webhook_deliveries` với dedup key duy nhất (`topic_id` + `alert_type` + `date`) và pipeline retry/backoff.
- [ ] **Breakout Trend Webhook:** Tự động gửi cảnh báo qua Slack / Telegram / Discord khi một topic cluster đạt `cross_platform_score >= 80.0` (Momentum: BREAKOUT).
- [ ] **Weekly Executive Digest:** Tự động chạy báo cáo tổng kết xu hướng hàng tuần và xuất bản trang HTML tĩnh.

### 🎯 Epic 2: Multi-Language & Regional Expansion (SEA & Global)
*Mục tiêu: Mở rộng khả năng lắng nghe thị trường ngoài Việt Nam.*
- [ ] **Đa khu vực (Geo Expansion):** Mở rộng bộ phân tích cho các thị trường Đông Nam Á (`TH`, `ID`, `MY`, `SG`, `PH`) và Toàn cầu (`US`, `GLOBAL`).
- [ ] **Cross-Language Semantic Alignment:** Đối chiếu các chủ đề đang bùng nổ tại thị trường US/Trung Quốc với tốc độ du nhập về Việt Nam (Time-Lag Arbitrage).

### 🎯 Epic 4: Trend Velocity Forecasting (Dự Báo Tương Lai)
*Mục tiêu: Đo lường chu kỳ sống của xu hướng.*
- [ ] **Time-series Projection:** Sử dụng mô hình ARIMA / Exponential Smoothing trên chuỗi dữ liệu Google Trends để dự đoán thời điểm xu hướng chạm đỉnh (Peak Interest).
- [ ] **Saturation Index:** Tính toán ngưỡng bão hòa của thị trường dựa trên tốc độ ra mắt video mới của các nhà sáng tạo nội dung.

---

## 🛠️ 3. Hướng Dẫn Kích Hoạt Cho Session Mới

Khi mở session mới với bất kỳ Agent nào (Antigravity, Claude Code, Codex), chỉ cần truyền lệnh:

> *"Đọc file `BACKLOG.md` để nắm hiện trạng kiến trúc `fn-ignis` và bắt đầu triển khai [Tên tính năng trong Backlog]."*
