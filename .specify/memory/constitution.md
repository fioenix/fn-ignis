# fn-ignis Constitution

This constitution defines the non-negotiable architecture, development, and governance principles
for `fn-ignis`.

---

## Core Principles

### I. Zero-Token Ingress and Separation of Concerns (NON-NEGOTIABLE)

- Connectors and ingestion ETL MUST run deterministically without consuming LLM tokens.
- The optional background worker MUST operate independently of an agent-client lifecycle.
- Agent LLMs participate in semantic synthesis, strategic reasoning, and artifact presentation, not
  raw collection.

### II. Pluggable and Isolated Connector Architecture

- Every platform connector MUST implement the connector port and remain independently callable.
- Circuit breaking and error isolation are required: one platform failure MUST NOT terminate
  healthy connector work.
- Scheduled ingress may use only connector runtimes available in the worker environment. Browser
  surfaces remain on-demand unless the connector exposes an HTTP tier.

### III. Storage-First Evidence and Time Semantics

- SQLite is the zero-configuration default; PostgreSQL with optional TimescaleDB is the production
  backend. Behavioral storage contracts MUST run on both.
- Persistence MUST separate one canonical external `source`, each immutable `observation`, and the
  exact `mission_evidence` association that used it. Runtime code MUST NOT maintain a second source
  identity or mission-ownership policy in titles, URLs, or legacy tables.
- PostgreSQL time-series data SHOULD use TimescaleDB where its partition contract preserves the
  evidence honestly. It MUST NOT become a hypertable when doing so would require inventing a
  non-null clock. In particular, legacy observations whose ingestion time was never recorded keep
  `observed_at = NULL` with explicit provenance.
- Time-window queries MUST use an ingestion clock whose provenance is exact. Publication time is a
  separate fact and MUST NOT silently substitute for ingestion time.
- Trend queries exposed through MCP SHOULD use appropriate indexes and retain the P95 < 50 ms
  target. A target is not reported as achieved without a reproducible benchmark.

### IV. Deterministic Artifact Builders

- The MCP server uses maintained builders and templates for HTML artifacts.
- Agents MUST NOT regenerate an artifact's full HTML/CSS ad hoc; deterministic builders protect
  layout fidelity, repeatability, and token cost.
- HTML is the source format for diagrams in this repository. Exported SVG/PNG may be embedded in
  documents; Mermaid is not used because parallel diagram sources have already drifted.

### V. Simplicity, Surgical Changes, and Type Safety

- Runtime support is Python 3.11+ with explicit type hints and typed domain models where practical.
- Do not add speculative abstractions or configuration (YAGNI).
- Changes MUST be the minimum coherent set needed to satisfy a measured contract.

### VI. Evidence-Gated Migration and Release

- A migration that transforms persisted evidence MUST publish its projection, counts, invariants,
  and deterministic digest before production data is changed.
- Production baselines MUST come from the exact quiesced snapshot being migrated. A tracked
  rehearsal baseline documents policy; it is not a production reference.
- Runtime safety guards are fail-closed backstops, not permission to violate the documented
  migration sequence.
- Work is not shipped until it is merged, deployed, migrated where required, verified from the
  production surface, and activated.

---

## Technology Constraints

- **Language and runtime:** Python >= 3.11; `uv` is the preferred package manager.
- **Persistence:** SQLite or PostgreSQL 16; TimescaleDB and pgvector are optional backend
  capabilities, not requirements for zero-configuration operation.
- **Protocol:** Model Context Protocol through FastMCP.
- **Ingress libraries:** `google-api-python-client`, `feedparser`, `httpx`, and `playwright` where
  the connector runtime requires a browser.
- **Artifacts:** maintained single-file HTML templates using the vendored FINOLABS design tokens.

---

## Governance and Spec-Driven Development

Large features use the Spec Kit artifact chain:

1. `/speckit-specify` — requirements and acceptance scenarios.
2. `/speckit-plan` — technical decisions and architecture.
3. `/speckit-tasks` — dependency-ordered work items.
4. `/speckit-implement` — implementation and tests.
5. `/speckit-converge` — code-to-spec gap assessment.

Tests, configuration, labels, and remembered command output are not evidence by themselves. Run the
command against the surface that owns the claim, read the output, and record what was not checked.

**Version**: 1.1.0 | **Ratified**: 2026-08-31 | **Last Amended**: 2026-09-13
