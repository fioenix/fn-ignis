# Implementation Plan: Dual-Surface Research Workspace

**Branch**: `007-dual-surface-research-workspace` | **Date**: 2026-09-21 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/007-dual-surface-research-workspace/spec.md`

## Summary

Add a workspace-scoped research boundary with two independent analytical surfaces. The Agent
host remains responsible for chat-session context and interactive Q&A; fn-ignis persists the
confirmed Market Brief, missions, observations, evidence links, run journals, and artifacts in
one user-visible child workspace. All Ignis research uses one configured shared database: local
SQLite by default or PostgreSQL when explicitly configured. Research records are scoped by
`workspace_id`, preserve the existing source/observation/mission-evidence provenance model, and
prevent Attention signals from being presented as Market evidence.

## Technical Context

**Language/Version**: Python >= 3.11

**Primary Dependencies**: Existing FastMCP interfaces, Pydantic domain models, Python stdlib
SQLite, and the existing connector/repository ports

**Storage**: One configured database shared by the Ignis installation: SQLite-local by default or
PostgreSQL when explicitly configured. Research-owned tables are scoped by `workspace_id`; the
manifest, journals, and derived artifacts remain under `.ignis/research/<research-slug>/`

**Testing**: pytest and pytest-asyncio unit/integration tests; repository parity tests remain
required for the existing SQLite/PostgreSQL storage contract

**Target Platform**: Local Agent hosts using the FastMCP server and the current writable workspace

**Project Type**: Python MCP server and Agent harness with local research persistence

**Performance Goals**: Preserve the existing P95 < 50 ms target for trend reads where the new
workspace repository participates; workspace orchestration must add no LLM calls to ingress

**Constraints**: No durable files before workspace confirmation; no abandoned Q&A transcript;
confirmed Briefs are immutable; all research records remain isolated inside the shared database;
missing or degraded connector data remains explicit; concurrent runs must not overwrite journals
or state

**Scale/Scope**: One shared Ignis database with multiple research scopes, each containing multiple
missions and concurrent distinct mission readers/writers; one active writer per mission; no new
connectors or Opportunity Index formula changes

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Plan compliance |
|---|---|---|
| I. Zero-Token Ingress and Separation of Concerns | PASS | Workspace lifecycle and Market Brief validation do not add LLM work to connector ingress; the Agent host may conduct Q&A, while ingestion remains deterministic. |
| II. Pluggable and Isolated Connector Architecture | PASS | Existing connector ports and failure isolation remain unchanged; the workspace binds missions to the existing ingress path. |
| III. Storage-First Evidence and Time Semantics | PASS | SQLite-local is the default and PostgreSQL is an optional backend for the same shared Ignis database contract. Workspace scoping is enforced through `workspace_id`; source, immutable observation, and mission-evidence rules remain unchanged and are verified on both backends. |
| IV. Deterministic Artifact Builders | PASS | Market and Attention artifacts continue through maintained builders; this feature adds lineage and destination context, not ad hoc HTML generation. |
| V. Simplicity, Surgical Changes, and Type Safety | PASS | Reuse existing repository and domain ports; add only workspace, surface, Brief, and lifecycle state needed by the accepted contract. |
| VI. Evidence-Gated Migration and Release | PASS with migration gate | The shared schema requires a versioned migration and SQLite/PostgreSQL parity verification. No production migration is activated without the existing projection/count/digest gate. |

## Project Structure

### Documentation (this feature)

```text
specs/007-dual-surface-research-workspace/
├── plan.md              # This file
├── research.md          # Phase 0 decisions and alternatives
├── data-model.md        # Phase 1 entities and state transitions
├── quickstart.md        # Phase 1 validation guide
├── contracts/           # Phase 1 host/Agent interface contracts
└── tasks.md             # Phase 2 dependency-ordered implementation tasks
```

### Source Code (repository root)

```text
src/ignis/
├── domain/
│   ├── entities.py                         # Existing mission/observation entities; extend only where needed
│   └── research_workspace.py                # Workspace, surface, Brief, and lineage value objects
├── application/
│   ├── ports/
│   │   ├── repository_port.py              # Existing evidence/repository contract
│   │   └── research_workspace_port.py      # Workspace lifecycle and canonical-store boundary
│   └── use_cases/
│       ├── create_research_workspace.py    # Propose, confirm, reuse, or reject a child workspace
│       ├── create_attention_mission.py      # Exploratory surface
│       ├── confirm_market_brief.py          # Persist only a confirmed Brief revision
│       └── create_market_revision.py        # Immutable revision and fresh Market mission
├── infrastructure/
│   ├── persistence/
│   │   ├── sqlite_repository.py             # Shared SQLite backend
│   │   ├── postgres_repository.py           # Shared PostgreSQL backend
│   │   └── workspace_repository.py          # Workspace scope, manifest, locking, and journals
│   └── templates/html/                      # Existing deterministic artifact builders
└── interfaces/mcp/server.py                 # Workspace and surface command contracts

tests/
├── integration/
│   ├── test_research_workspace_lifecycle.py
│   ├── test_dual_surface_journey.py
│   └── test_workspace_concurrency.py
└── unit/
    ├── test_research_workspace.py
    ├── test_market_brief.py
    └── test_surface_boundaries.py
```

**Structure Decision**: Keep domain rules in `src/ignis/domain`, orchestration in use cases,
workspace persistence behind an application port, and MCP serialization in the existing server.
Extend the current evidence repository rather than creating a parallel source/observation model.
Keep all feature tests under the existing unit/integration split and exercise the real temporary
workspace filesystem for lifecycle and collision cases.

## Phase 0 Research Summary

The repository already provides a typed domain layer, separate application use cases, FastMCP
handlers, SQLite and PostgreSQL repositories, and explicit source/observation/mission-evidence
tables. The plan reuses those seams. The accepted product decision resolves the main design
unknowns: workspace ownership, shared backend selection, surface separation, immutable Brief
revisions, and per-mission writer ownership. No external library research is required before
Phase 1 because the implementation is constrained to the repository's existing ports and
backend parity contract.

## Phase 1 Design Gate

After `research.md`, `data-model.md`, the contracts, and `quickstart.md` are reviewed, re-run the
constitution check above. The design must still show that:

- the shared database does not create a second source/observation identity and every research
  record is scoped by `workspace_id`;
- no Market claim can be supported only by Attention context;
- no abandoned Q&A transcript reaches canonical storage; and
- concurrent runs use exclusive journals and transactional state updates.

No connector addition or release/version bump is part of this feature plan. Any shared-schema
migration must pass the existing production migration gate before activation.
