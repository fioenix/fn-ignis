# Implementation Plan: FastMCP Server & Deterministic Artifacts

**Feature Directory**: `specs/004-fastmcp-server-and-artifacts`
**Date**: 2026-08-31
**Spec**: [spec.md](./spec.md)

---

## Technical Context

- **MCP Framework**: `fastmcp>=0.4.0`
- **Tool contract**: 39 independently callable tools; the original four remain stable entry points
- **Template Engine**: `jinja2`
- **Frontend Stack**: Tailwind CSS CDN, Chart.js / Recharts responsive charts
- **Delivery**: Return full HTML string formatted as MCP content / artifact
- **Runtime boundary**: This plan covers the open-source local standard-input/output process and
  local artifact delivery. Hosted HTTP transport, Google OAuth, authorization, and remote artifact
  retrieval belong exclusively to feature 006.
- **Evidence boundary**: channel summaries and strategic-insight citations are serialized today;
  exact observation references plus opportunity/actionable citations remain the convergence gap

---

## Structure

```text
src/ignis/
├── domain/
│   └── harness_models.py
├── application/
│   └── ports/artifact_port.py
├── infrastructure/
│   ├── harness/strategic_reasoner.py
│   └── templates/
│       ├── html_builder.py
│       └── html/mission_report.html
└── interfaces/
    └── mcp/
        └── server.py
```

`CitationEvidence.observation_id` is the target identity boundary. URL and title remain display
payload and must not become another deduplication policy beside the source resolver and mission
evidence ledger.

The local and hosted delivery modes reuse the same MCP handlers. Feature 006 may add transport and
policy adapters around those handlers, but it must not fork their business behavior.
