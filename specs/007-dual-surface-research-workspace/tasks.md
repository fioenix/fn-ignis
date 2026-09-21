# Tasks: Dual-Surface Research Workspace

**Input**: Design documents from `/specs/007-dual-surface-research-workspace/`

**Prerequisites**: `plan.md`, `spec.md`, `research.md`, `data-model.md`, `contracts/`,
`ownership.md`, and
`quickstart.md`

**Organization**: Tasks are grouped by user story so each story can be implemented and tested as
an independently demonstrable increment.

## Delivery ownership

- **PO — Codex:** P-001 through P-005 in `ownership.md` are complete. Codex owns product
  acceptance, ambiguity decisions, P2 promotion, and release scope.
- **Engineering — Claude Code:** T001-T023 are the first implementation handoff. T024-T033 are
  P2 hardening. T034-T037 are final quality, documentation, and release-gate work.
- Engineering must return a decision request when code encounters a product ambiguity. It must
  not persist Q&A drafts, create a second mission identity, or publish a release as a workaround.

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Establish the local-first workspace boundary and feature test locations.

- [x] T001 Add `.ignis/research/` to the repository ignore policy and document the local-first rule in `.gitignore` and `docs/decisions/2026-09-21-dual-surface-research-workspace.md` (touches: `.gitignore`, decision note; depends-on: none)
- [x] T002 [P] Add feature test module placeholders and shared fixtures for temporary host workspaces in `tests/unit/test_research_workspace.py`, `tests/unit/test_surface_boundaries.py`, `tests/integration/test_research_workspace_lifecycle.py`, `tests/integration/test_dual_surface_journey.py`, and `tests/integration/test_workspace_concurrency.py` (touches: listed test files; depends-on: none)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Build the canonical workspace, surface, Brief, provenance, and writer boundaries
that all user stories depend on.

- [x] T003 [P] Define workspace, surface, mission-lineage, and Brief value objects in `src/ignis/domain/research_workspace.py` with typed validation for `ATTENTION`, `MARKET`, and the seven required Brief fields (touches: `src/ignis/domain/research_workspace.py`; depends-on: T002)
- [x] T004 [P] Define workspace lifecycle and canonical-store ports in `src/ignis/application/ports/research_workspace_port.py`, including proposal, confirmation, reuse, adoption, and reopen operations (touches: `src/ignis/application/ports/research_workspace_port.py`; depends-on: T003)
- [x] T005 Add the workspace manifest, research metadata, Brief revision, surface lineage, and run-journal tables to the shared schema, extend the existing `research_missions` record with workspace/surface/lineage fields, and enforce equivalent SQLite/PostgreSQL constraints without duplicating source/observation/mission-evidence identity rules (touches: `sql/017_research_workspace.sql`, `src/ignis/resources.py`, `src/ignis/infrastructure/persistence/sqlite_repository.py`, `src/ignis/infrastructure/persistence/postgres_repository.py`, `src/ignis/domain/entities.py`; depends-on: T003)
- [x] T006 Implement workspace-scoped access against the configured shared database in `src/ignis/infrastructure/persistence/workspace_repository.py`, reusing the existing repository port and selecting SQLite-local by default or PostgreSQL from configuration (touches: `src/ignis/infrastructure/persistence/workspace_repository.py`, `src/ignis/infrastructure/persistence/sqlite_repository.py`, `src/ignis/infrastructure/persistence/postgres_repository.py`; depends-on: T004, T005)
- [x] T007 Implement path containment, slug validation, manifest compatibility, and non-destructive adoption guards in `src/ignis/application/use_cases/create_research_workspace.py` (touches: `src/ignis/application/use_cases/create_research_workspace.py`; depends-on: T004, T006)
- [x] T008 Implement per-mission single-writer coordination and transaction boundaries in `src/ignis/infrastructure/persistence/workspace_repository.py`, preserving the exclusive journal creation pattern from `scripts/t020_cutover.py` (touches: `src/ignis/infrastructure/persistence/workspace_repository.py`, `scripts/t020_cutover.py`; depends-on: T006)

**Checkpoint**: The workspace can be proposed, confirmed, reopened, and guarded without any
surface-specific analysis.

---

## Phase 3: User Story 1 - Create a Scoped Research Workspace (Priority: P1) 🎯 MVP

**Goal**: Create or safely reopen `.ignis/research/<research-slug>/` only after requester
confirmation and keep its shared-database scope addressable.

**Independent Test**: Run the lifecycle scenarios in `quickstart.md` section 1, including no
write before confirmation, matching-manifest reuse, and explicit adoption of a non-empty folder.

### Tests for User Story 1

- [x] T009 [P] [US1] Add unit tests for proposal-only behavior, path containment, slug validation, matching-manifest reuse, incompatible manifests, and non-empty-folder adoption in `tests/unit/test_research_workspace.py` (touches: `tests/unit/test_research_workspace.py`; depends-on: T007)
- [x] T010 [P] [US1] Add integration tests for create, reopen from a second host using the same shared database, cancel, and adopt flows in `tests/integration/test_research_workspace_lifecycle.py` (touches: `tests/integration/test_research_workspace_lifecycle.py`; depends-on: T007)

### Implementation for User Story 1

- [x] T011 [US1] Expose workspace proposal, confirmation, reuse, and adoption results through typed handlers in `src/ignis/interfaces/mcp/server.py` using the contract in `specs/007-dual-surface-research-workspace/contracts/workspace-and-mission.md` (touches: `src/ignis/interfaces/mcp/server.py`; depends-on: T009, T010)
- [x] T012 [US1] Add manifest and workspace identity readback to the existing setup/diagnostic path in `src/ignis/interfaces/cli/setup_bundle.py` without creating a research workspace implicitly (touches: `src/ignis/interfaces/cli/setup_bundle.py`; depends-on: T011)

**Checkpoint**: US1 is independently demonstrable: the user can create and reopen a scoped
research workspace through the shared Ignis database, and no unconfirmed folder is created.

---

## Phase 4: User Story 2 - Explore Attention Without a Market Thesis (Priority: P1)

**Goal**: Run an exploratory Attention mission without a hypothesis, and return transparent
attention evidence without a Market verdict.

**Independent Test**: Run the Attention-only journey in `quickstart.md` section 2 and verify no
Market Brief or Opportunity Index is required or emitted.

### Tests for User Story 2

- [x] T013 [P] [US2] Add unit tests for surface immutability, hypothesis-free Attention creation, and Opportunity Index exclusion in `tests/unit/test_surface_boundaries.py` (touches: `tests/unit/test_surface_boundaries.py`; depends-on: T003)
- [x] T014 [P] [US2] Add integration tests for ranked Attention output, observation-addressable citations, connector-surface states, and candidate handoff metadata in `tests/integration/test_dual_surface_journey.py` (touches: `tests/integration/test_dual_surface_journey.py`; depends-on: T011)

### Implementation for User Story 2

- [x] T015 [US2] Add Attention mission creation and workspace binding in `src/ignis/application/use_cases/create_attention_mission.py`, reusing existing mission ingress ports instead of duplicating connector logic (touches: `src/ignis/application/use_cases/create_attention_mission.py`, `src/ignis/application/use_cases/create_mission.py`; depends-on: T006, T013)
- [x] T016 [US2] Make mission analysis surface-aware in `src/ignis/application/use_cases/get_mission_analysis.py` and `src/ignis/infrastructure/harness/strategic_reasoner.py`, keeping momentum/freshness/coverage visible and suppressing Opportunity Index for Attention (touches: `src/ignis/application/use_cases/get_mission_analysis.py`, `src/ignis/infrastructure/harness/strategic_reasoner.py`; depends-on: T015)
- [x] T017 [US2] Add Attention response serialization and connector-surface citation classification in `src/ignis/interfaces/mcp/server.py` and `src/ignis/infrastructure/templates/html/mission_report.html` without changing the existing deterministic builder contract (touches: `src/ignis/interfaces/mcp/server.py`, `src/ignis/infrastructure/templates/html/mission_report.html`; depends-on: T014, T016)

**Checkpoint**: US2 is independently demonstrable: Attention can discover and rank topics while
making no commercial claim.

---

## Phase 5: User Story 3 - Frame and Run a Market Investigation (Priority: P1)

**Goal**: Require a requester-confirmed, falsifiable Market Brief before Market probes run.

**Independent Test**: Run the direct Market journey in `quickstart.md` section 3, including the
blocked incomplete Brief and the confirmed run.

### Tests for User Story 3

- [x] T018 [P] [US3] Add unit tests for all seven required Brief fields, non-empty falsifiers, edit-before-confirmation, immutable confirmation metadata, and abandoned-Q&A non-persistence in `tests/unit/test_market_brief.py` (touches: `tests/unit/test_market_brief.py`; depends-on: T003, T005)
- [x] T019 [P] [US3] Add integration tests for direct Market gating, confirmed Brief persistence, and Market analysis output in `tests/integration/test_dual_surface_journey.py` (touches: `tests/integration/test_dual_surface_journey.py`; depends-on: T011, T018)

### Implementation for User Story 3

- [x] T020 [US3] Implement Brief validation and confirmation in `src/ignis/application/use_cases/confirm_market_brief.py`, persisting only confirmed revisions and creating the authorized Market mission (touches: `src/ignis/application/use_cases/confirm_market_brief.py`; depends-on: T005, T018)
- [x] T021 [US3] Gate Market execution on a confirmed Brief in `src/ignis/application/use_cases/execute_mission.py` and `src/ignis/application/use_cases/create_mission.py`, returning explicit missing-field errors (touches: `src/ignis/application/use_cases/execute_mission.py`, `src/ignis/application/use_cases/create_mission.py`; depends-on: T020)
- [x] T022 [US3] Expose Brief confirmation and Market execution contracts through `src/ignis/interfaces/mcp/server.py`, keeping adaptive Q&A in Agent context rather than server persistence (touches: `src/ignis/interfaces/mcp/server.py`; depends-on: T019, T021)
- [x] T023 [US3] Ensure Market analysis and artifacts include Brief revision identity, falsifiers, connector-surface states, observation-addressable citations for opportunities and actionable takeaways, and Opportunity Index only for Market missions in `src/ignis/application/use_cases/get_mission_analysis.py`, `src/ignis/infrastructure/harness/strategic_reasoner.py`, and `src/ignis/infrastructure/templates/html/mission_report.html` (touches: listed files; depends-on: T016, T022; absorbs the P1 portion of `specs/004-fastmcp-server-and-artifacts/tasks.md` T009)

**Checkpoint**: US3 is independently demonstrable: incomplete Market framing cannot run, while a
confirmed Brief produces a traceable Market mission and Market-only Opportunity Index.

---

## Phase 6: User Story 4 - Handoff and Revise Without Rewriting History (Priority: P2)

**Goal**: Create explicit Attention-to-Market lineage and immutable Market revisions with fresh
probes.

**Independent Test**: Run `quickstart.md` section 4 and verify separate missions, lineage, and
unchanged earlier evidence.

### Tests for User Story 4

- [ ] T024 [P] [US4] Add unit tests for Attention parent/cluster lineage, immutable Brief revision numbers, and context-versus-support evidence roles in `tests/unit/test_market_brief.py` and `tests/unit/test_surface_boundaries.py` (touches: listed test files; depends-on: T020, T023)
- [ ] T025 [P] [US4] Add integration tests for Attention handoff, Market revision, fresh probe authorization, and old-evidence immutability in `tests/integration/test_dual_surface_journey.py` (touches: `tests/integration/test_dual_surface_journey.py`; depends-on: T020, T023)

### Implementation for User Story 4

- [ ] T026 [US4] Implement explicit Attention-topic handoff in `src/ignis/application/use_cases/create_market_revision.py`, recording parent mission and cluster as context lineage (touches: `src/ignis/application/use_cases/create_market_revision.py`; depends-on: T015, T024)
- [ ] T027 [US4] Implement immutable Market Brief revision creation and fresh-probe binding in `src/ignis/application/use_cases/create_market_revision.py` and `src/ignis/infrastructure/persistence/workspace_repository.py` (touches: listed files; depends-on: T020, T026)
- [ ] T028 [US4] Classify Attention context versus Market evidence in `src/ignis/application/use_cases/get_mission_analysis.py`, `src/ignis/infrastructure/harness/strategic_reasoner.py`, and `src/ignis/interfaces/mcp/server.py` (touches: listed files; depends-on: T025, T027)

**Checkpoint**: US4 is independently demonstrable: changing a Market Brief creates a new
evidence line and never rewrites the earlier one.

---

## Phase 7: User Story 5 - Preserve Research Integrity During Concurrent Work (Priority: P2)

**Goal**: Allow independent missions to run concurrently while enforcing one writer per mission
and exclusive journals.

**Independent Test**: Run `quickstart.md` section 5 with concurrent distinct missions, a same-
mission conflict, and a frozen same-second clock.

### Tests for User Story 5

- [ ] T029 [P] [US5] Add unit tests for one-writer mission claims, transactional state transitions, and clear conflict errors in `tests/unit/test_research_workspace.py` and `tests/unit/test_surface_boundaries.py` (touches: listed test files; depends-on: T008)
- [ ] T030 [P] [US5] Add integration tests for concurrent distinct missions, same-mission conflict, and same-second journal allocation in `tests/integration/test_workspace_concurrency.py` (touches: `tests/integration/test_workspace_concurrency.py`; depends-on: T008)

### Implementation for User Story 5

- [ ] T031 [US5] Complete transactional mission state updates and workspace read/write coordination in `src/ignis/infrastructure/persistence/workspace_repository.py` without serializing unrelated missions (touches: `src/ignis/infrastructure/persistence/workspace_repository.py`; depends-on: T029, T030)
- [ ] T032 [US5] Integrate collision-safe journal creation and recovery readback into the mission execution path in `src/ignis/application/use_cases/execute_mission.py` and `src/ignis/infrastructure/persistence/workspace_repository.py` (touches: listed files; depends-on: T031)
- [ ] T033 [US5] Verify multi-host reopen and concurrent mission behavior through the MCP contract and the shared configured database in `src/ignis/interfaces/mcp/server.py` and `tests/integration/test_workspace_concurrency.py` (touches: listed files; depends-on: T032)

**Checkpoint**: US5 is independently demonstrable: no concurrent run loses state or overwrites a
journal, and unrelated missions are not globally blocked.

---

## Phase 8: Polish & Cross-Cutting Concerns

**Purpose**: Close documentation, quality, and regression gates after all required stories pass.

- [ ] T034 [P] Update the permanent user/developer documentation for workspace lifecycle and surface boundaries in `docs/USER_GUIDE.md`, `docs/USER_GUIDE.vi.md`, and `README.md` (touches: listed files; depends-on: T012, T017, T023, T028)
- [ ] T035 [P] Add repository convention and provenance assertions for workspace-local data, no transcript persistence, and Attention/Market separation in `tests/unit/test_repo_conventions.py` and `tests/unit/test_data_provenance.py` (touches: listed test files; depends-on: T028, T033)
- [ ] T036 Run the feature quickstart and both-backend verification gates, record skipped PostgreSQL coverage honestly when `IGNIS_TEST_POSTGRES_DSN` is absent, and inspect the final diff in `.handoff/` only if a temporary handoff artifact is needed (touches: `specs/007-dual-surface-research-workspace/quickstart.md`; depends-on: T034, T035)
- [ ] T037 Prepare the evidence-gated production migration rehearsal and verification record for the new shared schema, including projection/count/invariant/digest outputs and an explicit no-apply-without-authorization boundary (touches: `.handoff/`, `scripts/`, `specs/007-dual-surface-research-workspace/quickstart.md`; depends-on: T036)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: T001-T002 have no implementation dependency and can begin immediately.
- **Foundational (Phase 2)**: T003-T008 depend on the setup fixtures and block all user stories.
- **User Stories (Phases 3-7)**: Each story depends on Phase 2. US2 and US3 can proceed in
  parallel after the foundation; US4 depends on US2 and US3; US5 depends on the foundational
  writer/journal work and integrates with the completed mission paths.
- **Polish (Phase 8)**: Depends on all selected stories being green.

### User Story Dependencies

- **US1 (P1)**: Foundation only; MVP workspace lifecycle.
- **US2 (P1)**: Foundation plus US1's workspace binding.
- **US3 (P1)**: Foundation plus US1's workspace binding; independent of US2 for direct Market.
- **US4 (P2)**: Depends on US2 Attention lineage and US3 Brief/Market persistence.
- **US5 (P2)**: Depends on Foundation and the mission execution path from US2/US3.

### Parallel Opportunities

- T003 and T004 can proceed in parallel after test fixture setup.
- T009 and T010 can proceed in parallel after the workspace use case exists.
- T013/T014 and T018/T019 can proceed in parallel after workspace binding is available.
- T024/T025 and T029/T030 can proceed in parallel once their story prerequisites exist.
- T034 and T035 can proceed in parallel after the respective story checkpoints.

## Parallel Example: P1 MVP

```text
T009  Workspace unit tests       -> T011 MCP lifecycle contract
T010  Workspace integration tests -> T011 MCP lifecycle contract
T011  Confirm/reopen contract     -> T012 setup readback
```

After US1 is green, two implementers can work in parallel:

```text
US2: Attention mission + surface-specific analysis
US3: Market Brief confirmation + execution gate
```

## Implementation Strategy

### MVP First

1. Complete Setup and Foundational phases.
2. Complete US1 so research state has a confirmed workspace boundary and shared-database scope.
3. Validate US1 independently and stop before adding analytical surfaces if the workspace
   contract is not green.

### Incremental Delivery

1. Add US2 Attention discovery and validate that it never emits Market conclusions.
2. Add US3 direct Market framing and confirmed Brief gating.
3. Add US4 Attention-to-Market handoff and immutable revisions.
4. Add US5 concurrency/recovery hardening.
5. Run Polish gates and update user/developer documentation.

Each increment must preserve the existing source/observation/mission-evidence provenance model,
run its workspace-scoping checks against SQLite and PostgreSQL where the DSN is available, and
must not be called shipped until integrated and verified.

## Notes

- Every task includes exact paths plus `touches:` and `depends-on:` to keep the plan executable.
- Test tasks are included because the feature specification defines independent acceptance
  scenarios and the repository's evidence contract requires reproducible checks.
- No task adds a connector, changes the Opportunity Index formula, or publishes research artifacts
  automatically. The shared schema task requires the existing production migration gate before
  any production activation.
