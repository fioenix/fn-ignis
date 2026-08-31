# Feature Specification: FastMCP Server Interface & Deterministic Artifacts

**Feature Directory**: `specs/004-fastmcp-server-and-artifacts`
**Created**: 2026-08-31
**Status**: Ready for Implementation
**Input**: Pha 4 (FastMCP Server & Deterministic Artifact Builder)

---

## User Scenarios & Testing *(mandatory)*

### User Story 1 - FastMCP Tools for AI Agents (Priority: P1)

Là một AI Agent (Claude Desktop, Antigravity, Cursor, OpenAI Codex), tôi cần kết nối qua giao thức Model Context Protocol (FastMCP) để truy vấn xu hướng, xem chi tiết tín hiệu và kích hoạt cào dữ liệu với phản hồi tức thì (< 50ms).

**Acceptance Scenarios**:
1. **Given** MCP Client kết nối tới server, **When** gọi `get_trending_topics()`, **Then** server trả về danh sách JSON các chủ đề có momentum cao nhất.
2. **Given** `topic_id` cụ thể, **When** gọi `get_topic_detail()`, **Then** trả về dữ liệu chuỗi thời gian và phân bố theo từng nền tảng.

---

### User Story 2 - Pixel-Perfect Deterministic HTML Artifacts (Priority: P2)

Là người dùng / AI Agent, tôi cần sinh ra các HTML Artifacts trực quan hóa biểu đồ (Recharts/Chart.js + Tailwind CSS) chuẩn xác 100% pixel-perfect từ template dựng sẵn mà không để LLM tự viết lại mã HTML gây vỡ giao diện (Nguyên tắc IV).

**Acceptance Scenarios**:
1. **Given** Danh sách các cụm xu hướng, **When** gọi `generate_trend_artifact()`, **Then** trả về Single-file HTML hoàn chỉnh kèm CSS và Javascript vẽ biểu đồ.

---

## Requirements

- **FR-001**: `IArtifactBuilder` PHẢI định nghĩa hàm `build_dashboard_artifact(clusters, geo)` và `build_topic_card_artifact(cluster, signals)`.
- **FR-002**: `HtmlArtifactBuilder` PHẢI sử dụng Jinja2 render Single-File HTML nhúng Tailwind CDN và Recharts/Chart.js.
- **FR-003**: FastMCP server PHẢI expose đầy đủ 4 tools cốt lõi: `get_trending_topics`, `get_topic_detail`, `generate_trend_artifact`, `trigger_ingress_refresh`.
