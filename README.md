# fn-ignis 🔥
**Unified Self-Hosted Mission-Driven Trend Intelligence & Social Listening Platform with FastMCP**

`fn-ignis` là nền tảng tự lưu trữ (self-hosted) giúp các AI Agent (Claude Desktop, Antigravity, Cursor, Codex) tự động khởi tạo các **chiến dịch nghiên cứu xu hướng đa kênh có định hướng (Targeted Research Missions)** trên Google Trends, YouTube, TikTok, Threads, Instagram Reels với chi phí vận hành **$0** (Zero-Token Ingress), lưu trữ phân tích trên Supabase/TimescaleDB và xuất báo cáo Artifacts chuẩn xác 100% pixel-perfect.

---

## 🏛️ Luồng Vận Hành Cốt Lõi (Mission-Driven Architecture)

Thay vì cào đại trà vô tội vạ, `fn-ignis` trao quyền cho AI Agent chủ động điều phối:

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│ 1. USER & AGENT (Claude Desktop / Antigravity)                                         │
│    User: "Nghiên cứu thị trường thời trang linen / bền vững tại VN 7 ngày qua"        │
│    Agent lập kế hoạch và định nghĩa:                                                   │
│      - Keywords: ["thời trang bền vững", "vải linen", "local brand eco"]               │
│      - Kênh: Google Trends, YouTube, TikTok, Threads, Reels                            │
├────────────────────────────────────────────────────────────────────────────────────────┤
│ 2. MCP INTERFACE & ORCHESTRATION                                                       │
│    Agent gọi FastMCP Tools:                                                            │
│      1. `create_research_mission(topic, keywords, platforms, geo="VN", timeframe="7d")`│
│      2. `execute_mission_ingress(mission_id)`                                          │
├────────────────────────────────────────────────────────────────────────────────────────┤
│ 3. TARGETED DEEP INGRESS (Đào sâu dữ liệu)                                             │
│    - Google Trends: Lấy biểu đồ Interest over time + Explore queries                   │
│    - YouTube: Search top video liên quan + Trích xuất views, likes, comments nổi bật   │
│    - TikTok / Threads / Reels: Search bài đăng thảo luận thực tế theo hashtag/keyword  │
│    - Lưu toàn bộ Signals & Context vào Supabase gắn theo `mission_id`                  │
├────────────────────────────────────────────────────────────────────────────────────────┤
│ 4. AGENT PHÂN TÍCH & GENERATE ARTIFACT                                                 │
│    - Agent gọi `get_mission_analysis(mission_id)` $\rightarrow$ Phân tích insight      │
│    - Gọi `generate_mission_artifact(mission_id)` $\rightarrow$ Xuất Dashboard HTML sâu│
└────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 🤖 Danh Mục FastMCP Tools Cho AI Agent

| Tên Tool | Mục đích | Tham số | Đầu ra |
|---|---|---|---|
| `create_research_mission` | Tạo một bài toán nghiên cứu theo chủ đề & từ khóa cụ thể | `topic`, `keywords`, `platforms`, `geo="VN"`, `timeframe="7d"` | `mission_id` và thông tin khởi tạo |
| `execute_mission_ingress` | Kích hoạt cào sâu đa kênh cho mission đó | `mission_id` | Báo cáo số lượng signals và clusters đã lưu |
| `get_mission_analysis` | Lấy toàn bộ dữ liệu cào được, phân bố nền tảng và metrics | `mission_id` | JSON chi tiết phục vụ Agent phân tích chiến lược |
| `generate_mission_artifact` | Sinh Single-File HTML Artifact báo cáo chuyên sâu đa kênh | `mission_id` | Mã HTML Tailwind CSS hoàn chỉnh pixel-perfect |
| `list_research_missions` | Liệt kê các chiến dịch nghiên cứu đã thực hiện | `limit=10` | JSON danh sách các mission gần nhất |
| `get_trending_topics` | Truy vấn các chủ đề nóng chung đa kênh | `geo="VN"`, `limit=10` | Bảng xếp hạng các cụm chủ đề tổng hợp |
| `generate_trend_artifact` | Sinh Dashboard tổng quan xu hướng chung | `topic_id=""`, `geo="VN"` | HTML Dashboard tổng quan |

---

## 🚀 Khởi Động Nhanh

### 1. Cài đặt môi trường
```bash
uv venv .venv
source .venv/bin/activate
uv pip install -e ".[dev]" pytest pytest-asyncio
```

### 2. Cấu hình Claude Desktop (`claude_desktop_config.json`)
```json
{
  "mcpServers": {
    "fn-ignis": {
      "command": "/Users/fioenix/Projects/fn-ignis/.venv/bin/python",
      "args": ["-m", "ignis.interfaces.mcp.server"],
      "env": {
        "DATABASE_URL": "postgresql://postgres.jxbysxsovxjglgkgkkfu:Ignis_Trend_999e20f8aaba8f64@aws-0-ap-southeast-1.pooler.supabase.com:5432/postgres",
        "DEFAULT_GEO": "VN"
      }
    }
  }
}
```

---

## 🧪 Kiểm Thử (Testing)

```bash
.venv/bin/pytest tests/ -v
```
