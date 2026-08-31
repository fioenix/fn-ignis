# Implementation Plan: FastMCP Server & Deterministic Artifacts

**Feature Directory**: `specs/004-fastmcp-server-and-artifacts`
**Date**: 2026-08-31
**Spec**: [spec.md](./spec.md)

---

## Technical Context

- **MCP Framework**: `fastmcp>=0.4.0`
- **Template Engine**: `jinja2`
- **Frontend Stack**: Tailwind CSS CDN, Chart.js / Recharts responsive charts
- **Delivery**: Return full HTML string formatted as MCP content / artifact

---

## Structure

```text
src/ignis/
├── application/
│   └── ports/artifact_port.py
├── infrastructure/
│   └── templates/
│       ├── html_builder.py
│       └── html/
│           ├── trend_dashboard.html
│           └── trend_card.html
└── interfaces/
    └── mcp/
        └── server.py
```
