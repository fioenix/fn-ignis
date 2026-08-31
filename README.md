# fn-ignis 🔥

> **Unified Self-Hosted Trend Intelligence & Social Listening Platform with Native MCP Server**

`fn-ignis` là nền tảng thu thập, chuẩn hóa và phân tích xu hướng đa kênh (YouTube, Google Trends, TikTok, Threads, Instagram Reels) chạy trên hạ tầng self-host với chi phí $0, kết nối trực tiếp với các AI Agent (Claude Desktop, Antigravity, Codex) qua chuẩn **Model Context Protocol (MCP)**.

---

## 🏛️ Kiến trúc Hệ thống

1. **Ingress Layer (Background Workers):** Chạy định kỳ độc lập (0 LLM Token), cào dữ liệu từ 5 nguồn và xử lý qua Circuit Breaker.
2. **Storage Pool (PostgreSQL + TimescaleDB + pgvector):** Lưu trữ chuỗi thời gian phân tích tốc độ tăng trưởng (momentum/velocity) và vector embeddings để gom cụm chủ đề (Entity Resolution).
3. **MCP Server (FastMCP):** Cung cấp các Tools truy vấn siêu tốc (<50ms) và Template Engine (Builder Pattern) sinh Artifacts trực quan (Tailwind + Recharts).
4. **Agent Frontier:** Tương tác qua Claude Desktop / Antigravity / Codex (Chat đàm thoại + Scheduled Routine 8:00 AM Morning Briefing).

---

## 📁 Cấu trúc Thư mục

```text
fn-ignis/
├── docker-compose.yml        # PostgreSQL 16 + TimescaleDB + pgvector
├── sql/
│   └── init.sql              # Database schema & hypertable init
├── pyproject.toml            # Package metadata & dependencies
├── .env.example              # Environment variables template
└── src/
    └── ignis/
        ├── connectors/       # Pluggable Connectors (YouTube, Google, TikTok, Threads, Reels)
        ├── core/             # DB connection pool, models, clustering logic
        ├── mcp/              # FastMCP Server & tool implementations
        ├── templates/        # HTML Artifact Templates (Tailwind + Recharts)
        └── workers/          # Background cron ingestion & pipeline runner
```

---

## 🚀 Khởi động Nhanh (Quickstart)

### 1. Khởi chạy Database
```bash
docker compose up -d
```

### 2. Cấu hình Môi trường
```bash
cp .env.example .env
# Điền YOUTUBE_API_KEY nếu có
```

### 3. Cài đặt Dependencies (sử dụng uv hoặc pip)
```bash
uv venv
source .venv/bin/activate
uv pip install -e .
```

### 4. Chạy Ingress Sync & Khởi động MCP Server
```bash
# Chạy sync dữ liệu thử nghiệm
python -m ignis.workers.sync_runner

# Khởi động MCP Server cho Claude Desktop / Antigravity
python -m ignis.mcp.server
```
