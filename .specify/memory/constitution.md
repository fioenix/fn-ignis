<!--
Sync Impact Report
- Version change: 1.1.0 -> 2.0.0
- Modified principles:
  - I. Zero-Token Ingress and Separation of Concerns -> I. Mission-Bound Autonomy and Zero-Token Collection
  - II. Pluggable and Isolated Connector Architecture -> II. Pluggable and User-Controlled Connector Architecture
  - III. Storage-First Evidence and Time Semantics -> III. Evidence-First Research and Falsification
  - IV. Deterministic Artifact Builders (clarified as report-source boundary)
  - V. Simplicity, Surgical Changes, and Type Safety (retained)
  - VI. Evidence-Gated Migration and Release (retained)
- Added sections: Product Reasoning Constraints
- Removed sections: none
- Removed commitments: optional always-on worker, scheduled ingress, continuous baseline collection
- Follow-up TODOs: none
-->
# fn-ignis Constitution

This constitution defines the non-negotiable product, architecture, development, and governance
principles for `fn-ignis`.

---

## Core Principles

### I. Mission-Bound Autonomy and Zero-Token Collection (NON-NEGOTIABLE)

- Ignis MUST start collection or analysis only after a user or host agent explicitly assigns a
  task. It MUST NOT run an always-on radar, unattended scheduled sweep, autonomous daily discovery,
  or background collection loop.
- Once assigned a task, Ignis MAY autonomously select and execute the bounded collection and
  analysis steps needed to satisfy that task, subject to connector authorization and evidence
  gates.
- Connectors and ingestion ETL MUST run deterministically without consuming LLM tokens. Agent LLMs
  participate in semantic judgment, strategic reasoning, and artifact presentation, not raw
  collection.
- A completed task MUST stop consuming connector quota and compute. A new task requires a new
  explicit trigger.

### II. Pluggable and User-Controlled Connector Architecture

- Every platform connector MUST implement the connector port and remain independently callable for
  tactical collection or as part of a research mission.
- Circuit breaking and error isolation are required: one platform failure MUST NOT terminate healthy
  connector work or be silently reported as complete coverage.
- Browser sessions, platform tokens, paid quotas, and other user-controlled resources MUST be used
  only when the task explicitly places them in scope and the repository's authorization boundary is
  satisfied.
- Connector availability, authentication state, rate limits, and missing channels MUST remain
  visible to the user and to downstream evidence qualification.

### III. Evidence-First Research and Falsification

- SQLite is the zero-configuration default; PostgreSQL with optional TimescaleDB is the production
  backend. Behavioral storage contracts MUST run on both.
- Persistence MUST separate one canonical external `source`, each immutable `observation`, and the
  exact `mission_evidence` association that used it. Runtime code MUST NOT maintain a second source
  identity or mission-ownership policy in titles, URLs, or legacy tables.
- Every strategic claim MUST trace to the mission evidence frame that supports it. Missing channels,
  failed probes, sample limits, and contradictory observations MUST remain first-class evidence.
- A mission MUST actively test its core hypothesis against counterevidence and at least one credible
  alternative explanation. It MUST NOT treat confirmation of the user's initial belief as the goal.
- Evidence qualification and verdict generation MUST fail closed: when required evidence is absent
  or insufficient, Ignis MUST return the gap and the next validation action instead of manufacturing
  certainty.
- Time-window queries MUST use an ingestion clock whose provenance is exact. Publication time is a
  separate fact and MUST NOT silently substitute for ingestion time. Legacy observations whose
  ingestion time was never recorded keep `observed_at = NULL` with explicit provenance.

### IV. Deterministic Artifact Builders

- The MCP server MUST use maintained builders and templates for runtime HTML reports.
- HTML templates in `src/ignis/infrastructure/templates/html/` are the only report source committed
  as code. Agents MUST NOT regenerate a report's full HTML/CSS ad hoc.
- Standalone documentation diagrams MAY live outside the report-template directory when they are not
  runtime report sources. HTML remains the canonical diagram source; exported SVG/PNG MAY be embedded
  in documents, and parallel Mermaid sources are prohibited.
- Builders and templates MUST preserve layout fidelity, reproducibility, accessible output, and the
  vendored FINOLABS design tokens.

### V. Simplicity, Surgical Changes, and Type Safety

- Runtime support is Python 3.11+ with explicit type hints and typed domain models where practical.
- New behavior MUST use the minimum coherent change needed to satisfy a measured contract. The
  project MUST NOT add speculative abstractions, workflows, or configuration.
- Domain vocabulary MUST remain data-driven and runtime-extensible; source code MUST NOT hard-code
  market terms, brand names, synonyms, or intent vocabularies.
- Contract changes MUST identify every consumer and prove behavioral parity or an intentional
  breaking boundary before release.

### VI. Evidence-Gated Migration and Release

- A migration that transforms persisted evidence MUST publish its projection, counts, invariants,
  and deterministic digest before production data is changed.
- Production baselines MUST come from the exact quiesced snapshot being migrated. A tracked rehearsal
  baseline documents policy; it is not a production reference.
- Runtime safety guards are fail-closed backstops, not permission to violate the documented migration
  sequence.
- Work is not shipped until it is merged, deployed, migrated where required, verified from the
  production or public surface, and activated.

---

## Product Reasoning Constraints

- **Outcome thinking:** Every mission, feature, and plan MUST state the decision outcome first and
  define observable evidence that proves the outcome was reached. Steps that cannot trace to that
  outcome MUST be removed.
- **Design thinking:** Ignis MUST be designed for the person making the decision. Research flows MUST
  expose collection cost, friction, missing data, and the next useful action instead of optimizing
  only for technical completeness.
- **Critical thinking:** Every mission MUST make assumptions explicit, search for disconfirming
  evidence, preserve competing explanations, and separate observation from inference.

The initial product beachhead is founder, operator, analyst, consultant, and small consumer-market
teams researching Vietnam. This constrains the first validation corpus and language experience; it
does not authorize claims of universal geographic or industry coverage.

---

## Technology Constraints

- **Language and runtime:** Python >= 3.11; `uv` is the preferred package manager.
- **Persistence:** SQLite or PostgreSQL 16; TimescaleDB and pgvector are optional backend
  capabilities, not requirements for zero-configuration operation.
- **Protocol:** Model Context Protocol through FastMCP.
- **Ingress libraries:** `google-api-python-client`, `feedparser`, `httpx`, and `playwright` where a
  user-requested connector requires a browser.
- **Artifacts:** maintained single-file HTML templates using the vendored FINOLABS design tokens.

---

## Governance and Spec-Driven Development

Large features use the Spec Kit artifact chain:

1. `/speckit-specify` — requirements and acceptance scenarios.
2. `/speckit-plan` — technical decisions and architecture.
3. `/speckit-tasks` — dependency-ordered work items.
4. `/speckit-implement` — implementation and tests.
5. `/speckit-converge` — code-to-spec gap assessment.

An amendment requires an explicit owner decision, a documented impact report, and a semantic version
bump: MAJOR for incompatible governance changes, MINOR for new or materially expanded guidance, and
PATCH for non-semantic clarification. Architecture and product ADRs MUST be reconciled with the
constitution; a superseded ADR remains in history and names the newer decision that replaces it.

Every plan and pull request MUST evaluate constitution compliance. An exception MUST identify who
pays the cost, its expiry condition, and the owner approval that permits it. Tests, configuration,
labels, and remembered command output are not evidence by themselves: run the command against the
surface that owns the claim, read the output, and record what was not checked.

**Version**: 2.0.0 | **Ratified**: 2026-08-31 | **Last Amended**: 2026-09-29
