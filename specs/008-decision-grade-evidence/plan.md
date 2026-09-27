# Implementation Plan: Decision-Grade Evidence Qualification

**Branch**: `008-decision-grade-evidence` | **Date**: 2026-09-25 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/008-decision-grade-evidence/spec.md`

## Summary

Make the first mission after startup load the same database-backed vocabulary as later missions,
then add an immutable, mission-scoped evidence-qualification boundary between raw observations and
strategic conclusions. The host Agent performs the semantic judgment through a typed MCP contract;
Ignis validates and persists those judgments, computes evidence sufficiency deterministically, and
withholds handoff candidates, Market verdicts, confidence, and Opportunity Index output when the
qualified evidence does not meet the product minimum.

The server gains no required AI-provider dependency. TypeSafe's `Choice` and `Noul` primitives are
the recommended host-side judgment shape, but any Agent host may submit the same typed contract.

## Technical Context

**Language/Version**: Python 3.11 through 3.14

**Primary Dependencies**: FastMCP, Pydantic, existing connector registry and deterministic harness;
no new required runtime dependency

**Storage**: Shared SQLite-local or PostgreSQL 16 database; migration `023` adds mission probe
outcomes and evidence qualifications

**Testing**: pytest unit and dual-backend integration contracts; real PostgreSQL parity; Compose
fresh-init migration contract; deterministic HTML artifact assertions

**Target Platform**: Self-hosted MCP server and optional worker on macOS or Linux

**Project Type**: Single Python package exposing an MCP server, worker, and deterministic artifacts

**Performance Goals**: Qualification batch reads remain bounded to 50 observations; reopening an
already qualified mission performs no semantic re-evaluation; existing SC-001 read-path P95 remains
below 50 ms

**Constraints**: Zero-token deterministic ingress; no raw observation deletion; no required external
AI key; Market verdicts fail closed; SQLite/PostgreSQL behavior parity; legacy missions without a
surface remain unchanged; no persisted prompt transcript

**Scale/Scope**: One qualification row per current mission-evidence association and one probe-outcome
row per connector surface per workspace run; expected mission batches are tens to low hundreds of
observations

## Constitution Check

*GATE: Passed before Phase 0 and re-checked after Phase 1.*

- **I. Zero-Token Ingress**: PASS. Vocabulary loading and connector ingress remain deterministic.
  Semantic judgment occurs after observations are stored and is supplied by the host Agent.
- **II. Pluggable connectors**: PASS. The registry returns a structured per-surface outcome without
  embedding qualification logic in any connector.
- **III. Storage-first evidence**: PASS. Qualifications point to canonical mission-evidence pairs;
  raw observations remain immutable. Both persistence backends receive the same contracts.
- **IV. Deterministic artifacts**: PASS. Existing maintained templates render persisted
  qualification and sufficiency records; Agents do not generate replacement HTML.
- **V. Simplicity and type safety**: PASS. Two typed records and two MCP operations form the minimum
  coherent boundary. The server does not grow a provider abstraction that has no default provider.
- **VI. Evidence-gated migration and release**: PASS. Migration `023` is additive, rehearsed on
  scratch databases, and must publish catalog/readback evidence before any existing database is
  changed. Release work remains separate.

## Project Structure

### Documentation (this feature)

```text
specs/008-decision-grade-evidence/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── evidence-qualification-mcp.md
│   └── qualified-analysis-output.md
└── tasks.md
```

### Source Code (repository root)

```text
sql/
└── 023_evidence_qualification.sql

src/ignis/
├── application/
│   ├── ports/research_workspace_port.py
│   └── use_cases/
│       ├── execute_mission.py
│       ├── get_evidence_qualification_batch.py
│       ├── submit_evidence_qualifications.py
│       └── get_mission_analysis.py
├── domain/
│   ├── harness_models.py
│   └── research_workspace.py
├── infrastructure/
│   ├── config/vocabulary_loader.py
│   ├── connectors/registry.py
│   ├── harness/quality_evaluator.py
│   ├── harness/strategic_reasoner.py
│   ├── persistence/sqlite_repository.py
│   ├── persistence/postgres_repository.py
│   └── templates/
│       ├── html_builder.py
│       └── html/mission_report.html
└── interfaces/mcp/server.py

tests/
├── fixtures/
│   └── decision_grade_evidence.json
├── unit/
│   ├── test_evidence_qualification.py
│   ├── test_surface_boundaries.py
│   ├── test_data_provenance.py
│   └── test_tool_manifests_drift.py
└── integration/
    ├── test_decision_grade_evidence.py
    ├── test_dual_surface_journey.py
    ├── test_postgres_migration_contract.py
    └── test_compose_init.py
```

**Structure Decision**: Extend the existing single-package architecture. Mission-scoped records stay
behind `IResearchWorkspaceStore`; deterministic policy stays in domain/application code; connector
and persistence details remain infrastructure concerns; MCP handlers serialize application results.

## Design

### 1. Cold-start vocabulary boundary

Extract the existing database-to-runtime registration logic from the MCP handler into one reusable
vocabulary synchronizer. `ExecuteMissionUseCase` invokes it before setting a mission to `RUNNING` or
calling the connector registry. Read/analysis handlers may invoke the same idempotent synchronizer,
but no handler call is required to warm the process. A failed required read blocks the mission before
connector work and before a run can claim completion.

### 2. Persist the exact probe outcome

The registry gains a structured search operation that returns both signals and one outcome per
eligible connector surface. Existing ad-hoc callers may keep the list-only operation. A workspace
mission stores the structured outcomes against its run journal before it becomes `COMPLETED`.

This removes current-time connector health from a reopened report. A measured absence is valid only
when the completed run records a healthy, relevant surface with zero collected observations.

### 3. Agent-supplied semantic judgment

The host Agent requests bounded qualification batches. Each batch carries the immutable mission
frame and observations that still lack a judgment. The Agent submits typed outcomes:

- relation: qualified support, context only, or excluded irrelevant;
- evidence purpose: demand, supply, Voice of Customer, or context;
- confidence from `0.0` to `1.0`;
- a bounded reason code; and
- optional evaluator identity/model metadata, never credentials or a prompt transcript.

Low-confidence or failed Agent judgments are submitted or retained as unassessed. The recommended
host implementation asks one `Choice` for relation and purpose plus a `Noul` for direct support of
the mission frame, then maps uncertainty to `UNASSESSED` in code. TypeSafe thresholds are calibrated
by fixtures and are not copied from cookbook examples.

The server validates that every observation belongs to the mission's current evidence ledger and
that the Market Brief revision/frame fingerprint matches. Submission is atomic per batch. Reopening a
completed mission reads the persisted result; it does not call an AI provider.

### 4. Deterministic sufficiency policy

Policy code, not the semantic model, decides whether a verdict is allowed:

- one qualified demand observation is required;
- positive supply requires two qualified observations from two canonical sources;
- zero supply requires two relevant healthy surfaces from the completed run, each with zero
  qualified supply observations;
- unavailable, failed, rate-limited, unauthenticated, context-only, excluded, and unassessed inputs
  never count as zero or support; and
- Attention handoff requires a directly relevant cluster backed by two canonical sources.

The reasoner receives only qualified evidence for Market calculations and conclusion citations.
Macro/news/context observations remain inspectable but cannot alter demand, supply, maturity, or
recommendations.

### 5. Fail-closed analysis and artifacts

Until all current mission evidence is assessed, Market analysis returns `QUALIFICATION_REQUIRED`
with progress and the next qualification operation. When assessment is complete but insufficient,
it returns `INSUFFICIENT_RELEVANT_EVIDENCE`, `opportunity_index_applies: false`, no Market
opportunities, and no strategic conclusion that presents a market verdict.

Attention may still display ranked context, but its handoff status is
`NO_QUALIFIED_CANDIDATE` unless a cluster meets the product minimum. Scorecards and artifacts show
question relevance and all four qualification counts. Market confidence is capped at `LOW` for a
complete but insufficient assessment and `UNRELIABLE` while any required judgment is unassessed.

### 6. Storage and migration

Migration `023` creates:

- `mission_probe_outcomes`, keyed by run and connector surface; and
- `mission_evidence_qualifications`, keyed by mission and observation.

The qualification table references the existing unique `(mission_id, observation_id)` evidence
ledger so pruning evidence also removes its qualification. Both tables are owner-only, have RLS
enabled on PostgreSQL, use `gen_random_uuid()` defaults, and are restated in SQLite bootstrap.
No existing row is semantically backfilled. Existing surfaced missions report qualification
required when reopened; missions with no surface retain their current behavior.

## Phase 0: Research Output

See [research.md](research.md). All technical unknowns are resolved; no `NEEDS CLARIFICATION`
markers remain.

## Phase 1: Design Outputs

- [data-model.md](data-model.md)
- [contracts/evidence-qualification-mcp.md](contracts/evidence-qualification-mcp.md)
- [contracts/qualified-analysis-output.md](contracts/qualified-analysis-output.md)
- [quickstart.md](quickstart.md)

## Post-Design Constitution Re-check

PASS. The design preserves deterministic ingress, keeps semantic inference in the Agent synthesis
layer, stores every decision against canonical evidence, adds no mandatory provider or second source
of truth, and defines dual-backend and migration evidence before implementation.

## Complexity Tracking

No constitution violation requires an exception.
