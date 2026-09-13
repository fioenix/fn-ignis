# fnIgnis 🔥 *(Mã dự án: fn-ignis)*

[![FINOLABS Project](https://img.shields.io/badge/FINOLABS-Open%20Source-orange.svg)](https://finolabs.io)
[![CI](https://github.com/fioenix/fn-ignis/actions/workflows/ci.yml/badge.svg)](https://github.com/fioenix/fn-ignis/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%20%7C%203.12-blue.svg)](https://www.python.org/downloads/)
[![MCP](https://img.shields.io/badge/MCP-Standard%20FastMCP-purple.svg)](https://modelcontextprotocol.io/)
[![Docker Ready](https://img.shields.io/badge/Docker-Worker%20Daemon-2496ED.svg)](https://www.docker.com/)

> **fnIgnis — Nền tảng Tự vận hành Lắng nghe Xu hướng & Khám phá Cơ hội Thị trường (Self-Hosted Market Intelligence Platform) phát triển bởi FINOLABS**
>
> 🌐 [English Version](README.md) · [Tài liệu Hướng dẫn Toàn diện](docs/USER_GUIDE.md)

`fnIgnis` (`fn-ignis`) là công cụ nghiên cứu chiến lược và lắng nghe thị trường hiệu năng cao, tự lưu trữ (self-hosted), được phát triển bởi **FINOLABS**. Nền tảng hỗ trợ các AI Agent (**Claude Desktop, Claude Code, Antigravity, OpenAI Codex, OpenClaw, Hermes, Pi Agent**) và các nhà hoạch định chiến lược phát hiện các khoảng trống thị trường (white spaces) giá trị cao trên Google Trends, YouTube, TikTok Creative Center, gợi ý tìm kiếm TikTok và bình luận thực tế của khách hàng (Voice of Customer) với **chi phí token cào $0**, công thức tính toán toán học chuẩn xác (**Opportunity Index**), tự động nạp từ điển ngành linh hoạt và kết xuất báo cáo HTML Infographic trực quan, sắc nét.

---

## 🌟 Điểm Nhấn Nổi Bật

- **⚡ Cào Dữ liệu Cục bộ $0 Token**: Thu thập, lọc và chuẩn hóa dữ liệu lớn cục bộ bằng các bộ parser Python xác định mà không làm hao tốn token API LLM đắt đỏ.
- **🏛️ Kiến trúc Dual-Track**: Kết hợp daemon radar nền chạy 24/7 (`fn-ignis-worker` — tùy chọn, chỉ dùng API chính thống) với các đợt nghiên cứu chiến lược chuyên sâu theo giả thuyết khi cần. Các kênh phải điều khiển browser thuộc track theo yêu cầu, chạy trên máy bạn với session của bạn — nhờ vậy image worker vẫn gọn, không cần Chromium.
- **📊 Chỉ số Cơ hội Toán học (Opportunity Index)**: Định lượng khoảng trống thị trường (+100 đến -100) bằng tương quan toán học giữa tốc độ tăng trưởng nhu cầu tìm kiếm vĩ mô và khối lượng cung cấp nội dung bản địa.
- **🧾 Evidence Ledger không mất dữ liệu**: Lưu một canonical source cho mỗi object bên ngoài, mọi
  observation thu thập bất biến, và đúng evidence mà từng mission đã dùng. Poll lặp không làm tăng
  giả source diversity; một source có thể tham gia nhiều mission và cluster mà không bị copy.
- **🗣️ Lắng nghe Khách hàng Thực tế (Voice of Customer)**: Cào và tổng hợp các rào cản mua hàng, thắc mắc về giá và nhu cầu chưa được đáp ứng trực tiếp từ phần bình luận video công khai.
- **🧠 Cơ chế Từ điển Động Tự trị (Dynamic Lexicon)**: Bảng từ vựng lưu trữ bền vững trên SQLite/PostgreSQL cho phép agent đăng ký tiếng lóng ngành, tên thương hiệu mới ngay trong quá trình chạy mà không cần sửa code.
- **🤖 Tương thích Toàn diện Hệ sinh thái Agent**: Hỗ trợ sẵn sàng out-of-the-box cho Claude (Desktop & Code), Antigravity, Codex, OpenClaw, Hermes và Pi Agent.

---

## 🏛️ Kiến trúc: Mô hình Song hành (Dual-Track Model)

<p align="center">
  <img src="docs/assets/architecture.png" alt="fn-ignis Kiến trúc Mô hình Song hành" width="100%">
</p>

Runtime persistence dùng một nguồn sự thật trên cả hai backend:

| Entity | Sở hữu |
|---|---|
| `sources` | Identity của object bên ngoài: đúng ba cột `id`, `platform`, `external_id` |
| `observations` | Một collection event: title, URL, metric, metadata, cluster membership, identity route và clock provenance |
| `mission_evidence` | Đúng observation mà từng research mission đã dùng |

`trend_signals` và `signal_metrics` chỉ còn là đầu vào migration lịch sử. Runtime không bao giờ ghi
vào chúng. Chỗ đọc duy nhất còn lại là guard của cluster pruner: cluster mà corpus legacy vẫn trỏ
tới thì chưa rỗng, xoá nó trước khi backfill sẽ cascade mất đúng những dòng backfill sắp đọc.
<p align="center">
  <small><em>Sơ đồ: Kiến trúc Tình báo Xu hướng & Nghiên cứu Thị trường Mô hình Song hành (<a href="docs/assets/architecture.svg">Vector SVG</a> · <a href="docs/assets/architecture.html">Bản HTML Độc lập</a>)</em></small>
</p>

---

## 🧭 Quy trình Vận hành Chuẩn 6 Bước (SOP)

Với chiến dịch nghiên cứu toàn diện, sáu bước dưới đây là workflow tham chiếu. Mọi FastMCP tool vẫn
gọi độc lập được; harness không ép câu hỏi ad-hoc phải chạy cả chuỗi.

```
Bước 1: Xác định Mục tiêu Nghiên cứu & Giả thuyết Cốt lõi
   ↓ (Đăng ký thuật ngữ/slang chuyên ngành vào DB qua register_domain_lexicon)
Bước 2: Quét Vĩ mô & Mở rộng Từ khóa Thực tế (Creative Center & Gợi ý Autocomplete)
   ↓ (Vòng phản hồi: Bổ sung từ khóa slang người dùng thực tế trước khi cào sâu)
Bước 3: Thu thập Đa nền tảng & Quality Gate (Lọc spam/nhiễu, Confidence >= 70%)
   ↓
Bước 4: Bóc tách Đơn nguồn qua 4 Lăng kính (Nhu cầu, Nguồn cung, Ý định, Tiếng nói Khách hàng)
   ↓
Bước 5: Tổng hợp Đa nguồn & Ma trận Opportunity Index (Xác định Khoảng trống Thị trường)
   ↓
Bước 6: Kết luận Chiến lược, Rào cản Gia nhập & Kế hoạch Kiểm chứng MVP (Kế hoạch 3-7 ngày + HTML Dashboard)
```

---

## 🤖 Tương thích Đa Nền tảng AI Agent

`fn-ignis` được thiết kế để tích hợp liền mạch với mọi nền tảng AI agent hiện đại:

| AI Agent / IDE | Cấu hình & Tiêu chuẩn | Khả năng Hỗ trợ |
|---|---|---|
| **Claude Desktop** | [`bundle/claude_desktop_config.json`](bundle/claude_desktop_config.json) | 39 FastMCP Tools, Prompts, Resources, tự động nạp 6 bước SOP |
| **Claude Code** | [`CLAUDE.md`](CLAUDE.md), [`.agents/skills/fn-ignis-harness/SKILL.md`](.agents/skills/fn-ignis-harness/SKILL.md) | Chuẩn Agent Skills, xuất Artifact HTML trực quan |
| **Antigravity / Gemini Code** | [`AGENTS.md`](AGENTS.md) + Agent Skills | Radar liên tục Dual-Track & nạp từ điển động |
| **OpenAI Codex** | [`.codex/instructions.md`](.codex/instructions.md), [`.codexrules`](.codexrules) | Duy trì ngữ cảnh phiên chat (`codex://threads/...`), Structured Tools |
| **OpenClaw** | [`openclaw.json`](openclaw.json), [`.openclaw/config.yaml`](.openclaw/config.yaml) | Chuẩn OpenClaw Plugin v1 với Lifecycle Hooks |
| **Nous Hermes** | [`.hermes/tools.json`](.hermes/tools.json), [`hermes_manifest.json`](hermes_manifest.json) | Định dạng Function-Calling JSON Schema tiêu chuẩn |
| **Pi Agent** | [`openclaw.json`](openclaw.json), [`hermes_manifest.json`](hermes_manifest.json) | Tiêu chuẩn OpenAPI & Tool-Calling qua FastMCP hoặc Manifest |

---

## 📡 Ma trận Nguồn Dữ liệu & Công cụ FastMCP Liên kết

| Nguồn Dữ liệu | Tín hiệu Thu thập | Cơ chế Ingress | Công cụ FastMCP Liên kết |
| :--- | :--- | :--- | :--- |
| **Meta Threads** | • Chủ đề thịnh hành (Trending Topics) trên `threads.net/search`<br>• Từ khóa gợi ý tìm kiếm (Autocomplete Suggestions)<br>• Bài viết văn bản, captions & thông tin tác giả<br>• Tương tác (lượt thích, phản hồi, chia sẻ lại, trích dẫn, lượt xem) | • **Tier 1 (Mặc định)**: Direct GraphQL qua `httpx` dùng session cookies + Tự phục hồi qua Playwright tự động sniff `doc_id`<br>• **Tier 2**: Graph API OAuth 2.0 (`/keyword_search`, `/me/threads`) | • `authenticate_threads`<br>• `get_threads_auth_status`<br>• `clear_threads_auth`<br>• `get_threads_trending_topics`<br>• `get_threads_search_suggestions` |
| **TikTok** | • Xếp hạng ngành vĩ mô (Creative Center)<br>• Từ khóa tìm kiếm gợi ý (Autocomplete Suggestions)<br>• Thẻ video (lượt xem, lượt thích, chia sẻ, hashtags)<br>• Bình luận công khai & phản hồi từ khách hàng | • **Tier 1**: Playwright Chromium (bắt phiên đăng nhập 1 chạm qua mã QR)<br>• **Public Probe**: API Creative Center & endpoints tìm kiếm | • `authenticate_tiktok`<br>• `get_platform_auth_status`<br>• `clear_platform_auth`<br>• `get_tiktok_creative_center_trends`<br>• `get_tiktok_search_suggestions`<br>• `get_tiktok_video_comments`<br>• `extract_customer_pain_points` |
| **YouTube** | • Video chuyên sâu dạng dài (hướng dẫn, nghiên cứu tình huống)<br>• Khối lượng nội dung đối thủ & độ sâu bài học<br>• Lượt xem, lượt thích và số lượng bình luận | • **API v3 Chính thức**: Khóa Google Cloud API Key kèm bộ đệm in-memory TTL | Được kích hoạt trong các chiến dịch nghiên cứu: `create_research_mission`, `execute_mission_ingress`, `trigger_autonomous_discovery` |
| **Google Trends** | • Tốc độ tăng trưởng khối lượng tìm kiếm vĩ mô<br>• Từ khóa đột phá (rising queries) & mức độ quan tâm theo khu vực | • **RSS / Atom Ingress**: Phân tích nguồn cấp dữ liệu công khai (không tốn token) | Được kích hoạt trong chu kỳ nạp dữ liệu: `trigger_ingress_refresh`, `trigger_autonomous_discovery`, `execute_mission_ingress` |
| **Meta Instagram** | • Thước phim ngắn Reels (captions, âm thanh, hashtags)<br>• Lượt xem, lượt thích, thời gian đăng tải | • **Tier 1**: Bắt phiên đăng nhập qua Playwright Chromium<br>• **Tier 2**: Instagram Graph API OAuth 2.0 | • `authenticate_instagram`<br>• `get_instagram_auth_status`<br>• `clear_instagram_auth` |

---

## 🛠️ Danh mục 39 FastMCP Tools, Prompts & Resources

### 1. Nghiên cứu Thị trường & Tổng hợp Chiến lược
- **`run_autonomous_research_mission(topic, keywords, geo, timeframe, min_signals)`**: Khởi tạo chiến dịch, thu thập dữ liệu đa nguồn, tính toán Opportunity Index và xuất báo cáo trong 1 bước.
- **`create_research_mission(title, keywords, geo, timeframe, hypothesis)`**: Tạo chiến dịch nghiên cứu mới kèm giả thuyết cần kiểm chứng.
- **`execute_mission_ingress(mission_id)`**: Thực thi cào dữ liệu chuyên sâu và chấm điểm Quality Scorecard.
- **`evaluate_mission_quality(mission_id)`**: Đánh giá lại chất lượng dữ liệu (Coverage, Precision, Freshness, Diversity).
- **`discover_market_opportunities(mission_id)`**: Phát hiện các khoảng trống thị trường tiềm năng cao.
- **`get_mission_analysis(mission_id)`**: Trích xuất toàn văn báo cáo phân tích chiến lược tổng hợp.
- **`generate_mission_artifact(mission_id)`**: Xuất bản file HTML Dashboard Infographic tương tác trực quan vào thư mục `reports/`.
- **`list_research_missions(limit)`**: Liệt kê các chiến dịch nghiên cứu đã thực hiện.
- **`get_current_session_mission(session_id)`**: Khôi phục chiến dịch gắn với phiên chat hiện tại.
- **`trigger_autonomous_discovery(geo)`**: Kích hoạt chu kỳ tự động quét xu hướng toàn quốc.
- **`get_latest_daily_discovery(geo)`**: Lấy bản tin tổng hợp cơ hội thị trường hàng ngày mới nhất.

### 2. Lắng nghe Xã hội, Threads & Tiếng nói Khách hàng (Voice of Customer)
- **`get_threads_trending_topics(geo, limit)`**: Lấy danh sách các chủ đề thịnh hành thời gian thực từ trang tìm kiếm Threads (`threads.net/search`).
- **`get_threads_search_suggestions(keyword, geo, limit)`**: Lấy từ khóa gợi ý tìm kiếm (autocomplete) và các truy vấn phát sinh từ Threads.
- **`get_tiktok_creative_center_trends(geo, period, limit, industry)`**: Lấy xếp hạng xu hướng chính thức từ TikTok Creative Center có lọc theo ngành hàng.
- **`get_tiktok_search_suggestions(keywords, geo)`**: Lấy từ khóa gợi ý tìm kiếm (autocomplete) thực tế của người dùng.
- **`get_tiktok_video_comments(video_url, limit)`**: Cào bình luận công khai từ một video TikTok cụ thể.
- **`extract_customer_pain_points(keywords, geo, max_videos, inquiry_patterns)`**: Bóc tách phản đối mua hàng, câu hỏi về giá và nhu cầu chưa được đáp ứng từ bình luận.

### 3. Từ điển Động, Cấu hình Runtime & Chẩn đoán Hạ tầng
- **`get_runtime_config(key, category)`**: Tra cứu tham số cấu hình động (`threads_web_client_id`, `threads_graphql_endpoint`, `doc_id`) từ DB và RAM cache.
- **`update_runtime_config(key, value, category, description)`**: Cho phép AI Agent tự động cập nhật tham số giao thức khi client thay đổi build version.
- **`refresh_runtime_config_cache()`**: Xóa và nạp lại toàn bộ cấu hình động từ database vào in-memory cache siêu tốc (~0.01ms).
- **`register_domain_lexicon(domain, terms, category)`**: Đăng ký từ khóa/slang chuyên ngành vào cơ sở dữ liệu.
- **`register_noise_blacklist(terms)`**: Đăng ký từ khóa rác/spam cần loại bỏ.
- **`list_domain_lexicons(domain)`**: Tra cứu từ điển chuyên ngành đang hoạt động.
- **`diagnose_system_health()`**: Kiểm tra telemetry và trạng thái toàn bộ thành phần hệ thống.
- **`get_system_logs(limit, level)`**: Tra cứu nhật ký sự kiện kiểm toán hệ thống.
- **`verify_connectors_health()`**: Chạy kiểm tra tự động trạng thái YouTube API, Google RSS, Playwright, DB pool và Proxy.
- **`authenticate_tiktok()`**, **`get_platform_auth_status()`**, **`clear_platform_auth()`**: Quản lý phiên đăng nhập trình duyệt có mã hóa Fernet (256-bit key: AES-128-CBC + HMAC-SHA256).
- **`authenticate_threads(auth_code?, client_id?, client_secret?, redirect_uri?, browser_login?)`**: Kết nối Meta theo mô hình Dual-UX. Gọi mà không truyền `auth_code` (hoặc đặt `browser_login=true`) sẽ chạy luồng Tier 1 — bắt phiên trình duyệt 1 chạm bằng tài khoản cá nhân thông thường, không cần Meta Developer App. Khi truyền `auth_code`, hệ thống chạy luồng Tier 2 OAuth 2.0 Graph API (authorization code → short-lived token → long-lived user token 60 ngày), lưu trữ mã hóa AES.
- **`get_threads_auth_status()`**: Kiểm tra cả hai tier — trạng thái token, scopes, `key_version`, số ngày còn lại, có cần refresh hay không, kèm thông tin phiên trình duyệt đã bắt được.
- **`clear_threads_auth()`**: Thu hồi và xóa credentials OAuth cùng phiên trình duyệt của Threads khỏi bộ lưu trữ mã hóa.
- **`authenticate_instagram(auth_code?, client_id?, client_secret?, redirect_uri?, browser_login?)`**: Luồng kết nối Dual-UX tương tự cho Instagram, phục vụ ingress Reels.
- **`get_instagram_auth_status()`**: Kiểm tra credentials Instagram đang lưu trên cả hai tier.
- **`clear_instagram_auth()`**: Thu hồi và xóa credentials OAuth cùng phiên trình duyệt của Instagram.
- **`get_trending_topics(geo, timeframe, limit)`**, **`get_topic_detail(topic_id)`**, **`generate_trend_artifact(topic_id, geo, format)`**, **`trigger_ingress_refresh(geo, scope)`**: Khám phá xu hướng thời gian thực.

### 4. FastMCP Native Resources & Prompts
- **Resources**: `fn-ignis://sop/market-research`, `fn-ignis://methodology/opportunity-index`
- **Prompts**: `market_research_pipeline`, `voice_of_customer_audit`

---

## 📊 Báo cáo Nghiên cứu Thực tế Mẫu

Xem các báo cáo tương tác mẫu do `fn-ignis` kết xuất trong [`examples/case-studies/`](examples/case-studies/) — báo cáo chạy tại máy sẽ nằm ở thư mục `reports/` (không đưa vào git):

| Chiến dịch / Hồ sơ | Phạm vi & Trọng tâm | Điểm nổi bật & Khoảng trống Phát hiện | Báo cáo Trực tiếp |
|---|---|---|:---:|
| **`[VN-AI-AGENT-90D]`** | AI Agents & CSKH Tự Động tại Việt Nam | Nhu cầu lớn về bot chăm sóc khách hàng; khoảng trống lớn ở mảng tích hợp chuyên sâu cho doanh nghiệp so với nội dung hướng dẫn đại trà. | [Xem Dossier HTML](examples/case-studies/case_study_ai_agents_vn.html) |
| **`[VN-LINEN-FASHION-30D]`** | Thời trang, Vải Linen & Local Brand | Nhu cầu tìm kiếm đồ linen công sở tối giản tăng vọt theo mùa; thiếu hụt nguồn cung sơ mi linen phom rộng cao cấp. | [Xem Dossier HTML](examples/case-studies/case_study_linen_fashion_vn.html) |
| **`[VN-TIKTOK-SHOP-30D]`** | Công cụ TikTok Shop & Livestream Automation | Nhu cầu cao về chốt đơn tự động và đồng bộ kho livestream; mật độ câu hỏi về giá và chiết khấu rất dày đặc. | [Xem Dossier HTML](examples/case-studies/case_study_tiktok_shop_automation_vn.html) |

---

## ⚡ Cài đặt & Bắt đầu Nhanh

### 🤖 1. Cài đặt Tự động 1-Lệnh cho AI Agent (Khuyến nghị)
Nếu bạn là AI Agent (**Claude Code, Antigravity, OpenAI Codex, OpenClaw, Hermes, Pi Agent**) hoặc muốn cài đặt tự động 1 lệnh trên máy:
```bash
git clone https://github.com/fioenix/fn-ignis.git && cd fn-ignis
./scripts/bootstrap.sh
```
*Script sẽ tự động khởi tạo môi trường Python virtualenv, SQLite database, sinh file `.env` với khóa bảo mật Fernet (256-bit key: AES-128-CBC + HMAC-SHA256), tự động đăng ký FastMCP vào Claude Desktop, Antigravity, Codex và chạy kiểm tra hệ thống.*

---

### 2. Cài đặt Thủ công Cục bộ Zero-Docker (SQLite)
Chạy `fn-ignis` trên máy cá nhân **không cần cài đặt Docker hay PostgreSQL**:
```bash
# 1. Clone repo & khởi tạo virtual environment
git clone https://github.com/fioenix/fn-ignis.git && cd fn-ignis
uv venv && source .venv/bin/activate && uv pip install -e .

# 2. Khởi chạy FastMCP Server trực tiếp (SQLite tự động khởi tạo)
ignis-mcp
```

### 3. Triển khai Trọn gói Production (Docker Compose)
Triển khai toàn bộ cụm doanh nghiệp (TimescaleDB + Worker Daemon Chạy ngầm + Nginx Web Portal xem báo cáo):
```bash
# Khởi chạy full stack
docker compose -f docker-compose.prod.yml up -d
```

> Installation PostgreSQL đã có corpus legacy trong `trend_signals` phải chạy
> [production cutover source/observation](docs/migrations/2026-09-10-source-observation-baseline.md#production-cutover-runbook).
> Sau khi apply `sql/016`, không khởi động runtime mới cho tới khi baseline sinh từ đúng snapshot,
> backfill và verifier trả `VERIFIED`.

---

## 📖 Cẩm nang Hướng dẫn Chi tiết (User Guide)

Để xem hướng dẫn cài đặt từng bước, code mẫu tích hợp Python scripting, vận hành Docker và xử lý sự cố thường gặp, vui lòng tham khảo **[Cẩm nang Hướng dẫn Sử dụng Thủ công (docs/USER_GUIDE.md)](docs/USER_GUIDE.md)**.

---

## ⚙️ Biến Môi trường (.env)

| Tên biến | Mô tả | Mặc định | Bắt buộc |
|---|---|---|:---:|
| `DATABASE_URL` | Chuỗi kết nối SQLite (`sqlite:///ignis.db`) hoặc PostgreSQL/TimescaleDB | `sqlite:///ignis.db` | **Có** |
| `YOUTUBE_API_KEY` | Google Cloud YouTube Data API v3 Key | `""` | Tùy chọn |
| `DEFAULT_GEO` | Mã quốc gia ISO mặc định cho nghiên cứu xu hướng | `VN` | Không |
| `SCHEDULER_INTERVAL_SECONDS` | Nhịp chạy ingress của worker, tính bằng giây. Mặc định suy ra từ quota YouTube: 10 từ khoá x 100 unit nên một ngày chỉ đủ 10 lượt | `8640` (~2,4 giờ) | Không |
| `DISCOVERY_INTERVAL_HOURS` | Khoảng cách giữa các đợt tự động quét toàn diện (giờ) | `24` (hàng ngày) | Không |
| `SYNC_INTERVAL_MINUTES` | Tùy chọn ghi đè chu kỳ đồng bộ ingress (phút; 0 = dùng SCHEDULER_INTERVAL_SECONDS) | `0` | Không |
| `YOUTUBE_CACHE_TTL_SECONDS` | Thời gian cache kết quả tìm kiếm YouTube để bảo vệ quota API | `86400` (24h) | Không |
| `PLAYWRIGHT_PROXY_SERVER` | Proxy HTTP/SOCKS tùy chọn khi cào dữ liệu qua Playwright | `""` | Không |
| `IGNIS_ENCRYPTION_KEY` | Khóa Fernet (256-bit key: AES-128-CBC + HMAC-SHA256) mã hóa cookie phiên đăng nhập | *(Tự sinh)* | Không |

---

## 🧪 Kiểm thử & Xác thực

Chạy bộ test suite với 100% async coverage (91 kiểm thử tự động):
```bash
uv run pytest
```

---

## 🛡️ Bảo mật & Quyền riêng tư

- **Không rò rỉ dữ liệu (Zero Data Leakage)**: Toàn bộ dữ liệu cào thô được phân tích và bóc tách cục bộ. Không gửi dữ liệu thô ra các mô hình LLM bên thứ ba trừ khi agent được chỉ định rõ ràng.
- **Mã hóa Fernet**: Trạng thái phiên trình duyệt và thông tin xác thực được mã hóa an toàn bằng Fernet (AES-128-CBC + HMAC-SHA256, 256-bit key).
- **Truy vấn SQL tham số hóa**: Tất cả truy vấn cơ sở dữ liệu sử dụng parameterized query để chống tấn công SQL Injection.
- Báo cáo lỗ hổng bảo mật: Xem chi tiết tại [Chính sách Bảo mật (SECURITY.md)](SECURITY.md).

---

## 🤝 Đóng góp & Phát triển Cộng đồng

Chúng tôi luôn hoan nghênh sự đóng góp từ cộng đồng mã nguồn mở! Vui lòng tham khảo [Quy định Đóng góp (CONTRIBUTING.md)](CONTRIBUTING.md) và [Bộ Quy tắc Ứng xử (CODE_OF_CONDUCT.md)](CODE_OF_CONDUCT.md) trước khi tạo pull request.

---

## 📄 Giấy phép Bản quyền (License)

Dự án được phân phối dưới giấy phép **MIT License**. Xem chi tiết tại tệp [`LICENSE`](LICENSE).
