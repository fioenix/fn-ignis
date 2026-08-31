# fn-ignis Constitution

Tài liệu Hiến pháp Dự án (Project Constitution) quy định các nguyên tắc bất biến trong kiến trúc, phát triển và quản trị của nền tảng `fn-ignis`.

---

## Core Principles

### I. Zero-Token Ingress & Separation of Concerns (BẤT BIẾN)
- Tầng thu thập dữ liệu (Connectors & Ingestion ETL) phải chạy độc lập dưới dạng deterministic background workers (Cron/Docker), hoàn toàn không tiêu thụ LLM tokens và không phụ thuộc vào vòng đời của Agent client.
- Agent LLM chỉ tham gia vào tầng tổng hợp ngữ nghĩa (Semantic Synthesis), phân tích chiến lược (Reasoning) và trực quan hóa (Artifacts).

### II. Pluggable & Isolated Connector Architecture
- Mỗi Connector nền tảng (YouTube, Google RSS, TikTok, Threads, Reels) là một module độc lập, tuân thủ `BaseConnector` interface chuẩn.
- Bắt buộc triển khai Circuit Breaker và Error Isolation: Lỗi cào dữ liệu từ một nền tảng không bao giờ được làm sập toàn bộ Ingress pipeline hoặc ảnh hưởng đến các kênh khác.

### III. Storage-First & Time-Series Rigor
- Sử dụng PostgreSQL kết hợp TimescaleDB hypertable cho mọi dữ liệu chuỗi thời gian (metric_value, velocity).
- Sử dụng `pgvector` cho semantic topic clustering. Mọi câu truy vấn xu hướng từ MCP Tool phải được tối ưu qua index để đạt độ trễ <50ms.

### IV. Builder Pattern for Deterministic Artifacts
- MCP Server đóng vai trò là Template Builder (Jinja2/Tailwind/Recharts) khi trả về Artifacts cho Agent client.
- Không để LLM tự viết lại toàn bộ mã HTML/CSS từ đầu nhằm đảm bảo giao diện hiển thị chính xác 100% (Pixel-Perfect), tránh vỡ layout và tối ưu token output.

### V. Simplicity, Surgical Changes & Type Safety
- Python 3.11+, định kiểu tường minh (Type hints & Pydantic models).
- Không bổ sung các abstraction hoặc cấu hình suy đoán không cần thiết (YAGNI).
- Code tối giản: Giải quyết bài toán với lượng code tối thiểu, dễ bảo trì.

---

## Technology Stack Constraints

- **Language & Runtime:** Python >= 3.11, uv package manager.
- **Database:** PostgreSQL 16 + TimescaleDB + pgvector.
- **Protocol:** Model Context Protocol (FastMCP).
- **Ingress Libraries:** `google-api-python-client`, `feedparser`, `httpx`, `playwright`.
- **UI / Artifacts:** Single-file HTML với Tailwind CSS CDN & Recharts.

---

## Governance & SDD Workflow

- Mọi tính năng lớn đều phải tuân thủ quy trình Spec-Driven Development (SDD):
  1. `/speckit-specify` - Tạo bản đặc tả yêu cầu (Requirements Spec).
  2. `/speckit-plan` - Lập kế hoạch kiến trúc kỹ thuật (Technical Plan).
  3. `/speckit-tasks` - Bẻ nhỏ thành danh sách task cụ thể.
  4. `/speckit-implement` - Tiến hành triển khai code và kiểm thử.
  5. `/speckit-converge` - Đánh giá và đối chiếu code với spec ban đầu.

**Version**: 1.0.0 | **Ratified**: 2026-08-31 | **Last Amended**: 2026-08-31
