# Tasks: FastMCP Server & Deterministic Artifacts

## Phase 1: Artifact Port & Templates
- [x] T001 Tạo port `IArtifactBuilder` trong `src/ignis/application/ports/artifact_port.py`
- [x] T002 Tạo templates Jinja2 `trend_dashboard.html` và `trend_card.html` trong `src/ignis/infrastructure/templates/html/`
- [x] T003 Cài đặt `HtmlArtifactBuilder` trong `src/ignis/infrastructure/templates/html_builder.py`
- [x] T004 [P] Viết unit tests cho `HtmlArtifactBuilder` trong `tests/unit/test_html_builder.py`

## Phase 2: FastMCP Server & Tools
- [x] T005 Cài đặt FastMCP Server trong `src/ignis/interfaces/mcp/server.py`
- [x] T006 [P] Viết unit tests cho FastMCP Server Tools trong `tests/unit/test_mcp_server.py`

## Phase 3: As-Built Reporting Contract (2026-09-13)

- [x] T007 Keep the 39-tool catalog independently callable and synchronized across manifests
- [x] T008 Serialize channel summaries and typed `StrategicInsight` citations from mission analysis
- [x] T009 Add observation-addressable typed citations to `MarketOpportunity` and actionable
  takeaways, then expose them consistently in FastMCP and HTML artifacts. Completed by
  `specs/007-dual-surface-research-workspace/tasks.md` T023 and locked at the serializer boundary
  by T035.
