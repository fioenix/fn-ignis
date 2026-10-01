---

description: "Dependency-ordered implementation tasks for the evidence-grounded product reset"
---

# Tasks: Evidence-Grounded Product Reset

**Input**: Design documents from `/specs/011-evidence-grounded-product-reset/`

**Prerequisites**: `plan.md`, `spec.md`, `research.md`, `data-model.md`, `contracts/`, `quickstart.md`

**Tests**: Required. Every behavior change follows RED → GREEN, including SQLite/PostgreSQL parity,
public MCP inventory, deterministic artifact, clean-bootstrap, and fail-closed negative controls.

**Organization**: Tasks are grouped by user story. The minimum coherent MVP is the complete P1 core
(US1–US3), because idle-only behavior without an auditable evidence frame and a fail-closed verdict
path is not a usable product outcome.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel because it touches different files and has no dependency on another
  incomplete task in the same phase.
- **[Story]**: Maps the task to a user story in `spec.md`.
- Every task names the files it changes or the file where the decision/evidence is recorded.
- **OWNER GATE** tasks are hard stops. A checked planning box or earlier proposal approval does not
  substitute for the target-specific authorization named by the task.

## Phase 1: Governance, Consumer Inventory, and Owner Gates

**Purpose**: Freeze the current public surface and prove exactly what the breaking cutover will
change before modifying runtime contracts or persisted evidence.

- [X] T001 Capture the current MCP operation names, parameters, manifests, CLI entrypoints, Compose services, runtime configs, templates, and canonical-document consumers in `specs/011-evidence-grounded-product-reset/consumer-inventory.md`
- [X] T002 Add the expected retained, removed, changed, and new MCP operation inventory as a RED contract in `tests/unit/test_public_mcp_contract.py`
- [X] T003 Add RED packaging assertions for the absent worker entrypoints, absent scheduler service, migration `025`, and the two planned skill packages in `tests/unit/test_sql_packaging.py` and `tests/integration/test_compose_init.py`
- [X] T004 Reconcile the eight-operation removal set against every consumer found by T001 and record any discrepancy in `specs/011-evidence-grounded-product-reset/consumer-inventory.md`
- [X] T005 OWNER GATE: obtain explicit approval to change/remove the exact existing MCP signatures in `contracts/mission-bound-public-surface.md` and record the owner answer under the current session in `specs/011-evidence-grounded-product-reset/spec.md`
- [X] T006 OWNER GATE: obtain explicit approval to write migration `sql/025_evidence_grounded_claim_ledger.sql` and record the owner answer under the current session in `specs/011-evidence-grounded-product-reset/spec.md`

**Checkpoint**: The old and new surfaces are enumerated, RED contracts exist, and implementation may
proceed only through the owner gates that have actually been granted.

---

## Phase 2: Foundational Evidence-Control Plane

**Purpose**: Add the shared typed records, schema, repository contracts, and dual-backend behavior
required by every user story.

**CRITICAL**: T006 must be approved before T009. No user-story implementation begins until the
foundation passes on SQLite and PostgreSQL.

- [X] T007 [P] Add RED validation cases for `MissionManifest`, authority boundaries, stop conditions, immutable digests, and invalid resource combinations in `tests/unit/test_mission_manifest.py`
- [X] T008 [P] Add RED validation cases for expanded Brief hypotheses, channel states, collection-plan identity, evidence roles, frame digests, claim types, bindings, and Gap Reports in `tests/unit/test_evidence_grounded_contracts.py`
- [X] T009 Create approved migration `sql/025_evidence_grounded_claim_ledger.sql` with manifests, expanded Brief fields, probe-outcome extensions, qualification extensions, claims, claim-evidence bindings, indexes, constraints, RLS, ACLs, UUID defaults, and no baseline-data promotion
- [X] T010 Add migration `025` ordering, packaging, schema, RLS, owner-only ACL, UUID-default, and negative-control assertions in `tests/unit/test_sql_packaging.py`, `tests/integration/test_postgres_migration_contract.py`, and `tests/integration/test_postgres_rls_coverage.py`
- [X] T011 Implement typed manifest, authority, channel-state, hypothesis-target, evidence-role, frame, claim, claim-binding, and Gap Report records in `src/ignis/domain/research_workspace.py` and `src/ignis/domain/value_objects.py`
- [X] T012 Add canonical serialization and digest helpers for manifests, collection plans, evidence frames, and candidate-claim idempotency keys in `src/ignis/domain/research_workspace.py`
- [X] T013 Extend `IResearchWorkspaceStore` with manifest, expanded Brief, complete outcome, claim, claim-binding, frame-invalidation, and read-only legacy-inventory contracts in `src/ignis/application/ports/research_workspace_port.py`
- [X] T014 Add RED dual-backend contract cases for all new records, uniqueness, foreign keys, cascades, idempotent replay, conflicting replay, legacy Brief readback, and frame supersession in `tests/integration/test_evidence_grounded_persistence.py`
- [X] T015 Implement the SQLite schema restatement and persistence methods for the new contracts in `src/ignis/infrastructure/persistence/sqlite_repository.py`
- [X] T016 Implement PostgreSQL persistence and row decoding for the new contracts in `src/ignis/infrastructure/persistence/postgres_repository.py`
- [X] T017 Add RED repository parity cases for latest-completed-plan `EMPTY_NO_DATA`, missing outcome rows, composite frame-scoped claim identity, measured-absence bindings, and claim invalidation after evidence pruning in `tests/integration/test_evidence_grounded_persistence.py`; canonical current-frame authority remains T040/T054
- [X] T018 Make SQLite and PostgreSQL enforce identical channel-state, qualification-compatible binding, explicit supersession, and cascade semantics in `src/ignis/infrastructure/persistence/sqlite_repository.py` and `src/ignis/infrastructure/persistence/postgres_repository.py`; neither backend may promote a caller-supplied digest to current
- [X] T019 Add a synthetic migration projection, count, constraint, and digest rehearsal in `scripts/rehearse_evidence_grounded_schema.py`
- [X] T020 Add deterministic rehearsal and negative-control tests for migration `025` in `tests/unit/test_evidence_grounded_schema_rehearsal.py`
- [X] T021 Run the Phase 1–2 targeted unit and dual-backend integration suites and record exact pass, fail, and skip evidence in `.handoff/011-foundation.handoff.md`

**Checkpoint**: The evidence-control plane is representable and behaviorally equivalent on both
backends; no production database has been migrated.

---

## Phase 3: User Story 1 - Start Only From an Explicit Research Task (Priority: P1)

**Goal**: An idle installation performs zero research work; an explicitly assigned task may run
autonomously inside its authority boundary and stops at a terminal state.

**Independent Test**: Initialize the package without assigning a task, then execute and complete one
bounded task. Verify zero idle calls/artifacts and zero post-terminal continuation.

### Tests for User Story 1

- [x] T022 [P] [US1] Add RED idle-state assertions for zero connector calls, journals, alerts, reports, scheduled jobs, and LLM work in `tests/integration/test_mission_bound_idle.py`
- [x] T023 [P] [US1] Add RED manifest-authority and terminal-state continuation cases, including browser, token, paid-quota, retry, and material-scope boundaries, in `tests/unit/test_mission_manifest.py`
- [x] T024 [P] [US1] Add RED bootstrap and Compose assertions that no resident worker or recurring schedule is installed or started in `tests/integration/test_compose_init.py` and `tests/unit/test_env_file_provisioning.py`

### Implementation for User Story 1

- [x] T025 [US1] Persist and validate a confirmed Mission Manifest when creating an Attention mission in `src/ignis/application/use_cases/create_attention_mission.py`
- [x] T026 [US1] Persist and validate the Mission Manifest for a confirmed Market Brief in `src/ignis/application/use_cases/confirm_market_brief.py`
- [x] T027 [US1] Enforce allowed resources, authority boundaries, one-run execution, and terminal stop conditions in `src/ignis/application/use_cases/execute_mission.py`
- [x] T028 [US1] Return explicit missing-authority and out-of-scope results without opening a connector session in `src/ignis/application/use_cases/execute_mission.py` and `src/ignis/interfaces/mcp/server.py`
- [x] T029 [US1] Remove scheduler CLI entrypoints and worker services from `pyproject.toml`, `docker-compose.yml`, and `docker-compose.prod.yml`
- [x] T030 [US1] Remove scheduled-worker environment settings, image guidance, bootstrap registration, and release acceptance from `env.example`, `src/ignis/config.py`, `Dockerfile`, `src/ignis/interfaces/cli/setup_bundle.py`, `scripts/bootstrap.sh`, and `scripts/public_release_acceptance.py`
- [x] T031 [US1] Delete the now-unreachable scheduler module and update direct consumers in `src/ignis/interfaces/cli/scheduler.py`, `tests/unit/test_scheduler.py`, and `tests/unit/test_worker_connector_selection.py`
- [x] T032 [US1] Prove idle-zero-work, explicit start, bounded autonomy, terminal stop, and clean bootstrap through `tests/integration/test_mission_bound_idle.py` and record results in `.handoff/011-us1.handoff.md`

**Checkpoint**: US1 is independently demonstrable without invoking strategic analysis or a report.

---

## Phase 4: User Story 2 - Collect a Transparent Social Evidence Frame (Priority: P1)

**Goal**: A bounded collection returns auditable provenance and exactly one explicit state for every
declared source surface, without interpreting unmeasured surfaces as zero.

**Independent Test**: Run one synthetic mission containing healthy, empty, unauthenticated,
rate-limited, degraded, failed, and unrequested surfaces; compare every response with persisted
provenance and frame identity.

### Tests for User Story 2

- [X] T033 [P] [US2] Add RED exact channel-state, scope-attestation, operational-note, and measured-zero cases in `tests/unit/test_mission_probe_outcomes.py`
- [X] T034 [P] [US2] Add RED tactical collection cases proving query/source/time/path/revision provenance and no Market side effects in `tests/integration/test_tactical_collection_contract.py`
- [X] T035 [P] [US2] Add RED full-frame digest and prior-mission evidence-requalification cases in `tests/integration/test_evidence_grounded_persistence.py`

### Implementation for User Story 2

- [X] T036 [US2] Return typed per-surface results for healthy, empty, auth, rate-limit, degraded, failed, and not-requested paths in `src/ignis/infrastructure/connectors/registry.py`
- [X] T037 [US2] Derive the versioned collection-plan projection with hypothesis targets, evidence roles, sampling, scope, authority tier, and digest in `src/ignis/domain/research_workspace.py`
- [X] T038 [US2] Persist one outcome for every manifest-declared channel and refuse a completed frame with a missing outcome row in `src/ignis/application/use_cases/execute_mission.py`
- [X] T039 [US2] Persist the readable collection-plan projection in the collision-safe run journal and its digest on each surfaced outcome in `src/ignis/infrastructure/persistence/workspace_repository.py` and `src/ignis/application/use_cases/execute_mission.py`
- [X] T040 [US2] Derive the canonical evidence-frame digest from the current manifest, Brief, plan, mission evidence, qualifications, and channel outcomes in `src/ignis/domain/research_workspace.py`
- [X] T041 [US2] Expose manifest, plan, provenance, complete channel states, frame digest, retention, redaction, policy, and reuse limits in `src/ignis/interfaces/mcp/server.py`
- [X] T042 [US2] Reject silent reuse of prior-mission observations until a current mission association and qualification exist in `src/ignis/application/use_cases/execute_mission.py` and `src/ignis/application/use_cases/get_evidence_qualification_batch.py`
- [X] T043 [US2] Prove tactical independence and transparent mixed-state collection with `tests/integration/test_tactical_collection_contract.py` and record results in `.handoff/011-us2.handoff.md`

**Checkpoint**: US2 produces a complete, auditable collection frame without requiring a strategic
verdict.

---

## Phase 5: User Story 3 - Challenge the Initial Belief Before a Verdict (Priority: P1)

**Goal**: Every Market mission tests core, alternative, and null hypotheses; preserves qualified
contradiction; and emits either current-frame traceable claims or a Gap Report with no forbidden
verdict.

**Independent Test**: Compare a sufficient mixed-evidence mission with auth-blocked, low-relevance,
all-confirmatory, and missing-metric controls through the real MCP handlers and deterministic HTML.

### Tests for User Story 3

- [X] T044 [P] [US3] Add RED expanded Brief tests for two distinct alternatives, null, falsifiers, kill criteria, revision rule, legacy read-only behavior, and immutable fingerprinting in `tests/unit/test_market_brief.py`
- [X] T045 [P] [US3] Add RED qualification tests for support, contradiction, context, hypothesis targets, equal quality rules, atomic replay, and stale-frame refusal in `tests/unit/test_evidence_qualification.py`
- [X] T046 [P] [US3] Add RED deterministic sufficiency and Gap Report cases for required channels, metrics, assessment coverage, contradiction coverage, denominators, timeframes, and next-best probes in `tests/unit/test_surface_boundaries.py`
- [X] T047 [P] [US3] Add RED Claim Ledger validation, idempotency, evidence-binding, measured-absence, withheld, permitted, and superseded cases in `tests/unit/test_mission_claims.py`
- [X] T048 [P] [US3] Add RED end-to-end sufficient, auth-blocked, low-relevance, contradictory, all-confirmatory, and missing-metric missions in `tests/integration/test_evidence_grounded_market_mission.py`
- [X] T049 [P] [US3] Add RED artifact cases proving contradiction visibility and total omission of forbidden verdict sections under insufficiency in `tests/unit/test_html_builder.py`

### Implementation for User Story 3

- [X] T050 [US3] Validate and persist the expanded immutable hypothesis register in `src/ignis/application/use_cases/confirm_market_brief.py` and `src/ignis/domain/research_workspace.py`
- [X] T051 [US3] Include hypothesis targets and the collection-plan identity in qualification batches in `src/ignis/application/use_cases/get_evidence_qualification_batch.py`
- [X] T052 [US3] Validate and persist `QUALIFIED_CONTRADICTION`, `hypothesis_target`, and `evidence_role` with atomic fail-closed replay semantics in `src/ignis/application/use_cases/submit_evidence_qualifications.py`
- [X] T053 [US3] Calculate deterministic sufficiency before accepting strategic prose and derive a typed Gap Report on failure in `src/ignis/domain/research_workspace.py`
- [X] T054 [US3] Implement candidate-claim validation, binding checks, current-frame checks, sufficiency gating, and persistence in `src/ignis/application/use_cases/submit_mission_claims.py`
- [X] T055 [US3] Implement current and superseded Claim Ledger retrieval with render status in `src/ignis/application/use_cases/get_mission_claims.py`
- [X] T056 [US3] Export the two new claim use cases from `src/ignis/application/use_cases/__init__.py` and wire them into component construction in `src/ignis/interfaces/mcp/server.py`
- [X] T057 [US3] Add `submit_mission_claims` and `get_mission_claims` handlers and MCP registrations in `src/ignis/interfaces/mcp/server.py`
- [X] T058 [US3] Make analysis and opportunity discovery read only persisted sufficiency and current-frame permitted claims in `src/ignis/application/use_cases/get_mission_analysis.py` and `src/ignis/infrastructure/harness/strategic_reasoner.py`
- [X] T059 [US3] Omit Opportunity Index, demand-gap, whitespace, saturation, and commercial recommendations whenever the evidence contract fails in `src/ignis/application/use_cases/get_mission_analysis.py` and `src/ignis/interfaces/mcp/server.py`
- [X] T060 [US3] Render the current Claim Ledger, contradiction, limitations, decision conditions, frame digest, and Gap Report through `src/ignis/infrastructure/templates/html_builder.py` and `src/ignis/infrastructure/templates/html/mission_report.html`
- [ ] T061 [US3] Prove the mixed-evidence and fail-closed journeys on both backends with `tests/integration/test_evidence_grounded_market_mission.py` and record results in `.handoff/011-us3.handoff.md`

**Checkpoint**: US1–US3 form the minimum coherent MVP: explicit task, transparent evidence frame,
and confirmation-bias-resistant verdict control.

---

## Phase 6: User Story 4 - Use Collection and Analysis as Independent Capabilities (Priority: P2)

**Goal**: Host agents can use bounded collection without a dossier and Senior Market Analytics only
over an eligible Ignis evidence frame, while both capabilities share one policy and schema.

**Independent Test**: Run `ignis-collect` alone, then run `ignis-analyze` over a qualified frame and
over an arbitrary external dataset; verify the first returns evidence only, the second traces every
claim, and the external dataset cannot become primary Market evidence.

### Tests for User Story 4

- [X] T062 [P] [US4] Add RED static skill-contract checks for thin shared-policy packages, exact MCP names, no credentials, no thresholds, no templates, and no arbitrary-dataset bypass in `tests/unit/test_ignis_skills.py`
- [X] T063 [P] [US4] Add RED misuse scenarios for auth-blocked collection, all-confirmatory queries, unsupported external data, and narration around insufficiency in `tests/integration/test_capability_skills.py`

### Implementation for User Story 4

- [X] T064 [US4] Create the bounded collection instruction surface in `.agents/skills/ignis-collect/SKILL.md`
- [X] T065 [US4] Create the Senior Market Analytics instruction surface in `.agents/skills/ignis-analyze/SKILL.md`
- [X] T066 [US4] Add shared evidence-frame examples without duplicating policy in `.agents/skills/ignis-collect/examples/collection-frame.md` and `.agents/skills/ignis-analyze/examples/claim-ledger.md`
- [X] T067 [US4] Return a typed context-only refusal when arbitrary uploaded or purchased data lacks mission-scoped provenance and qualification in `src/ignis/interfaces/mcp/server.py`
- [X] T068 [US4] Prove independent collection, eligible analysis, and all misuse controls through `tests/integration/test_capability_skills.py` and record results in `.handoff/011-us4.handoff.md`

**Checkpoint**: Both capability families are independently usable and cannot diverge from the shared
evidence contract.

---

## Phase 7: User Story 5 - Complete the Breaking Product Cutover (Priority: P2)

**Goal**: Runtime, public operations, packaging, bootstrap, skills, documentation, and historical
data handling describe one mission-bound product with no compatibility aliases.

**Independent Test**: Enumerate a clean installation, run one tactical probe and one Market mission,
and verify that all eight removed operations and every worker/scheduler/daily-discovery surface are
absent while legacy baseline data remains separate and untouched.

### Tests for User Story 5

- [ ] T069 [P] [US5] Extend the RED public contract to reject aliases, redirects, legacy surface-null mission creation, and any monitor/daily/schedule translation in `tests/unit/test_public_mcp_contract.py`
- [ ] T070 [P] [US5] Add RED clean-install and manifest-drift assertions for the retained, changed, removed, and new tools in `tests/integration/test_clean_user_journey.py`, `tests/unit/test_tool_manifests_drift.py`, and `scripts/wheel_mcp_smoke.py`
- [x] T071 [P] [US5] Add RED read-only classification, recoverable manifest, zero-write, and no-promotion cases in `tests/integration/test_legacy_baseline_inventory.py`

### Implementation for User Story 5

- [x] T072 [US5] Remove the approved eight MCP registrations and their handlers without aliases from `src/ignis/interfaces/mcp/server.py`
- [x] T073 [US5] Remove the approved obsolete operation definitions and add the two Claim Ledger operations in `hermes_manifest.json`, `.hermes/tools.json`, and `openclaw.json`
- [x] T074 [US5] Delete the autonomous-discovery use case and update direct consumers in `src/ignis/application/use_cases/autonomous_discovery.py`, `tests/unit/test_autonomous_discovery.py`, and `tests/unit/test_mission_flow.py`
- [ ] T075 [US5] Remove scheduled-only trigger/filter/config behavior while preserving requested atomic and mission collection in `src/ignis/domain/value_objects.py`, `src/ignis/application/use_cases/ingest_trends.py`, `src/ignis/infrastructure/connectors/registry.py`, and `tests/unit/test_regional_script_gate.py`
- [ ] T076 [US5] Trace the three trend-template consumers against T001 and delete only consumer-proven unreachable sources from `src/ignis/infrastructure/templates/html/trend_card.html`, `src/ignis/infrastructure/templates/html/trend_dashboard.html`, and `src/ignis/infrastructure/templates/html/trend_graph.html`
- [ ] T077 [US5] Implement read-only legacy classification and recoverable target-manifest generation in `src/ignis/application/use_cases/inventory_legacy_baseline.py`
- [ ] T078 [US5] Add a thin no-write inventory command in `scripts/inventory_legacy_baseline.py`
- [ ] T079 [US5] Update English product architecture, bootstrap, tool catalog, agent skills, and superseded-history guidance in `README.md`, `docs/USER_GUIDE.md`, `AGENTS.md`, `CLAUDE.md`, `.codexrules`, and `.agents/skills/fn-ignis-harness/SKILL.md`
- [ ] T080 [US5] Update Vietnamese market-facing product, capability, refusal, and migration guidance in `README.vi.md` and `docs/USER_GUIDE.vi.md`
- [ ] T081 [US5] Update package and marketplace descriptions without changing the version in `server.json`, `openclaw.json`, and `bundle/README.md`
- [ ] T082 [US5] Update repository convention gates for the mission-bound category, absent worker language, English developer guidance, and canonical template boundary in `tests/unit/test_repo_conventions.py` and `tests/unit/test_public_doc_conventions.py`
- [ ] T083 [US5] Run the clean-install public inventory, tactical probe, Market journey, and legacy inventory tests and record exact results in `.handoff/011-us5.handoff.md`

**Checkpoint**: The implementation is cut over locally, but no baseline record has been archived or
deleted and no release has been prepared.

---

## Phase 8: Pilot, Cross-Cutting Verification, and Shipping Gates

**Purpose**: Validate the Vietnam consumer-market wedge, close documentation and backlog state, and
separate implementation completion from owner-authorized migration, release, and deletion actions.

- [ ] T084 Add five reproducible pilot case definitions, decision outcomes, stop conditions, required channels, and comparison criteria in `specs/011-evidence-grounded-product-reset/pilot-protocol.md`
- [ ] T085 OWNER GATE: obtain explicit bounded authorization before using any real TikTok, Threads, or Instagram session/token and record allowed accounts, surfaces, quotas, and expiry in `specs/011-evidence-grounded-product-reset/pilot-protocol.md`
- [ ] T086 [P] Run the authorized sufficient multi-source Vietnam consumer-market pilot and record mission, Brief, frame, claims, limitations, and decision usefulness in `specs/011-evidence-grounded-product-reset/pilot-results.md`
- [ ] T087 [P] Run the authorized required-channel authentication-block pilot and record the Gap Report and smallest next probe in `specs/011-evidence-grounded-product-reset/pilot-results.md`
- [ ] T088 [P] Run the authorized high-volume low-relevance pilot and record qualification and refusal evidence in `specs/011-evidence-grounded-product-reset/pilot-results.md`
- [ ] T089 [P] Run the authorized contradictory-signals pilot and record how counterevidence changes or conditions the claims in `specs/011-evidence-grounded-product-reset/pilot-results.md`
- [ ] T090 [P] Run the authorized missing decision-critical metric pilot and record the absent forbidden outputs and next-best probe in `specs/011-evidence-grounded-product-reset/pilot-results.md`
- [ ] T091 Compare the five pilot outcomes against one generic research-agent workflow and one composable OSS workflow without inventing unavailable metrics in `specs/011-evidence-grounded-product-reset/pilot-results.md`
- [ ] T092 Run `quickstart.md`, the full unit suite, full dual-backend integration suite, ruff, `git diff --check`, `uv lock --check`, package build, wheel smoke, and fresh Compose init; record exact commands, skips, negative controls, and cleanup in `.handoff/011-final-verification.handoff.md`
- [ ] T093 Run the read-only legacy inventory, present explicit archive/deletion candidates, and record the owner's disposition decision without changing data in `specs/011-evidence-grounded-product-reset/legacy-disposition.md`
- [ ] T094 Update `BACKLOG.md` and this ledger with implementation evidence, unresolved owner gates, and explicit shipped/not-shipped state without claiming release from local tests
- [ ] T095 OWNER GATE: obtain explicit decisions for persistent-database migration application, exact baseline archive/deletion targets, release version, tag, push, and GitHub Release; record each answer in `specs/011-evidence-grounded-product-reset/spec.md`
- [ ] T096 Apply only the owner-approved persistent migration and baseline disposition with pre-action manifest, recovery path, post-action readback, and evidence in `.handoff/011-owner-authorized-operations.handoff.md`
- [ ] T097 Prepare the owner-approved breaking release by synchronizing `pyproject.toml`, `openclaw.json`, `server.json`, `CITATION.cff`, `.openclaw/config.yaml`, `BACKLOG.md`, and regenerated `uv.lock` in one atomic change
- [ ] T098 Merge, tag, push, and publish only the owner-approved release, then record the PR, merge commit, tag, public package/container checks, and anonymous clean-install evidence in `BACKLOG.md` and `specs/011-evidence-grounded-product-reset/tasks.md`

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1** has no code dependency. T005 blocks existing MCP signature changes; T006 blocks
  migration creation.
- **Phase 2** depends on T006 and blocks every user story.
- **US1** and **US2** may start after Phase 2. Their tests and separate files can proceed in
  parallel; `execute_mission.py` edits must be serialized.
- **US3** depends on the US2 evidence-frame and channel-outcome contracts.
- **US4** depends on US2 collection output and US3 analysis/claim gates.
- **US5** depends on T005 and the retained behavior from US1–US4, so removal cannot accidentally
  erase a needed consumer.
- **Phase 8** depends on the locally complete US1–US5 implementation. T085 blocks only pilots that
  use real restricted sessions. T095 blocks migration application, deletion, versioning, tagging,
  pushing, and release.

### User Story Dependency Graph

```text
Phase 1 gates -> Phase 2 foundation
                         ├── US1 explicit start/stop ─────────────┐
                         └── US2 transparent evidence frame ──> US3 falsification + claims
                                                                 └──> US4 capability skills
US1 + US2 + US3 + US4 + MCP owner gate ─────────────────────────────> US5 breaking cutover
US1–US5 ────────────────────────────────────────────────────────────> Pilot and shipping gates
```

### Within Each User Story

- Write each RED contract first and run it to capture the intended failure.
- Implement domain records before persistence consumers, persistence before use cases, use cases
  before MCP/skill surfaces, and current-frame policy before artifacts.
- Run the independent test and record evidence before moving the story checkpoint.
- Never check an OWNER GATE based on inferred approval or an earlier broader proposal decision.

## Parallel Opportunities

- T002–T004 may run in parallel after T001.
- T007 and T008 are parallel; SQLite and PostgreSQL implementation may be assigned separately only
  after the shared port is fixed.
- The RED test tasks inside each user story are parallelizable.
- US1 and US2 can proceed in parallel except where both touch `execute_mission.py`.
- The two skill packages in US4 can be authored in parallel after their shared contract test exists.
- Documentation language surfaces in T079 and T080 can proceed in parallel after runtime names are
  final.
- The five pilot conditions are independent after T084–T085, subject to quota and account limits in
  the recorded authority boundary.

## Parallel Examples

### US1 and US2 after the foundation

```text
Task A: T022–T032 in the explicit start/stop slice
Task B: T033–T043 in the transparent evidence-frame slice
Constraint: serialize edits to src/ignis/application/use_cases/execute_mission.py
```

### US3 RED contracts

```text
Task A: T044 expanded Market Brief tests
Task B: T045 qualification and contradiction tests
Task C: T046 sufficiency and Gap Report tests
Task D: T047 Claim Ledger tests
Task E: T049 deterministic artifact tests
```

### US4 capability packages

```text
Task A: T064 ignis-collect skill
Task B: T065 ignis-analyze skill
Join: T066 shared-contract examples after both package entrypoints exist
```

## Implementation Strategy

### Minimum Coherent MVP: P1 Core

1. Complete Phase 1 inventories and obtain only the gates needed for code about to change.
2. Complete Phase 2 and prove SQLite/PostgreSQL parity.
3. Complete US1 and US2, then validate idle behavior and the transparent evidence frame.
4. Complete US3 and validate both a permitted mixed-evidence claim set and a fail-closed Gap Report.
5. Stop and review the P1 outcome before packaging skills or removing public compatibility surfaces.

### Incremental Delivery

1. **Foundation** → typed control plane and migration rehearsal, no production mutation.
2. **P1 core** → explicit task, auditable collection, falsification, claims, and refusal.
3. **Capability packaging** → `ignis-collect` and `ignis-analyze` over the same contract.
4. **Breaking cutover** → remove the approved old surface only after consumer audit.
5. **Pilot** → test the Vietnam wedge under five conditions.
6. **Shipping** → migrate, delete/archive, version, merge, tag, push, and release only where each
   owner gate is explicit.

## Notes

- The accepted product proposal authorizes planning; it does not satisfy T005, T006, T085, or T095.
- Migration `024` never promotes legacy baseline rows into mission evidence.
- T093 produces a decision surface, not permission to mutate data.
- HTML runtime report sources remain only under `src/ignis/infrastructure/templates/html/`.
- A local green suite is implementation evidence, not proof of merge, deployment, migration, or
  public release.
