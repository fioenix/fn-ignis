# fnIgnis 🔥 — Cẩm nang Hướng dẫn Cài đặt, Cấu hình & Sử dụng Thủ công (User Guide)

Tài liệu này cung cấp hướng dẫn đầy đủ, chi tiết từng bước cho người dùng (developers, data analysts, product strategists) muốn tự tay cài đặt, cấu hình các biến môi trường và sử dụng `fn-ignis` thủ công (không bắt buộc qua AI Agent).

---

## 📑 Mục lục

1. [Tổng quan Kiến trúc](#1-tổng-quan-kiến-trúc)
2. [Các Chế độ Cài đặt Thủ công](#2-các-chế-độ-cài-đặt-thủ-công)
   - [Chế độ 1: Zero-Docker Local Mode (SQLite)](#chế-độ-1-zero-docker-local-mode-sqlite)
   - [Chế độ 2: Production Self-Hosted Stack (Docker Compose)](#chế-độ-2-production-self-hosted-stack-docker-compose)
   - [Chế độ 3: Cấu hình MCP Server thủ công cho IDE / Desktop App](#chế-độ-3-cấu-hình-mcp-server-thủ-công-cho-ide--desktop-app)
3. [Chi tiết Biến Môi trường & Cấu hình](#3-chi-tiết-biến-môi-trường--cấu-hình)
4. [Sử dụng Thủ công qua Command Line (CLI)](#4-sử-dụng-thủ-công-qua-command-line-cli)
5. [Sử dụng Thủ công qua Python Scripting](#5-sử-dụng-thủ-công-qua-python-scripting)
6. [Quản lý Báo cáo & Nginx Report Portal](#6-quản-lý-báo-cáo--nginx-report-portal)
7. [Xử lý Sự cố Thường gặp (Troubleshooting)](#7-xử-lý-sự-cố-thường-gặp-troubleshooting)
8. [Danh mục 28 FastMCP Tools & Khả năng Nghiên cứu Toàn diện](#8-danh-mục-28-fastmcp-tools--khả-năng-nghiên-cứu-toàn-diện)

---

## 1. Tổng quan Kiến trúc

`fn-ignis` được thiết kế theo mô hình **Dual-Track**:

- **Track 1 (Continuous Radar)**: Chạy nền 24/7 bằng daemon scheduler để thu thập dữ liệu macro từ Google Trends, YouTube và TikTok, tự động phát hiện xu hướng mới mỗi 12h-24h và ghi vào cơ sở dữ liệu.
- **Track 2 (On-Demand Deep Research)**: Chạy chủ động theo nhu cầu nghiên cứu từng chiến dịch cụ thể. Hệ thống sẽ cào gợi ý tìm kiếm (autocomplete), quét lưới video, bóc tách Voice-of-Customer từ bình luận, tính toán **Opportunity Index** (+100 đến -100) và xuất Dashboard HTML tương tác.

---

## 2. Các Chế độ Cài đặt Thủ công

### Chế độ 1: Zero-Docker Local Mode (SQLite)

Chế độ này phù hợp để chạy ngay trên máy tính cá nhân (macOS, Linux, Windows) mà **không cần cài đặt Docker hay PostgreSQL**. Toàn bộ dữ liệu được lưu tự động trong file `ignis.db`.

#### Bước 1: Yêu cầu môi trường
- Python $\ge 3.11$ (Khuyến nghị Python 3.11 hoặc 3.12).
- Trình quản lý gói `uv` (khuyên dùng để cài đặt siêu tốc) hoặc `pip` tiêu chuẩn.

#### Bước 2: Clone repository & Tạo Virtual Environment
```bash
# Clone source code
git clone https://github.com/fioenix/fn-ignis.git
cd fn-ignis

# Tạo và kích hoạt môi trường ảo bằng uv (khuyến nghị)
uv venv
source .venv/bin/activate    # Trên macOS/Linux
# Hoặc trên Windows PowerShell: .venv\Scripts\Activate.ps1

# Cài đặt package fn-ignis ở editable mode
uv pip install -e .
```

*(Nếu dùng pip thông thường: `python3 -m venv .venv && source .venv/bin/activate && pip install -e .`)*

#### Bước 3: Thiết lập file `.env`
Sao chép file mẫu:
```bash
cp .env.example .env
```
Mặc định `.env` đã được cấu hình `DATABASE_URL=sqlite:///ignis.db`. Bạn có thể điền thêm `YOUTUBE_API_KEY` nếu muốn thu thập dữ liệu YouTube.

#### Bước 4: Khởi tạo Database & Chạy thử
```bash
# Chạy script setup để tự sinh key mã hóa và khởi tạo bảng SQLite
ignis-setup

# Kiểm tra FastMCP server chạy thành công
ignis-mcp
```

---

### Chế độ 2: Production Self-Hosted Stack (Docker Compose)

Chế độ này triển khai toàn bộ hệ thống doanh nghiệp gồm:
1. **PostgreSQL / TimescaleDB (`fn-ignis-db`)**: Cơ sở dữ liệu chuỗi thời gian tối ưu cho hàng triệu tín hiệu social listening.
2. **Worker Daemon (`fn-ignis-worker`)**: Daemon chạy ngầm liên tục cào dữ liệu định kỳ mỗi 15 phút.
3. **Nginx Report Portal (`fn-ignis-reports`)**: Web server tĩnh phân phối các báo cáo HTML tại cổng `53080`.

#### Bước 1: Chuẩn bị file `.env`
```bash
cp .env.example .env
```
Chỉnh sửa `.env` cho chế độ Docker:
```env
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres
POSTGRES_DB=ignis
POSTGRES_PORT=5432
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/ignis
DEFAULT_GEO=VN
YOUTUBE_API_KEY=your_google_cloud_youtube_api_key_here
REPORTS_PORT=53080
```

#### Bước 2: Khởi chạy toàn bộ dịch vụ
```bash
# Khởi chạy full stack ở chế độ background
docker compose -f docker-compose.prod.yml up -d --build
```

#### Bước 3: Kiểm tra trạng thái
```bash
# Xem logs của worker daemon
docker compose -f docker-compose.prod.yml logs -f worker

# Kiểm tra các container đang chạy
docker compose -f docker-compose.prod.yml ps
```

Sau khi khởi chạy, bạn có thể mở trình duyệt truy cập `http://localhost:53080/` để xem danh sách các báo cáo HTML đã xuất bản.

---

### Chế độ 3: Cấu hình MCP Server thủ công cho IDE / Desktop App

Nếu bạn muốn kết nối `fn-ignis` làm công cụ FastMCP cho các ứng dụng AI Desktop:

#### 1. Cấu hình cho Claude Desktop
Mở file cấu hình Claude Desktop:
- **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`
- **Linux**: `~/.config/Claude/claude_desktop_config.json`

Thêm khối cấu hình:
```json
{
  "mcpServers": {
    "fn-ignis": {
      "command": "/ĐƯỜNG_DẪN_TUYỆT_ĐỐI/fn-ignis/.venv/bin/python",
      "args": ["-m", "ignis.interfaces.mcp.server"],
      "env": {
        "DATABASE_URL": "sqlite:////ĐƯỜNG_DẪN_TUYỆT_ĐỐI/fn-ignis/ignis.db",
        "DEFAULT_GEO": "VN",
        "YOUTUBE_API_KEY": ""
      }
    }
  }
}
```

#### 2. Cấu hình cho Cursor IDE
Tạo hoặc sửa file `.cursor/mcp.json` trong workspace của bạn:
```json
{
  "mcpServers": {
    "fn-ignis": {
      "command": "/ĐƯỜNG_DẪN_TUYỆT_ĐỐI/fn-ignis/.venv/bin/python",
      "args": ["-m", "ignis.interfaces.mcp.server"],
      "env": {
        "DATABASE_URL": "sqlite:////ĐƯỜNG_DẪN_TUYỆT_ĐỐI/fn-ignis/ignis.db",
        "DEFAULT_GEO": "VN"
      }
    }
  }
}
```

*(Mẹo: Bạn chỉ cần chạy lệnh `ignis-setup` hoặc `./scripts/bootstrap.sh`, hệ thống sẽ tự động điền đường dẫn chính xác vào các file trên).*

---

## 3. Chi tiết Biến Môi trường & Cấu hình

Tất cả các biến môi trường được định nghĩa trong file `.env`:

| Tên biến | Kiểu dữ liệu | Mặc định | Bắt buộc | Mục đích & Giải thích |
|---|---|---|:---:|---|
| `DATABASE_URL` | String | `sqlite:///ignis.db` | Có | URI kết nối database. Dùng `sqlite:///ignis.db` cho Zero-Docker hoặc `postgresql://user:pass@host:5432/db` cho Postgres/TimescaleDB. |
| `DEFAULT_GEO` | String (ISO) | `VN` | Không | Mã quốc gia 2 ký tự mặc định để quét xu hướng (`VN`, `US`, `JP`, `UK`,...). |
| `YOUTUBE_API_KEY` | String | `""` | Khuyến nghị | Key Google Cloud YouTube Data API v3 để cào video tutorials & case studies. |
| `IGNIS_ENCRYPTION_KEY` | Base64 String | *(Tự sinh)* | Không | Khóa Fernet AES-256 để mã hóa cookie/phiên đăng nhập TikTok lưu trong database. |
| `SCHEDULER_INTERVAL_SECONDS` | Integer | `900` (15m) | Không | Tần suất heartbeat kiểm tra trạng thái của worker daemon. |
| `DISCOVERY_INTERVAL_HOURS` | Integer | `24` | Không | Khoảng cách giữa các đợt tự động quét toàn diện Creative Center và phát hiện white space. |
| `SYNC_INTERVAL_MINUTES` | Integer | `60` | Không | Chu kỳ cào dữ liệu Google Trends RSS định kỳ. |
| `YOUTUBE_CACHE_TTL_SECONDS` | Integer | `86400` (24h) | Không | Thời gian lưu cache kết quả tìm kiếm YouTube để tiết kiệm quota 10,000 unit/ngày. |
| `PLAYWRIGHT_PROXY_SERVER` | String | `""` | Không | Proxy server HTTP/SOCKS5 (ví dụ: `http://user:pass@proxy.ip:port`) để cào TikTok không bị chặn. |
| `CONFIDENCE_HIGH_THRESHOLD` | Float | `80.0` | Không | Ngưỡng điểm để đánh giá chất lượng dữ liệu chiến dịch ở mức HIGH. |
| `CONFIDENCE_MEDIUM_THRESHOLD`| Float | `60.0` | Không | Ngưỡng điểm để đánh giá chất lượng dữ liệu chiến dịch ở mức MEDIUM. |

### Cách lấy `YOUTUBE_API_KEY` miễn phí:
1. Truy cập [Google Cloud Console](https://console.cloud.google.com/).
2. Tạo dự án mới (ví dụ: `fn-ignis-research`).
3. Vào **APIs & Services** $\rightarrow$ **Library** $\rightarrow$ Tìm `YouTube Data API v3` và bấm **Enable**.
4. Vào mục **Credentials** $\rightarrow$ **Create Credentials** $\rightarrow$ **API Key**.
5. Dán key vào `.env`: `YOUTUBE_API_KEY=AIzaSy...`

---

## 4. Sử dụng Thủ công qua Command Line (CLI)

`fn-ignis` cung cấp 3 lệnh CLI chính:

### 1. `ignis-setup`: Auto-provisioning & Cấu hình môi trường
```bash
# Chạy setup tự động và hiển thị báo cáo dạng Markdown
ignis-setup

# Chạy setup và xuất JSON (dành cho automation script)
ignis-setup --json
```

### 2. `ignis`: Kích hoạt Ingress thu thập xu hướng một lần (One-shot ETL)
```bash
# Thu thập xu hướng mới nhất tại Việt Nam (VN)
ignis VN

# Thu thập xu hướng tại thị trường Mỹ (US)
ignis US
```

### 3. `ignis-mcp`: Khởi động FastMCP Server
```bash
# Khởi chạy server trên cổng Standard I/O (Stdio)
ignis-mcp
```

---

## 5. Sử dụng Thủ công qua Python Scripting

Bạn có thể viết script Python độc lập để tích hợp `fn-ignis` vào hệ thống nội bộ của bạn:

### Ví dụ: Tạo chiến dịch nghiên cứu, cào dữ liệu và xuất HTML Report

Tạo file `run_research.py`:

```python
import asyncio
from uuid import uuid4
from ignis.config import settings
from ignis.domain.value_objects import GeoCode, Timeframe
from ignis.infrastructure.persistence import create_repository
from ignis.infrastructure.connectors.registry import ConnectorPluginRegistry
from ignis.infrastructure.connectors.google_trends.rss_plugin import GoogleTrendsRssPlugin
from ignis.infrastructure.connectors.youtube.youtube_plugin import YouTubeDataPlugin
from ignis.infrastructure.connectors.tiktok.creative_center_plugin import TikTokCreativeCenterPlugin
from ignis.application.use_cases.create_mission import CreateMissionUseCase
from ignis.application.use_cases.execute_mission import ExecuteMissionUseCase
from ignis.application.use_cases.get_mission_analysis import GetMissionAnalysisUseCase
from ignis.infrastructure.templates.html_builder import HtmlArtifactBuilder


async def main():
    # 1. Khởi tạo Repository (SQLite hoặc Postgres tùy cấu hình)
    repo = create_repository()
    
    # 2. Đăng ký các Connector Ingress
    registry = ConnectorPluginRegistry()
    registry.register(GoogleTrendsRssPlugin())
    registry.register(TikTokCreativeCenterPlugin())
    if settings.YOUTUBE_API_KEY:
        registry.register(YouTubeDataPlugin(api_key=settings.YOUTUBE_API_KEY))

    # 3. Tạo Chiến dịch Nghiên cứu mới
    create_uc = CreateMissionUseCase(repository=repo)
    mission = await create_uc.execute(
        title="AI Agent Chăm sóc Khách hàng tại Việt Nam",
        keywords=["ai agent", "cskh tự động", "chatbot bán hàng", "tự động hóa chốt đơn"],
        geo=GeoCode.VN,
        timeframe=Timeframe.LAST_30D,
        hypothesis="Thị trường có nhu cầu cao về bot CSKH nhưng thiếu giải pháp tích hợp sâu vào CRM nội địa."
    )
    print(f"✅ Đã tạo Mission ID: {mission.id}")

    # 4. Thực thi cào dữ liệu đa nền tảng
    execute_uc = ExecuteMissionUseCase(registry=registry, repository=repo)
    scorecard = await execute_uc.execute(mission_id=mission.id)
    print(f"📊 Chất lượng dữ liệu: {scorecard.confidence_level} ({scorecard.overall_score}/100)")

    # 5. Tổng hợp phân tích chiến lược & Opportunity Index
    analysis_uc = GetMissionAnalysisUseCase(repository=repo)
    analysis = await analysis_uc.execute(mission_id=mission.id)
    print("\n💡 Các cơ hội thị trường (White Spaces) phát hiện được:")
    for opp in analysis.get("opportunities", []):
        print(f"  • [{opp['category']}] {opp['title']} (Opportunity Index: {opp['opportunity_index']})")

    # 6. Xuất bản Interactive HTML Report Dashboard
    builder = HtmlArtifactBuilder()
    html_path = builder.build_mission_report(
        mission=mission,
        scorecard=scorecard,
        analysis=analysis,
        signals=await repo.get_mission_signals(mission.id)
    )
    print(f"\n🎉 Báo cáo HTML đã xuất ra: {html_path}")

    await repo.close()


if __name__ == "__main__":
    asyncio.run(main())
```

Chạy script:
```bash
uv run python run_research.py
```

---

## 6. Quản lý Báo cáo & Nginx Report Portal

Mọi báo cáo Infographic HTML sau khi tạo ra đều được lưu vĩnh viễn trong thư mục:
```
reports/mission_<shortcode>.html
```

### Xem báo cáo:
- **Cách 1 (Trực tiếp)**: Mở trực tiếp file HTML bằng bất kỳ trình duyệt nào:
  ```bash
  open reports/case_study_ai_agents_vn.html      # Trên macOS
  xdg-open reports/case_study_ai_agents_vn.html  # Trên Linux
  start reports/case_study_ai_agents_vn.html     # Trên Windows
  ```
- **Cách 2 (Nginx Web Portal trong Docker)**:
  Truy cập `http://localhost:53080/` để xem và chia sẻ báo cáo qua mạng nội bộ.

---

## 7. Xử lý Sự cố Thường gặp (Troubleshooting)

### 1. `YOUTUBE_API_KEY not configured`
- **Hiện tượng**: Log hiển thị cảnh báo `YOUTUBE_API_KEY not configured. Skipping YouTube Plugin.`
- **Khắc phục**: Đây chỉ là cảnh báo (warning). `fn-ignis` vẫn hoạt động bình thường với Google Trends và TikTok. Để lấy thêm tín hiệu YouTube, hãy cấu hình `YOUTUBE_API_KEY` vào file `.env`.

### 2. Lỗi `playwright not installed` khi cào chi tiết bình luận TikTok
- **Khắc phục**: Cài đặt browser binary cho Playwright:
  ```bash
  uv run playwright install chromium
  ```

### 3. Khôi phục / Reset Database SQLite
- Nếu muốn làm mới toàn bộ dữ liệu SQLite:
  ```bash
  rm -f ignis.db
  ignis-setup
  ```

### 4. Kiểm tra sức khỏe hệ thống (Health Check)
Chạy bộ test suite 85 kiểm thử tự động:
```bash
uv run pytest
```

---

## 8. Danh mục 28 FastMCP Tools & Khả năng Nghiên cứu Toàn diện

Khi FastMCP Server khởi chạy (`ignis-mcp`), 28 tools, 2 prompts và 2 resources sau đây luôn sẵn sàng cho AI Agents hoặc MCP clients:

### 1. Nhóm Chiến dịch & Nghiên cứu Chiến lược (Research & White Space)
| Tên Tool | Tham số chính | Chức năng & Giá trị đầu ra |
|---|---|---|
| `run_autonomous_research_mission` | `topic, keywords, geo, timeframe, min_signals` | Tạo mission, chạy ingress đa nền tảng, tính Opportunity Index và xuất dashboard trong 1 bước. |
| `create_research_mission` | `title, keywords, geo, timeframe, hypothesis` | Khởi tạo chiến dịch nghiên cứu mới với giả thuyết kiểm chứng. |
| `execute_mission_ingress` | `mission_id` | Thực thi cào dữ liệu đa nguồn và đánh giá Quality Scorecard (Confidence $\ge 70\%$). |
| `evaluate_mission_quality` | `mission_id` | Đánh giá lại 4 chiều chất lượng dữ liệu (Coverage, Language, Freshness, Diversity). |
| `discover_market_opportunities` | `mission_id` | Khám phá các khoảng trống thị trường (Unserved White Spaces) và xếp hạng tiềm năng. |
| `get_mission_analysis` | `mission_id` | Trích xuất phân tích chiến lược tổng hợp (cung/cầu, Opportunity Index, rào cản gia nhập, kế hoạch MVP). |
| `generate_mission_artifact` | `mission_id` | Xuất bản file HTML Dashboard Infographic tương tác trực quan vào thư mục `reports/`. |
| `list_research_missions` | `limit` | Liệt kê lịch sử các chiến dịch nghiên cứu đã thực hiện. |
| `get_current_session_mission` | `session_id` | Khôi phục ngữ cảnh chiến dịch gắn với phiên chat của agent. |
| `trigger_autonomous_discovery` | `geo` | Kích hoạt chu kỳ tự động phát hiện xu hướng và tổng hợp cơ hội trên toàn quốc gia. |
| `get_latest_daily_discovery` | `geo` | Lấy bản tin tổng hợp cơ hội thị trường hàng ngày mới nhất. |

### 2. Nhóm Lắng nghe Xã hội & Voice of Customer (Social Listening)
| Tên Tool | Tham số chính | Chức năng & Giá trị đầu ra |
|---|---|---|
| `get_tiktok_creative_center_trends` | `geo, period, limit, industry` | Lấy bảng xếp hạng hashtag, nhạc nền, creator chính thức từ TikTok Creative Center. |
| `get_tiktok_search_suggestions` | `keywords, geo` | Lấy từ khóa gợi ý tìm kiếm (autocomplete) và sub-hashtags thực tế của người dùng. |
| `get_tiktok_video_comments` | `video_url, limit` | Cào bình luận công khai từ một video TikTok cụ thể. |
| `extract_customer_pain_points` | `keywords, geo, max_videos, inquiry_patterns` | Bóc tách phản đối mua hàng, câu hỏi về giá và nhu cầu chưa được đáp ứng từ bình luận. |
| `get_trending_topics` | `geo, timeframe, limit` | Lấy danh sách các chủ đề đang thịnh hành kèm điểm tín hiệu. |
| `get_topic_detail` | `topic_id` | Xem chi tiết cụm chủ đề và danh sách tín hiệu liên quan. |
| `generate_trend_artifact` | `topic_id, geo` | Xuất báo cáo HTML độc lập cho một chủ đề cụ thể. |
| `trigger_ingress_refresh` | `geo` | Buộc quét và làm mới toàn bộ nguồn dữ liệu cho một khu vực. |

### 3. Nhóm Dynamic Lexicon & Chẩn đoán Hạ tầng (Platform & Telemetry)
| Tên Tool | Tham số chính | Chức năng & Giá trị đầu ra |
|---|---|---|
| `register_domain_lexicon` | `domain, terms, category` | Đăng ký thuật ngữ/slang chuyên ngành vào cơ sở dữ liệu để Quality Gate nhận diện. |
| `register_noise_blacklist` | `terms` | Đăng ký từ khóa rác/spam để tự động loại bỏ trong các đợt cào tiếp theo. |
| `list_domain_lexicons` | `domain` | Tra cứu danh mục từ điển chuyên ngành và phân loại ngành hàng đang kích hoạt. |
| `diagnose_system_health` | Không | Kiểm tra telemetry toàn diện, circuit breakers và trạng thái các thành phần. |
| `get_system_logs` | `limit, level` | Truy vấn nhật ký sự kiện kiểm toán hệ thống. |
| `verify_connectors_health` | Không | Chạy synthetic diagnostics trên YouTube quota, Google RSS, DB pool, Playwright contexts. |
| `authenticate_tiktok` | `headless, timeout_seconds` | Quản lý vòng đời xác thực trình duyệt TikTok có mã hóa AES-256. |
| `get_platform_auth_status` | `platform` | Kiểm tra trạng thái phiên đăng nhập của các nền tảng mạng xã hội. |
| `clear_platform_auth` | `platform` | Xóa thông tin xác thực đã lưu của nền tảng. |

### 4. FastMCP Native Prompts & Resources
- **Prompts**:
  - `market_research_pipeline`: Tiêm kịch bản nghiên cứu chuẩn 6 bước SOP.
  - `voice_of_customer_audit`: Tiêm quy trình kiểm toán Voice of Customer & phản đối mua hàng.
- **Resources**:
  - `fn-ignis://sop/market-research`: Toàn văn hướng dẫn SOP nghiên cứu thị trường.
  - `fn-ignis://methodology/opportunity-index`: Công thức toán học và giải thích Opportunity Index (+100 đến -100).

