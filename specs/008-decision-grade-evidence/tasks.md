---

description: "Dependency-ordered implementation tasks for decision-grade evidence qualification"
---

# Tasks: Decision-Grade Evidence Qualification

**Input**: Design documents from `/specs/008-decision-grade-evidence/`

**Prerequisites**: `plan.md`, `spec.md`, `research.md`, `data-model.md`, `contracts/`, `quickstart.md`

**Tests**: Required. Every behavior change follows RED → GREEN, including semantic negative controls
and SQLite/PostgreSQL parity.

**Organization**: Tasks are grouped by user story so each story can be implemented and verified as
an independent increment after the shared foundation.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel because it touches different files and has no dependency on another
  incomplete task in the same phase.
- **[Story]**: Maps the task to a user story in `spec.md`.
- Every task names the files it changes.

## Phase 1: Setup and Migration Contract

**Purpose**: Establish the additive schema endpoint and make packaging/fresh-init tests fail before
the migration exists.

- [X] T001 Add RED expectations for migration `023`, 19 RLS-enabled public tables, and packaged SQL in `tests/unit/test_sql_packaging.py`, `tests/integration/test_postgres_migration_contract.py`, and `tests/integration/test_compose_init.py`
- [X] T002 Create idempotent PostgreSQL migration `sql/023_evidence_qualification.sql` for `mission_probe_outcomes` and `mission_evidence_qualifications`, including constraints, indexes, composite evidence foreign key, RLS, owner-only ACLs, and `gen_random_uuid()` defaults

**Checkpoint**: Fresh and upgraded PostgreSQL schemas can represent the feature without changing any
existing source, observation, mission evidence, mission, Brief, or journal row.

---

## Phase 2: Foundational Typed Records and Dual-Backend Persistence

**Purpose**: Provide the shared storage and connector-run facts required by every user story.

**CRITICAL**: No user-story implementation begins until this phase passes on SQLite and PostgreSQL.

- [X] T003 Add RED enum/dataclass validation tests for qualification relation, evidence purpose, reason code, probe outcome, frame fingerprint, and invalid combinations in `tests/unit/test_evidence_qualification.py`
- [X] T004 Implement typed qualification, probe-outcome, progress, and sufficiency domain records in `src/ignis/domain/research_workspace.py` and extend `QualityScorecard` fields in `src/ignis/domain/harness_models.py`
- [X] T005 Extend `IResearchWorkspaceStore` with atomic batch qualification and run-outcome read/write contracts in `src/ignis/application/ports/research_workspace_port.py`
- [X] T006 Add RED dual-backend contracts for qualification atomicity, idempotency, frame conflicts, foreign-key ownership, evidence-prune cascade, latest-completed-run selection, and no semantic backfill in `tests/integration/test_decision_grade_evidence.py`
- [X] T007 Implement SQLite schema restatement and persistence methods for both records in `src/ignis/infrastructure/persistence/sqlite_repository.py`
- [X] T008 Implement PostgreSQL persistence methods for both records with equivalent transactions and row decoding in `src/ignis/infrastructure/persistence/postgres_repository.py`
- [X] T009 Add RED registry contracts for per-surface data, empty, failure, auth, rate-limit, and circuit-open outcomes without process-global last-result state in `tests/unit/test_registry.py`
- [X] T010 Refactor connector search to return a typed signals-plus-outcomes result while preserving the existing list-only caller contract in `src/ignis/infrastructure/connectors/registry.py`
- [X] T011 Persist run-scoped probe outcomes before a workspace mission becomes `COMPLETED`, and read only the latest completed run for analysis in `src/ignis/application/use_cases/execute_mission.py`
- [X] T012 Run the Phase 1–2 migration, domain, registry, and dual-backend targeted suites and record exact PostgreSQL skips/failures in `specs/008-decision-grade-evidence/tasks.md`

**Checkpoint**: Canonical evidence can carry stable semantic judgments and historical connector
surface outcomes with identical SQLite/PostgreSQL behavior.

**T012 evidence (27/09/2026, scratch TimescaleDB `pg16` container, `IGNIS_TEST_POSTGRES_DSN` set):**

- Targeted Phase 1-2 suites (`test_sql_packaging`, `test_evidence_qualification`, `test_registry`,
  `test_postgres_migration_contract`, `test_postgres_rls_coverage`,
  `test_decision_grade_evidence`): 119 passed, 0 skipped, 0 failed.
- `tests/unit/`: 1137 passed, 1 skipped (`test_diagram_and_release_claims.py:143`, banner declares
  no unreleased state), 0 failed.
- `tests/integration/`: 515 passed, 3 skipped, 0 failed. Skips: the `[sqlite]` parameter of two
  PostgreSQL-only backfill contracts (`test_backfill_observations.py:275`, `:378`) and the Compose
  opt-in; no PostgreSQL case skipped.
- `IGNIS_TEST_COMPOSE_INIT=1 tests/integration/test_compose_init.py`: 1 passed (every file through
  023 in order, 19 public tables, 0 without RLS, 13 built-in UUID defaults, no leftovers).
- Negative controls: removing 023's `ENABLE ROW LEVEL SECURITY` fails the owner-only contract;
  removing its composite evidence foreign key fails the ownership contract.
- Consumer fix found by the checkpoint: three backfill contracts drop `mission_evidence` to model a
  pre-016 schema and now drop the 023 table first.

---

## Phase 3: User Story 1 - Same First Mission After Every Startup (Priority: P1) MVP

**Goal**: A cold first mission uses the same persisted vocabulary and connector configuration as a
warm mission.

**Independent Test**: Construct a fresh process with persisted vocabulary, run mission ingress as
the first operation, compare it with an otherwise identical warmed process, and inject a vocabulary
read failure that must call zero connectors.

### Tests for User Story 1

- [X] T013 [US1] Add RED cold-versus-warm parity, first-operation TikTok vocabulary, probe-template, and fail-before-connector scenarios in `tests/integration/test_decision_grade_evidence.py`

### Implementation for User Story 1

- [X] T014 [US1] Extract the idempotent database-to-runtime vocabulary registration from MCP handlers into `src/ignis/infrastructure/config/vocabulary_loader.py`
- [X] T015 [US1] Inject and invoke vocabulary synchronization before mission `RUNNING` state and connector search in `src/ignis/application/use_cases/execute_mission.py` and component construction in `src/ignis/interfaces/mcp/server.py`
- [X] T016 [US1] Add handler-level regression coverage proving `execute_mission_ingress` needs no prior analysis call in `tests/unit/test_mcp_server.py` and `tests/integration/test_decision_grade_evidence.py`

**Checkpoint**: US1 is deployable independently as a cold-start correctness fix.

**US1 evidence (27/09/2026):** `-k cold_start` in `test_decision_grade_evidence.py`: 8 passed (4 x
SQLite and PostgreSQL), including the handler-level first operation. RED before T014: the
synchronizer did not exist (ImportError); negative control with the synchronizer disabled
reproduces the validation defect exactly -- TikTok `EMPTY_NO_DATA`/0 and Google probing the bare
keyword once instead of every persisted template. Unit wiring test fails when the server stops
passing the synchronizer. Full suites: unit 1140 passed, 1 skipped; integration 523 passed,
3 skipped (the same `[sqlite]` backfill parameters and the Compose opt-in); no PostgreSQL skip.

---

## Phase 4: User Story 2 - Withhold Unsupported Market Verdicts (Priority: P1)

**Goal**: Market conclusions use only qualified evidence and fail closed when demand or supply
evidence is insufficient.

**Independent Test**: Submit typed judgments for a keyword-matched noise fixture and a relevant
positive control through real MCP handlers; the noise fixture emits no verdict and the control
retains an Opportunity Index with qualified citations only.

### Tests for User Story 2

- [X] T017 [P] [US2] Add RED batch-read and atomic-submit use-case tests, including pagination, stale frame, foreign observation, duplicate observation, conflicting rewrite, and idempotent replay in `tests/unit/test_evidence_qualification.py`
- [X] T018 [P] [US2] Add RED deterministic sufficiency tests for missing demand, positive supply, measured-zero supply, failed/unauthenticated surfaces, source deduplication, and unassessed evidence in `tests/unit/test_surface_boundaries.py`
- [X] T019 [P] [US2] Commit the redacted post-v0.5 corpus as `tests/fixtures/decision_grade_evidence.json` and add RED semantic negative and positive controls for film, sports, lottery, unrelated news, synonyms, target-user mismatch, and direct support in `tests/integration/test_decision_grade_evidence.py`

### Implementation for User Story 2

- [X] T020 [US2] Implement bounded pending-batch reads and stable mission/Brief frame fingerprints in `src/ignis/application/use_cases/get_evidence_qualification_batch.py`
- [X] T021 [US2] Implement atomic typed submission validation and immutable replay/conflict semantics in `src/ignis/application/use_cases/submit_evidence_qualifications.py`
- [X] T022 [US2] Expose `get_mission_evidence_qualification_batch` and `submit_mission_evidence_qualifications` in `src/ignis/interfaces/mcp/server.py`, `hermes_manifest.json`, `.hermes/tools.json`, and `openclaw.json`
- [X] T023 [US2] Implement deterministic per-topic evidence sufficiency and independent-source counting in `src/ignis/domain/research_workspace.py`
- [X] T024 [US2] Restrict Market demand, supply, maturity, insights, takeaways, and citations to qualified support in `src/ignis/infrastructure/harness/strategic_reasoner.py`
- [X] T025 [US2] Return structured `QUALIFICATION_REQUIRED`, `UNAVAILABLE`, and `INSUFFICIENT_RELEVANT_EVIDENCE` results from analysis, opportunity discovery, and artifact boundaries in `src/ignis/application/use_cases/get_mission_analysis.py` and `src/ignis/interfaces/mcp/server.py`
- [X] T026 [US2] Prove reopen stability, Market revision isolation, evidence-replacement invalidation, measured-zero probe history, and no legacy-surface gate on both backends in `tests/integration/test_decision_grade_evidence.py` and `tests/integration/test_dual_surface_journey.py`

**Checkpoint**: US2 prevents unsupported Market verdicts while preserving positive qualified controls.

**US2 evidence (27/09/2026):**

- RED captured before production code: T017/T018 failed on missing use-case modules and missing
  `QualifiedObservation`; T019 failed on the missing MCP handlers (12 = 6 tests x 2 backends).
- `test_decision_grade_evidence.py`: 53 passed (every contract on SQLite and PostgreSQL), including
  the corpus replay (`direct_market`, `attention_to_market`) with zero emitted unsupported conclusion
  units against the committed `0/21` baseline, the film/lottery/news/sports/target-user negative
  controls, the positive control (`SUFFICIENT_POSITIVE_SUPPLY`, 1 demand, 3 supply, 2 sources), the
  measured-zero control, reopen stability under changed connector health, a later failed run,
  revision isolation and evidence replacement.
- Negative control: counting every judged observation as support with its platform purpose (the
  pre-008 reading) turns the `direct_market` replay and the negative-control test red on both
  backends. The first negative-control attempt passed, exposing that the negative controls carried
  no demand; the fixture gained the corpus `att-032` adjacent Google item so the control can fail.
- Consumer updates: `test_dual_surface_journey` now expects `QUALIFICATION_REQUIRED` rather than an
  index right after ingress, and gains the legacy no-surface regression (2 passed); tool counts 45
  -> 47 in the manifests, the wheel smoke and the stdio/clean-user contracts (8 passed).
- Full suites before staging: unit 1165 passed, 1 skipped; integration 544 passed, 3 skipped,
  2 failed -- the clean-user contracts copy `git ls-files`, which did not yet include the two new
  untracked modules; staged, they pass (8 passed). No PostgreSQL skip.
- Interpretation recorded for review: an explicit `UNASSESSED`/`INSUFFICIENT_CONTENT` row counts
  as unassessed and never as support, but does not block the mission once every observation
  carries a row; `EVALUATOR_UNAVAILABLE` makes the mission `UNAVAILABLE`. A measured zero counts
  only `EMPTY_NO_DATA` supply surfaces of the same query; a `HEALTHY` surface whose items were all
  excluded is not a measured absence.

---

## Phase 5: User Story 3 - Handoff Only a Qualified Attention Candidate (Priority: P2)

**Goal**: Attention explicitly returns no qualified handoff candidate instead of promoting the
least-bad noise or adjacent cluster.

**Independent Test**: Compare a noise/adjacent-only Attention fixture with a directly relevant
multi-source fixture through the real analysis handler.

### Tests for User Story 3

- [X] T027 [P] [US3] Add RED Attention qualification tests for noise, adjacent context, synonyms, one-source repetition, two-source support, and no-fallback behavior in `tests/unit/test_surface_boundaries.py`
- [X] T028 [P] [US3] Add RED end-to-end Attention handoff payload scenarios on SQLite and PostgreSQL in `tests/integration/test_decision_grade_evidence.py`

### Implementation for User Story 3

- [X] T029 [US3] Implement qualified Attention cluster/source aggregation and no-fallback candidate selection in `src/ignis/infrastructure/harness/strategic_reasoner.py`
- [X] T030 [US3] Serialize `handoff_status`, qualified candidates, context-only clusters, and refusal reasons in `src/ignis/interfaces/mcp/server.py`

**Checkpoint**: US3 can be demonstrated without running a Market mission and Attention still never
emits an Opportunity Index.

**US3 evidence (27/09/2026):** the Attention aggregation and serialization (T029/T030) landed in the
same reasoner and server edit as T024/T025, before T027/T028 were written, so this story's RED is
shown by negative controls rather than by a pre-implementation run: a least-bad cluster fallback
turns 4 tests red (2 unit, the corpus replay on SQLite and PostgreSQL), and dropping the handoff
block from the serializer turns all 4 integration handoff tests red. Green: `test_surface_boundaries`
34 passed; `-k attention_handoff` 4 passed on both backends; every Attention payload keeps
`opportunity_index_applies: false` and `market_opportunities: []`. The validation's three Attention
clusters are not recoverable from the redacted corpus, so the replay groups by probe keyword.

---

## Phase 6: User Story 4 - Inspect Why Evidence Was or Was Not Used (Priority: P2)

**Goal**: Responses and artifacts expose question relevance, qualification counts, and the exact
reason a conclusion was allowed or withheld.

**Independent Test**: Render one mixed-evidence Market mission and compare MCP payload, canonical
qualification rows, and HTML output field for field.

### Tests for User Story 4

- [X] T031 [P] [US4] Add RED scorecard tests for question relevance, complete-but-insufficient `LOW` cap, pending/unavailable `UNRELIABLE` cap, and unaffected legacy missions in `tests/unit/test_evidence_qualification.py`
- [X] T032 [P] [US4] Add RED MCP serializer and citation-role tests for all four qualification counts and withheld-reason parity in `tests/unit/test_data_provenance.py`
- [X] T033 [P] [US4] Add RED deterministic HTML tests for hidden Opportunity Index UI, qualification summary, and no-qualified-candidate state in `tests/unit/test_html_builder.py`

### Implementation for User Story 4

- [X] T034 [US4] Calculate question relevance and confidence caps from persisted qualification summaries in `src/ignis/infrastructure/harness/quality_evaluator.py` and `src/ignis/domain/harness_models.py`
- [X] T035 [US4] Render qualification status and withheld-verdict states consistently in `src/ignis/infrastructure/templates/html_builder.py`, `src/ignis/infrastructure/templates/html/mission_report.html`, and `src/ignis/interfaces/mcp/server.py`

**Checkpoint**: US4 makes the decision boundary independently auditable in both machine and human
outputs.

**US4 evidence (27/09/2026):** RED before T034/T035: 13 failed (8 scorecard tests on the missing
`apply_qualification`, 3 HTML tests on the missing qualification section, 2 serializer tests on a
fixture whose supply carried no topic query -- a test fixture fault, corrected before any
production change). Two serializer tests passed at RED because T025 had already shipped the shared
`_surface_payload` block. Green: unit 1186 passed, 1 skipped; integration 552 passed, 3 skipped
(same intentional skips), including the parity contract in which the MCP analysis, the artifact
response, the canonical rows and the rendered HTML agree on every qualification count, the
question relevance, the reason code and the `UNRELIABLE` cap on both backends.

---

## Phase 7: Polish and Cross-Cutting Verification

**Purpose**: Synchronize public contracts and prove migration, backend, artifact, and package gates.

- [ ] T036 [P] Update the 47-tool catalog and Agent operating flow in `README.md`, `README.vi.md`, `docs/USER_GUIDE.md`, `docs/USER_GUIDE.vi.md`, and `CLAUDE.md`
- [ ] T037 [P] Add static convention gates for typed qualification tools, manifest count, migration inventory, no prompt transcript storage, and no hardcoded vocabulary in `tests/unit/test_tool_manifests_drift.py`, `tests/unit/test_repo_conventions.py`, and `tests/unit/test_sql_packaging.py`
- [ ] T038 Run the complete `quickstart.md` scenarios with a scratch PostgreSQL server, including negative controls that remove one migration command and re-enable unsupported evidence; record exact results in `.handoff/008-decision-grade-evidence.handoff.md`
- [ ] T039 Run unit, full dual-backend integration, ruff, `git diff --check`, `uv lock --check`, `uv build`, and fresh Compose init; verify no PostgreSQL case was skipped and no scratch resource or credential remains
- [ ] T040 Update `BACKLOG.md` and this task ledger with verified counts and explicit limits, without bumping version, tagging, pushing, merging, migrating a persistent database, or claiming release readiness

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1** starts immediately.
- **Phase 2** depends on migration `023` from Phase 1 and blocks every user story.
- **US1 (Phase 3)** depends on Phase 2 and is the suggested MVP.
- **US2 (Phase 4)** depends on Phase 2; it does not require US1 behavior but both must pass before
  whole-feature integration.
- **US3 (Phase 5)** depends on the qualification foundation in Phase 2 and can proceed in parallel
  with US2 until both touch `strategic_reasoner.py` and `server.py`.
- **US4 (Phase 6)** depends on US2 and US3 output contracts.
- **Polish (Phase 7)** depends on all selected stories.

### User Story Dependencies

- **US1**: No story dependency after Phase 2.
- **US2**: No story dependency after Phase 2.
- **US3**: No story dependency after Phase 2; coordinate shared reasoner/server files with US2.
- **US4**: Depends on US2 qualification/sufficiency output and US3 handoff output.

### Within Each User Story

- Write the named RED tests before production changes.
- Capture the expected failure and prove that it fails for the intended reason.
- Implement the smallest coherent behavior that makes the story green.
- Run the story checkpoint before editing a later story.
- Preserve existing unsupported/legacy behavior unless the spec explicitly changes it.

## Parallel Opportunities

- T017, T018, and T019 can be authored in parallel because they touch separate test files.
- T027 and T028 can be authored in parallel.
- T031, T032, and T033 can be authored in parallel.
- T036 and T037 can proceed in parallel after all output contracts stabilize.
- US1 and the initial US2 use-case work can proceed in parallel after Phase 2 because their primary
  production files do not overlap.

## Parallel Example: User Story 2

```text
Task: Add batch-read and atomic-submit RED tests in tests/unit/test_evidence_qualification.py
Task: Add sufficiency-policy RED tests in tests/unit/test_surface_boundaries.py
Task: Add semantic negative/positive controls in tests/integration/test_decision_grade_evidence.py
```

## Implementation Strategy

### MVP First

1. Complete Phases 1 and 2.
2. Complete US1 (T013–T016).
3. Stop and prove the first mission after startup matches a warm mission.
4. Commit the cold-start fix as an independently reviewable increment.

### Incremental Delivery

1. Foundation provides durable facts without changing conclusions.
2. US1 removes process-history dependence.
3. US2 makes Market fail closed and restores positive controls.
4. US3 prevents noisy Attention handoffs.
5. US4 makes the new boundary visible and auditable.
6. Phase 7 proves the whole plan on both backends and package surfaces.

### Commit Discipline

- Commit after each task or tightly coupled RED/GREEN pair.
- Do not open a pull request per task; open one only after the full plan is independently reviewed.
- Do not amend prior plan commits to hide failed evidence.
- Stop for PO review if a task would add a server-side AI provider, relax the evidence minimum,
  delete raw observations, or reinterpret legacy missions.
