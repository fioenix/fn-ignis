# 📋 FN-IGNIS BACKLOG & SYSTEM STATUS

> **Cập nhật lần cuối:** 02/09/2026  
> **Phiên bản:** `v0.2.0`  
> **Kiến trúc:** Clean Architecture + Dual-Backend (Postgres TimescaleDB & Zero-Docker SQLite) + FastMCP Server (21 Handlers & Tools)  
> **Trạng thái Tests:** 81/81 unit & integration tests PASSED (100%) | Ruff Linter Clean


---

## 🚀 1. Hiện Trạng Hệ Thống Đã Hoàn Thành (Current Accomplishments)

### A. Hạ Tầng & Cơ Sở Dữ Liệu
- [x] **Supabase Cloud Pooler (Region ap-southeast-1):** Kết nối qua pooler endpoint `aws-0-ap-southeast-1.pooler.supabase.com:5432` với `psycopg_pool.AsyncConnectionPool`.
- [x] **Schema Bền Vững:** `research_missions`, `topic_clusters`, `trend_signals`, `system_audit_logs`, `platform_credentials`.
- [x] **Lightweight Worker Container:** Dockerfile tối ưu (~90MB, multi-stage uv build) chạy nền 24/7 trên OrbStack.

### B. Ingress Connectors & Authentication
- [x] **YouTube Data API v3:** 
  - Batch call `videos.list?part=snippet,statistics` để lấy lượt xem, likes, comments thật.
  - Tính tốc độ tăng trưởng thật: `velocity = views / hours_since_published`.
  - Bộ lọc thời gian: Áp dụng `publishedAfter` (RFC 3339) theo đúng timeframe yêu cầu (24h, 7d, 30d, 90d, 12m).
  - Bản địa hóa: Bộ lọc `relevanceLanguage="vi"` và `regionCode="VN"`.
- [x] **Google Trends RSS & Suggest API:** 
  - Dynamic interest score & traffic volume thật.
  - Lấy cụm từ khóa tìm kiếm liên quan (related queries) theo thời gian thực.
- [x] **TikTok 1-Click QR Code / Managed Browser Ingress:**
  - `TikTokAuthManager` với khả năng bắt tự động `storageState` (cookies, tokens) mà end-user không cần DevTools.
  - Hỗ trợ cào Trending và Tìm kiếm theo từ khóa (`search_signals`) bóc tách Play Count, Digg Count, Comment Count, Share Count thật.
  - Tool FastMCP: `authenticate_tiktok`, `get_platform_auth_status`, `clear_platform_auth`.
- [x] **Error Isolation & Observability:** Circuit Breaker độc lập cho từng kênh kết nối, tự động ghi vết sự cố vào bảng `system_audit_logs`.

### C. Agent Harness & Strategic Reasoning (4 Tầng)
- [x] **Tầng 1 - Autonomous Refinement Loop (`AutonomousRefinementOrchestrator`):** Tự động phát hiện dữ liệu mỏng hoặc độ tin cậy thấp để cào bổ sung đợt 2 (Pass 2) theo từ khóa phụ.
- [x] **Tầng 2 - Quality & Integrity Scorecard (`QualityEvaluator`):** Chấm điểm minh bạch Coverage, Language Precision, Data Freshness, Creator Diversity, và Overall Confidence.
- [x] **Tầng 3 - White Space Discovery (`StrategicMarketReasoner`):**
  - So sánh Nhu cầu tìm kiếm (Google Trends) vs Nguồn cung video tiếng Việt bản địa (YouTube/TikTok).
  - Bóc tách các phân khúc: `HIGH_DEMAND_LOW_SUPPLY`, `ENTERPRISE_GAP`, `SATURATED_SEGMENT`.
  - Đánh giá giai đoạn xu hướng (Trend Maturity Stage: `EMERGING`, `HYPING`, `MATURE`).
- [x] **Tầng 4 - Deterministic Artifact Builder:** Single-file HTML Report (Tailwind CSS Dark Mode) trực quan hóa Scorecard, Ma trận Cung-Cầu và Bằng chứng đa kênh.

### D. Tối Ưu Hóa Giao Tiếp & UX
- [x] **Token-Efficient Payload:** Giảm hơn 90% dung lượng response của `get_mission_analysis` (từ 111KB xuống 10KB), loại bỏ hoàn toàn lỗi `exceeds maximum allowed tokens`.
- [x] **Human-Friendly Shortcode:** Tự động sinh mã ngắn (ví dụ: `VN-AI-AGENT-90D-FB16` hoặc `FB16C5EE`) và hỗ trợ tra cứu linh hoạt 3 trong 1 (Shortcode, 8-char Prefix, UUID).
- [x] **Cross-Agent Session Tracing:** Lưu trữ trường `agent` (`claude_desktop`, `claude_code`, `codex`) và `session_id` (`codex://threads/...`). Tool `get_current_session_mission` tự động khôi phục ngữ cảnh làm việc mà không cần nhập lại ID.
- [x] **Đóng gói chuẩn Agent Skill:** File `.agents/skills/fn-ignis-harness/SKILL.md` hướng dẫn quy chuẩn giao tiếp cho Claude Code, Codex và Claude Desktop.

---

## 📌 2. Danh Mục Backlog Cho Các Session Tiếp Theo (Upcoming Roadmap)

### 🎯 Epic 1: Hoàn thiện Meta Ingress (Threads & Instagram Reels)
*Mục tiêu: Đưa Coverage Score lên 100% bằng cách kết nối Meta Ingress.*
- [ ] **Official Meta Threads OAuth 2.0 Ingress:** Tích hợp Threads Graph API OAuth với Long-Lived Token (60 ngày tự refresh).
- [ ] **Instagram Reels Ingress:** Bóc tách video ngắn Reels dựa trên session pool.

### 🎯 Epic 2: Multi-Language & Regional Expansion (SEA & Global)
*Mục tiêu: Mở rộng khả năng lắng nghe thị trường ngoài Việt Nam.*
- [ ] **Đa khu vực (Geo Expansion):** Bổ sung bộ lọc cho các thị trường Đông Nam Á (`TH`, `ID`, `MY`, `SG`, `PH`) và Toàn cầu (`US`, `GLOBAL`).
- [ ] **Cross-Language Semantic Alignment:** Đối chiếu các chủ đề đang bùng nổ tại thị trường US/Trung Quốc với tốc độ du nhập về Việt Nam (Time-Lag Arbitrage).

### 🎯 Epic 3: Live Alerts & Notification Webhooks
*Mục tiêu: Đẩy thông báo chủ động cho người dùng khi xu hướng bùng nổ.*
- [ ] **Breakout Trend Webhook:** Tự động gửi cảnh báo qua Slack / Telegram / Discord khi một topic cluster đạt `cross_platform_score >= 80.0` (Momentum: BREAKOUT).
- [ ] **Weekly Executive Digest:** Tự động chạy báo cáo tổng kết xu hướng hàng tuần và xuất bản trang HTML tĩnh.

### 🎯 Epic 4: Trend Velocity Forecasting (Dự Báo Tương Lai)
*Mục tiêu: Đo lường chu kỳ sống của xu hướng.*
- [ ] **Time-series Projection:** Sử dụng mô hình ARIMA / Exponential Smoothing trên chuỗi dữ liệu Google Trends để dự đoán thời điểm xu hướng chạm đỉnh (Peak Interest).
- [ ] **Saturation Index:** Tính toán ngưỡng bão hòa của thị trường dựa trên tốc độ ra mắt video mới của các nhà sáng tạo nội dung.

---

## 🛠️ 3. Hướng Dẫn Kích Hoạt Cho Session Mới

Khi mở session mới với bất kỳ Agent nào (Antigravity, Claude Code, Codex), chỉ cần truyền lệnh:

> *"Đọc file `BACKLOG.md` để nắm hiện trạng kiến trúc `fn-ignis` và bắt đầu triển khai [Tên tính năng trong Backlog]."*
