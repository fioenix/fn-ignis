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
8. [Research Workspace & Hai bề mặt Nghiên cứu](#8-research-workspace--hai-bề-mặt-nghiên-cứu)
9. [Danh mục 45 FastMCP Tools & Khả năng Nghiên cứu Toàn diện](#9-danh-mục-45-fastmcp-tools--khả-năng-nghiên-cứu-toàn-diện)

---

## 1. Tổng quan Kiến trúc

`fn-ignis` được thiết kế theo mô hình **Dual-Track**:

- **Track 1 (Continuous Radar)**: Chạy nền bằng daemon scheduler để thu thập qua runtime HTTP mà
  connector tự khai báo. Mặc định là Google Trends RSS và YouTube Data API; Threads/Reels chỉ tham
  gia khi có Graph API token. Image worker không mang Chromium, nên TikTok và browser fallback
  thuộc Track 2.
- **Track 2 (On-Demand Deep Research)**: Chạy chủ động theo nhu cầu nghiên cứu từng chiến dịch cụ thể. Hệ thống sẽ cào gợi ý tìm kiếm (autocomplete), quét lưới video, bóc tách Voice-of-Customer từ bình luận, tính toán **Opportunity Index** (+100 đến -100) và xuất Dashboard HTML tương tác.

Hai backend cùng dùng ba entity persistence:

- `sources`: một dòng cho mỗi object bên ngoài, key theo `(platform, external_id)`.
- `observations`: một collection event bất biến, giữ payload quan sát, cluster membership,
  identity-resolution route và clock provenance.
- `mission_evidence`: đúng observation mà một mission đã dùng.

Research workspace thêm một lớp phạm vi quanh ba entity đó chứ không mở thêm kho lưu trữ riêng.
Identity của workspace, các Market Brief revision, writer claim và run journal đều là dòng dữ liệu
trong cùng database đã cấu hình; `.ignis/research/<slug>/` giữ manifest, các run journal và artifact
đã xuất, không giữ database nào. Mục 8 mô tả ranh giới này.

Poll lặp tạo observation mới, không tạo source mới. Một source có thể phục vụ nhiều mission và nằm
trong nhiều cluster qua các observation khác nhau. Runtime không bao giờ ghi vào hai bảng legacy
`trend_signals` và `signal_metrics`; chỗ đọc duy nhất còn lại là guard của cluster pruner, nó coi
cluster mà corpus legacy vẫn trỏ tới là chưa rỗng, để việc prune trước backfill không cascade mất
những dòng backfill cần.

---

## 2. Các Chế độ Cài đặt Thủ công

### Chế độ 1: Zero-Docker Local Mode (SQLite)

Chế độ này phù hợp để chạy ngay trên máy tính cá nhân (macOS, Linux, Windows) mà **không cần cài đặt Docker hay PostgreSQL**. Toàn bộ dữ liệu được lưu tự động trong file `ignis.db`.

#### Bước 1: Yêu cầu môi trường
- Python $\ge 3.11$. CI kiểm 3.11, 3.12, 3.13 và 3.14 trên mỗi commit, nên bốn bản này đều đã chạy qua toàn bộ test suite.
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

# Cài đặt đúng bộ version đã khoá trong uv.lock
uv sync --locked --inexact
```

`--locked` bắt uv dùng đúng lời giải đã commit trong `uv.lock` và báo lỗi nếu lock lệch với
`pyproject.toml`. `--inexact` không gỡ những package nằm ngoài lock, nên nó không âm thầm xoá bộ
test của bạn. Muốn có luôn test tooling: `uv sync --locked --inexact --extra dev --extra browser`.

*(Không có uv thì dùng `python3 -m venv .venv && source .venv/bin/activate && pip install -e .`.
Đường này **không reproducible**: pip tự resolve từ khoảng version trong `pyproject.toml` và bỏ qua
`uv.lock`.)*

#### Bước 3: Thiết lập file `.env`
Sao chép file mẫu:
```bash
cp env.example .env
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
2. **Worker Daemon (`fn-ignis-worker`)** — *tùy chọn*: daemon chạy ngầm, thu dữ liệu nền qua các API chính thống (Google Trends RSS, YouTube Data API) theo nhịp mặc định ~2,4 giờ một lượt. Image không kèm browser runtime, nên các kênh chỉ lấy được bằng cách điều khiển browser (TikTok, và Threads/Instagram khi chưa có Graph token) không nằm trong worker mà thuộc Track 2 — chạy trên máy của bạn với session của bạn.
3. **Nginx Report Portal (`fn-ignis-reports`)**: Web server tĩnh phân phối các báo cáo HTML tại cổng `53080`.

#### Bước 1: Chuẩn bị file `.env`
```bash
cp env.example .env
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

Với database mới, container `db` chạy mọi file trong `sql/` theo thứ tự tên file ở lần khởi động
đầu tiên rồi mới chuyển sang healthy; điều này đã được kiểm chứng tới `021` trên
`timescale/timescaledb-ha:pg16`. Mọi bảng mà chuỗi migration tạo trong `public` đều bật
row-level security. Trên server có hai role Supabase `anon` và `authenticated`, `006` thêm policy
chỉ đọc cho hai role này trên `market_lexicons` và `industry_taxonomies`, còn `021` thu hồi mọi
quyền khác của chúng trên các bảng của chuỗi. Không migration nào tự tạo role. Các script init chỉ
chạy khi volume dữ liệu còn trống, nên database khởi tạo trước khi có `021` phải chạy
`sql/021_public_schema_rls_coverage.sql` một lần bằng kết nối của chủ sở hữu bảng; chạy lại cũng
không làm thay đổi gì. Với PostgreSQL
đã có corpus legacy, không khởi động worker mới ngay sau khi đưa artifact lên. Chạy đúng
[production cutover source/observation](migrations/2026-09-10-source-observation-baseline.md#production-cutover-runbook):
quiesce runtime cũ, snapshot, sinh baseline từ chính snapshot đó, apply `sql/016`, backfill, bắt
buộc verifier trả `VERIFIED`, rồi mới khởi động runtime mới và mở lại ingress.

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
        "IGNIS_ENV_FILE": "/ĐƯỜNG_DẪN_TUYỆT_ĐỐI/fn-ignis/.env"
      }
    }
  }
}
```

#### 2. Cấu hình cho OpenAI Codex / Antigravity
Cấu hình cho OpenAI Codex trong `~/.codex/config.toml`:
```toml
[mcp_servers.fn-ignis]
command = "/ĐƯỜNG_DẪN_TUYỆT_ĐỐI/fn-ignis/.venv/bin/python"
args = ["-m", "ignis.interfaces.mcp.server"]

[mcp_servers.fn-ignis.env]
IGNIS_ENV_FILE = "/ĐƯỜNG_DẪN_TUYỆT_ĐỐI/fn-ignis/.env"
```

`IGNIS_ENV_FILE` là biến duy nhất mà một MCP config cần, và nó là đường dẫn chứ không phải khoá.
Server tự đọc `.env`, nên chuỗi kết nối database, khoá Fernet và các API key nằm ở đúng một file.
Sao chép chúng vào config của client vừa đặt secret ở dạng plaintext tại nhiều nơi, vừa tạo thêm
một chỗ giữ cùng giá trị đó: `env` của host ghi đè file env, nên bản cũ sẽ âm thầm được ưu tiên.
Nếu rotate key YouTube trong `.env` mà Claude Desktop còn giữ key cũ thì mọi lệnh gọi YouTube qua
MCP đều thất bại với "API key expired", trong khi cùng đoạn code chạy từ shell lại thành công.

*(Mẹo: Bạn chỉ cần chạy lệnh `ignis-setup` hoặc `./scripts/bootstrap.sh`, hệ thống sẽ tự động cấu hình cho Claude Desktop, Antigravity, Codex và workspace `.mcp.json`).*

#### Hai hành vi của client dễ bị hiểu nhầm là lỗi

**Claude Code có thể yêu cầu bạn duyệt server của workspace.** File `.mcp.json` ở thư mục gốc dự án
thuộc phạm vi project, nên Claude Code để nó ở trạng thái chờ duyệt cho tới khi bạn chấp nhận một
lần. Trước đó, `claude mcp list` vẫn hiện entry nhưng báo là chưa được duyệt chứ không phải đã kết
nối, và chưa gọi được tool nào. Hãy chạy `claude` trong thư mục đó rồi duyệt server. Bản đăng ký ở
phạm vi user (`claude mcp add-json`) không cần bước này.

**Thoát hẳn Claude Desktop trước khi chạy bootstrap, rồi mở lại.** Claude Desktop giữ cấu hình
trong bộ nhớ và ghi đè file khi thoát, nên bản đăng ký được ghi lúc ứng dụng đang mở sẽ bị ghi đè
mất. Thứ tự đúng là: thoát ứng dụng, chạy `./scripts/bootstrap.sh` (hoặc
`python -m ignis.interfaces.cli.setup_bundle`), rồi mở lại.

---

## 3. Chi tiết Biến Môi trường & Cấu hình

Tất cả các biến môi trường được định nghĩa trong file `.env`:

| Tên biến | Kiểu dữ liệu | Mặc định | Bắt buộc | Mục đích & Giải thích |
|---|---|---|:---:|---|
| `DATABASE_URL` | String | `sqlite:///ignis.db` | Có | URI kết nối database. Dùng `sqlite:///ignis.db` cho Zero-Docker hoặc `postgresql://user:pass@host:5432/db` cho Postgres/TimescaleDB. |
| `DEFAULT_GEO` | String (ISO) | `VN` | Không | Mã quốc gia 2 ký tự mặc định để quét xu hướng (`VN`, `US`, `JP`, `UK`,...). |
| `YOUTUBE_API_KEY` | String | `""` | Khuyến nghị | Key Google Cloud YouTube Data API v3 để cào video tutorials & case studies. |
| `IGNIS_ENCRYPTION_KEY` | Base64 String | *(Tự sinh)* | Không | Khóa Fernet (256-bit key: AES-128-CBC + HMAC-SHA256) để mã hóa cookie/phiên đăng nhập TikTok lưu trong database. |
| `SCHEDULER_INTERVAL_SECONDS` | Integer | `8640` (~2,4 giờ) | Không | Nhịp chạy một lượt ingress của worker. Mặc định suy ra từ quota YouTube search: 10 từ khoá x 100 unit, tức một ngày chỉ đủ 10 lượt trong 10.000 unit. |
| `DISCOVERY_INTERVAL_HOURS` | Integer | `24` | Không | Khoảng cách giữa các đợt tự động quét toàn diện Creative Center và phát hiện white space. |
| `SYNC_INTERVAL_MINUTES` | Integer | `0` | Không | Ghi đè nhịp ingress của worker, tính theo phút. Giá trị lớn hơn 0 sẽ thắng `SCHEDULER_INTERVAL_SECONDS`; để 0 thì biến kia quyết định. Chỉ nâng lên khi người vận hành xác định được quota YouTube của mình chịu được số lượt tăng thêm. |
| `YOUTUBE_CACHE_TTL_SECONDS` | Integer | `86400` (24h) | Không | Thời gian lưu cache kết quả tìm kiếm YouTube để tiết kiệm quota 10,000 unit/ngày. |
| `PLAYWRIGHT_PROXY_SERVER` | String | `""` | Không | Proxy server HTTP/SOCKS5 (ví dụ: `http://user:pass@proxy.ip:port`) để cào TikTok không bị chặn. |
| `CONFIDENCE_HIGH_THRESHOLD` | Float | `80.0` | Không | Ngưỡng điểm để đánh giá chất lượng dữ liệu chiến dịch ở mức HIGH. |
| `CONFIDENCE_MEDIUM_THRESHOLD`| Float | `60.0` | Không | Ngưỡng điểm để đánh giá chất lượng dữ liệu chiến dịch ở mức MEDIUM. |
| `THREADS_APP_ID` | String | `""` | Không | Meta App ID cho Threads Graph API (chi tiết xem [META_INTEGRATION_GUIDE.md](META_INTEGRATION_GUIDE.md)). |
| `THREADS_APP_SECRET` | String | `""` | Không | Meta App Secret cho Threads Graph API (chi tiết xem [META_INTEGRATION_GUIDE.md](META_INTEGRATION_GUIDE.md)). |
| `THREADS_REDIRECT_URI` | String | `http://localhost:8000/oauth/callback` | Không | OAuth redirect callback URL cho Threads. |

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
  open examples/case-studies/case_study_ai_agents_vn.html      # Trên macOS
  xdg-open examples/case-studies/case_study_ai_agents_vn.html  # Trên Linux
  start examples/case-studies/case_study_ai_agents_vn.html     # Trên Windows
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

## 8. Research Workspace & Hai bề mặt Nghiên cứu

### 8.1 Nghiên cứu nằm ở đâu

Một nghiên cứu được đề xuất tại `<host-workspace>/.ignis/research/<research-slug>/`:

```text
<host-workspace>/
└── .ignis/
    └── research/
        └── ai-customer-service/
            ├── workspace.json        # manifest: identity nghiên cứu và format version
            └── journals/             # một bản ghi độc quyền cho mỗi lần chạy
                └── run-20260921-103000-001.json
```

Bước đề xuất chỉ đọc. `propose_research_workspace(host_workspace, research_name)` báo đường dẫn sẽ
dùng, thư mục đã tồn tại chưa, đã có manifest chưa và có cần bước nhận thư mục hay không; nó không
tạo thư mục, manifest, bản ghi database hay journal nào. Chỉ
`confirm_research_workspace(proposed_path, confirmation=true)` mới tạo ra thứ gì đó.

Tình trạng sẵn có của thư mục quyết định kết quả:

| Tình trạng thư mục | Kết quả |
|---|---|
| Chưa có hoặc rỗng | Tạo mới kèm manifest mới |
| Đã có manifest khớp | Tái sử dụng nguyên trạng, không ghi đè manifest |
| Có nội dung, chưa có manifest | Từ chối cho tới khi truyền `adopt=true`; bước nhận giữ nguyên mọi file không liên quan |
| Manifest thuộc format mới hơn | Báo `INCOMPATIBLE` thay vì đọc một nửa |

**Thư mục nghiên cứu không chứa database.** Mọi research workspace dùng chung một database Ignis
đã cấu hình qua `DATABASE_URL`: mặc định là SQLite cục bộ, PostgreSQL là backend tương đương tuỳ
chọn. Đó là điều kiện để mở lại một nghiên cứu: `list_research_workspaces()` trả về các nghiên cứu
nằm trong database đó, nên một Agent host thứ hai trên cùng database tìm ra nghiên cứu mà không cần
phiên chat đã tạo ra nó.

### 8.2 `ATTENTION` và `MARKET`

Mỗi mission trả lời một trong hai câu hỏi và giữ nguyên bề mặt đó suốt vòng đời.

| | `ATTENTION` | `MARKET` |
|---|---|---|
| Câu hỏi | Cái gì đang được chú ý? | Đây có phải cơ hội thị trường không? |
| Điểm vào | `create_attention_mission` | `confirm_market_brief` |
| Bắt buộc có giả thuyết | Không | Có |
| Opportunity Index | Không bao giờ phát ra | Có phát ra |
| Vai trò bằng chứng khi phân tích | `ATTENTION_CONTEXT` | `MARKET_EVIDENCE` |

`ATTENTION` dành cho người yêu cầu chưa biết chủ đề nào đáng điều tra. Nó trả về chủ đề đã xếp
hạng kèm momentum, độ tươi dữ liệu, độ phủ nguồn và citation tra được tới từng observation, và nó
không đưa ra khẳng định thương mại nào.

`MARKET` đòi một Brief đã được người yêu cầu xác nhận. Cả bảy trường đều bắt buộc:

| Trường | Ý nghĩa |
|---|---|
| `decision` | Quyết định mà nghiên cứu này phải phục vụ |
| `target_user` | Nhóm người dùng hoặc khách hàng đang được điều tra |
| `problem` | Nỗi đau hoặc công việc cần tìm hiểu |
| `geo` | Phạm vi địa lý |
| `timeframe` | Cửa sổ thời gian của bằng chứng |
| `hypothesis` | Mệnh đề có thể bị bác bỏ |
| `falsifiers` | Ít nhất một điều kiện đủ sức bác bỏ giả thuyết |

Brief thiếu trường sẽ bị từ chối trước khi có probe nào chạy, và câu từ chối nêu đúng các trường
còn thiếu. Mission `MARKET` không đọc được Brief thì bị chặn chứ không chạy: thực thi, phân tích và
xuất artifact đều trả về cùng một kết quả `BLOCKED`, vì một Opportunity Index rút ra từ bằng chứng
không ai đặt câu hỏi cho nó là kiểu hỏng âm thầm hơn hẳn việc từ chối probe.

Phần hỏi đáp dựng Brief thuộc về host Agent: hỏi tối đa bảy câu, mỗi lần một câu, bỏ qua trường đã
có câu trả lời, đưa bản nháp cho người yêu cầu sửa rồi xin xác nhận rõ ràng. **fn-ignis không nhận
transcript và không có thao tác lưu bản nháp.** Người yêu cầu bỏ dở giữa chừng thì không để lại gì,
bởi chưa có gì được gửi đi.

### 8.3 Handoff và revision

Chọn một chủ đề Attention để điều tra thương mại sẽ tạo mission mới, không phải dán nhãn lại mission cũ:

```text
confirm_market_brief(
    workspace_id=...,
    parent_attention_mission_id=<mission Attention>,   # lineage, tuỳ chọn
    parent_cluster_id=<cluster đã chọn>,               # tuỳ chọn, phải là cluster mission đó từng thấy
    decision=..., target_user=..., problem=...,
    geo=..., timeframe=..., hypothesis=..., falsifiers=[...],
    confirmed_by=...,
)
```

Lineage là ngữ cảnh. Những observation Attention mà nó trỏ tới nằm trong khối `attention_context`
với vai trò `ATTENTION_CONTEXT`, và chúng không thoả mãn được một cơ hội Market hay một citation
chống lưng cho kết luận; mission mới tự thu thập `MARKET_EVIDENCE` của nó.

Sửa một Brief đã xác nhận sẽ tạo revision mới thay vì sửa bản cũ. Truyền `previous_mission_id` để
mở một mission Market mới gắn với một `MarketBriefRevision` bất biến, đánh số revision kế tiếp
trong nhánh nghiên cứu đó, kèm `revises_mission_id` trỏ ngược về mission mà nó sửa. Mission cũ,
Brief và evidence của nó giữ nguyên; revision kế thừa đúng nguồn gốc Attention của mission mà nó
sửa, còn payload khai một nguồn khác sẽ bị từ chối chứ không bị lặng lẽ bỏ qua.

### 8.4 Chạy song song, journal và khôi phục

Hai mission của cùng một nghiên cứu chạy cùng lúc; writer claim tính theo từng mission và không bao
giờ xếp hàng cả một nghiên cứu.

- **Mỗi mission một writer đang hoạt động.** Lần chạy thứ hai trên cùng mission nhận kết quả
  `CONFLICT` nêu run nào đang giữ slot và giữ từ lúc nào. Nó không chạm tới connector nào và không
  ghi gì.
- **Mỗi lần chạy một journal độc quyền.** Mỗi run lấy file riêng dưới `journals/`, tạo theo cơ chế
  độc quyền, nên hai run khởi động trong cùng một giây vẫn nhận tên khác nhau. Run đã kết thúc báo
  `COMPLETED` hoặc `FAILED` kèm thời điểm kết thúc; run không bao giờ báo về giữ nguyên `STARTED`
  và không có thời điểm kết thúc, vì "run này đã kết thúc" và "không ai nghe tin gì từ nó nữa" là
  hai dữ kiện khác nhau.
- **Khôi phục phải nói rõ.** Chỉ chính run đang giữ claim mới nhả được claim đó. Ở đây không có cơ
  chế hết hạn và không có force release: trao slot cho writer thứ hai theo đồng hồ trong khi writer
  thứ nhất có thể vẫn đang chạy chính là sự cố mà slot này sinh ra để chặn. Khi một run chắc chắn
  đã chết, `release_mission_writer(mission_id, run_id)` khôi phục mission và đòi đúng `run_id` mà
  kết quả CONFLICT đã báo. Sai `run_id` thì lệnh từ chối và không thay đổi gì.

Mission tạo bên ngoài research workspace, tức mọi mission có trước tính năng này, không lấy writer
claim và không ghi journal; chúng chạy y như trước.

---

## 9. Danh mục 45 FastMCP Tools & Khả năng Nghiên cứu Toàn diện

Khi FastMCP Server khởi chạy (`ignis-mcp`), 45 tools, 2 prompts và 2 resources sau đây luôn sẵn sàng cho AI Agents hoặc MCP clients:

### 0. Nhóm Research Workspace & Hai bề mặt Nghiên cứu
| Tên Tool | Tham số chính | Chức năng & Giá trị đầu ra |
|---|---|---|
| `propose_research_workspace` | `host_workspace, research_name, slug` | Báo nghiên cứu sẽ nằm ở đâu. Chỉ đọc, không tạo thư mục, manifest, bản ghi database hay journal. |
| `confirm_research_workspace` | `proposed_path, confirmation, adopt, research_name` | Tạo, tái sử dụng hoặc nhận workspace đã đề xuất sau khi người yêu cầu đồng ý. |
| `list_research_workspaces` | `limit` | Liệt kê các research workspace trong database đã cấu hình để mở lại từ bất kỳ Agent host nào. |
| `create_attention_mission` | `workspace_id, title, geo, timeframe, seed, keywords, platforms` | Mở mission `ATTENTION`: không cần giả thuyết, không phát ra Opportunity Index. |
| `confirm_market_brief` | `workspace_id`, bảy trường Brief, `parent_attention_mission_id`, `parent_cluster_id`, `previous_mission_id` | Lưu Brief đã xác nhận và mở mission `MARKET` tương ứng; cũng là điểm vào của handoff từ Attention và của revision. |
| `release_mission_writer` | `mission_id, run_id` | Khôi phục mission có run đã chết trong lúc giữ writer slot, bằng cách nêu đúng run đó. |

### 1. Nhóm Chiến dịch & Nghiên cứu Chiến lược (Research & White Space)
| Tên Tool | Tham số chính | Chức năng & Giá trị đầu ra |
|---|---|---|
| `run_autonomous_research_mission` | `topic, keywords, geo, timeframe, min_signals` | Tạo mission, chạy ingress đa nền tảng, tính Opportunity Index và xuất dashboard trong 1 bước. |
| `create_research_mission` | `topic, keywords, platforms, geo, timeframe` | Khởi tạo chiến dịch nghiên cứu nhắm đích bên ngoài research workspace; mission không khai báo bề mặt nên không bị chặn bởi Brief. |
| `execute_mission_ingress` | `mission_id` | Thực thi cào dữ liệu đa nguồn và đánh giá Quality Scorecard (Confidence $\ge 70\%$). |
| `evaluate_mission_quality` | `mission_id` | Đánh giá lại 4 chiều chất lượng dữ liệu (Coverage, Language, Freshness, Diversity). |
| `discover_market_opportunities` | `mission_id` | Khám phá các khoảng trống thị trường (Unserved White Spaces) và xếp hạng tiềm năng. |
| `get_mission_analysis` | `mission_id, limit, platform` | Trích xuất phân tích tổng hợp theo bề mặt của mission: bằng chứng xếp hạng, scorecard chất lượng, lineage, và riêng `MARKET` mới có Opportunity Index cùng white space. |
| `generate_mission_artifact` | `mission_id` | Xuất bản file HTML Dashboard Infographic tương tác trực quan vào thư mục `reports/`. |
| `list_research_missions` | `limit` | Liệt kê lịch sử các chiến dịch nghiên cứu đã thực hiện. |
| `get_current_session_mission` | `session_id` | Khôi phục ngữ cảnh chiến dịch gắn với phiên chat của agent. |
| `trigger_autonomous_discovery` | `geo` | Kích hoạt chu kỳ tự động phát hiện xu hướng và tổng hợp cơ hội trên toàn quốc gia. |
| `get_latest_daily_discovery` | `geo` | Lấy bản tin tổng hợp cơ hội thị trường hàng ngày mới nhất. |

### 2. Nhóm Lắng nghe Xã hội & Voice of Customer (Social Listening)
| Tên Tool | Tham số chính | Chức năng & Giá trị đầu ra |
|---|---|---|
| `get_threads_trending_topics` | `geo, limit` | Lấy các chủ đề thịnh hành thời gian thực từ Threads (`threads.net/search`). |
| `get_threads_search_suggestions` | `keyword, geo, limit` | Lấy từ khóa gợi ý tìm kiếm (autocomplete) từ Threads search. |
| `get_tiktok_creative_center_trends` | `geo, period, limit, industry` | Lấy bảng xếp hạng hashtag, nhạc nền, creator chính thức từ TikTok Creative Center. |
| `get_tiktok_search_suggestions` | `keywords, geo` | Lấy từ khóa gợi ý tìm kiếm (autocomplete) và sub-hashtags thực tế của người dùng. |
| `get_tiktok_video_comments` | `video_url, limit` | Cào bình luận công khai từ một video TikTok cụ thể. |
| `extract_customer_pain_points` | `keywords, geo, max_videos, inquiry_patterns` | Bóc tách phản đối mua hàng, câu hỏi về giá và nhu cầu chưa được đáp ứng từ bình luận. |
| `get_trending_topics` | `geo, timeframe, limit` | Lấy danh sách các chủ đề đang thịnh hành kèm điểm tín hiệu. |
| `get_topic_detail` | `topic_id` | Xem chi tiết cụm chủ đề và danh sách tín hiệu liên quan. |
| `generate_trend_artifact` | `topic_id, geo, format` | Xuất báo cáo HTML độc lập: dashboard, thẻ chủ đề (`topic_id`), hoặc đồ thị tương tác (`format="graph"`) zoom/pan được. Đồ thị xem chi tiết tới tầng cluster; tín hiệu được gom thành vầng chấm quanh cluster nên không bị lag khi dữ liệu lớn. |
| `trigger_ingress_refresh` | `geo, scope` | Buộc quét và làm mới toàn bộ nguồn dữ liệu cho một khu vực. Mặc định `scope="public_market"`: chỉ lấy dữ liệu công khai, không đọc và không tính post của chính tài khoản đang đăng nhập. Chỉ dùng `scope="own_profile"` khi người dùng nói rõ là muốn xem profile của họ. |

### 3. Nhóm Xác thực Meta (Threads & Instagram)
| Tên Tool | Tham số chính | Chức năng & Giá trị đầu ra |
|---|---|---|
| `authenticate_threads` | `auth_code?, client_id?, client_secret?, redirect_uri?, browser_login?, headless?, timeout_seconds?` | Kết nối Threads theo Dual-UX: không có `auth_code` (hoặc `browser_login=true`) chạy Tier 1 bắt phiên trình duyệt 1 chạm; có `auth_code` chạy Tier 2 OAuth 2.0 nâng cấp Long-Lived Token 60 ngày, mã hóa AES. |
| `get_threads_auth_status` | Không | Kiểm tra Threads trên cả hai tier: trạng thái token, scopes, key_version, số ngày còn lại, có cần refresh không, kèm phiên trình duyệt. |
| `clear_threads_auth` | Không | Xóa thông tin xác thực Threads (OAuth và phiên trình duyệt) khỏi bộ lưu trữ mã hóa cục bộ. Không thu hồi token ở phía Meta; làm riêng trong phần bảo mật tài khoản Meta nếu cần. |
| `authenticate_instagram` | `auth_code?, client_id?, client_secret?, redirect_uri?, browser_login?, headless?, timeout_seconds?` | Kết nối Instagram theo Dual-UX: Tier 1 bắt phiên trình duyệt 1 chạm hoặc Tier 2 OAuth 2.0 Instagram Graph API với Long-Lived Token 60 ngày. |
| `get_instagram_auth_status` | Không | Kiểm tra Instagram trên cả hai tier: trạng thái token, scopes, số ngày còn lại, kèm phiên trình duyệt. |
| `clear_instagram_auth` | Không | Xóa thông tin xác thực Instagram (OAuth và phiên trình duyệt) khỏi bộ lưu trữ mã hóa cục bộ. Không thu hồi token ở phía Meta; làm riêng trong phần bảo mật tài khoản Meta nếu cần. |

*(Hướng dẫn chi tiết tích hợp Threads & Instagram Reels xem tại [META_INTEGRATION_GUIDE.vi.md](META_INTEGRATION_GUIDE.vi.md))*

### 4. Nhóm Dynamic Lexicon, Runtime Config & Chẩn đoán Hạ tầng
| Tên Tool | Tham số chính | Chức năng & Giá trị đầu ra |
|---|---|---|
| `get_runtime_config` | `key, category` | Xem các tham số giao thức chạy động (`threads_web_client_id`, `doc_id`, endpoints) từ database và RAM cache. |
| `update_runtime_config` | `key, value, category, description` | Cho phép AI Agent tự động cập nhật tham số giao thức khi web client xoay vòng build. |
| `refresh_runtime_config_cache` | Không | Ép hủy và nạp lại toàn bộ cấu hình chạy động từ database vào bộ nhớ đệm RAM. |
| `register_domain_lexicon` | `domain, terms, category` | Đăng ký thuật ngữ/slang chuyên ngành vào cơ sở dữ liệu để Quality Gate nhận diện. |
| `register_noise_blacklist` | `terms` | Đăng ký từ khóa rác/spam để tự động loại bỏ trong các đợt cào tiếp theo. |
| `list_domain_lexicons` | `domain` | Tra cứu danh mục từ điển chuyên ngành và phân loại ngành hàng đang kích hoạt. |
| `diagnose_system_health` | Không | Kiểm tra telemetry toàn diện, circuit breakers và trạng thái các thành phần. |
| `get_system_logs` | `limit, level` | Truy vấn nhật ký sự kiện kiểm toán hệ thống. |
| `verify_connectors_health` | Không | Chạy synthetic diagnostics trên YouTube quota, Google RSS, DB pool, Playwright contexts. |
| `authenticate_tiktok` | `headless, timeout_seconds` | Quản lý vòng đời xác thực trình duyệt TikTok có mã hóa Fernet (AES-128-CBC + HMAC-SHA256). |
| `get_platform_auth_status` | `platform` | Kiểm tra trạng thái phiên đăng nhập của các nền tảng mạng xã hội, kèm cảnh báo token sắp hết hạn (< 7 ngày) và lịch `refresh_plan` giãn cách để không làm mới nhiều phiên Tier-1 cùng lúc. |
| `clear_platform_auth` | `platform` | Xóa thông tin xác thực đã lưu của nền tảng. |

### 5. FastMCP Native Prompts & Resources
- **Prompts**:
  - `market_research_pipeline`: Tiêm kịch bản nghiên cứu chuẩn 6 bước SOP.
  - `voice_of_customer_audit`: Tiêm quy trình kiểm toán Voice of Customer & phản đối mua hàng.
- **Resources**:
  - `fn-ignis://sop/market-research`: Toàn văn hướng dẫn SOP nghiên cứu thị trường.
  - `fn-ignis://methodology/opportunity-index`: Công thức toán học và giải thích Opportunity Index (+100 đến -100).
