# Feature Specification: FastMCP Server Interface & Deterministic Artifacts

**Feature Directory**: `specs/004-fastmcp-server-and-artifacts`
**Created**: 2026-08-31
**Status**: Implemented; citation attribution remains partial
**Input**: Pha 4 (FastMCP Server & Deterministic Artifact Builder)
**As-built amendment**: 2026-09-13 — 39 independent tools and typed strategic-insight citations

**Scope boundary**: This feature owns the open-source local MCP interface over standard
input/output and local-file artifact delivery. Authenticated remote HTTP delivery, hosted artifact
access, and hosted tool authorization are owned by
[`specs/006-hosted-mcp-access`](../006-hosted-mcp-access/spec.md).

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
- **FR-003**: FastMCP server MUST keep the four original tools independently callable within the
  current 39-tool catalog: `get_trending_topics`, `get_topic_detail`, `generate_trend_artifact`,
  and `trigger_ingress_refresh`.
- **FR-004**: `get_mission_analysis` MUST serialize channel summaries and typed citations already
  attached to strategic insights. Opportunity and actionable-takeaway citations remain incomplete
  until the residual contract in `docs/DATA_PROVENANCE_AND_CITATION_SPEC.md` is implemented.
- **FR-005**: The open-source server MUST remain independently usable over local standard
  input/output without depending on the hosted service or hosted identity provider.
- **FR-006**: Tool handlers shared with hosted delivery MUST remain one implementation; this feature
  MUST NOT grow a second hosted copy of domain or scoring behavior.
- **FR-007**: Local artifact tools MAY return operator-local file paths. That behavior MUST NOT be
  interpreted as the remote artifact contract defined by feature 006.
