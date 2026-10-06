# Tasks: Task-Bound Host Browser Search

**Input**: Approved spec.md, plan.md, research.md, data-model.md and contracts/.
**Execution**: Inline, test-first. Keep existing owner edits. No release or DB mutation authorized.
**Latest reconciliation — 2026-10-04**: Behavioral implementation and actual bounded UAT are verified
against the final runtime; shipping is not. Initial RED ordering for T004/T006/T007 and the
before-extraction chronology of T020/T022 are not established by retained evidence reviewed here.
Those process tasks remain unchecked rather than reconstructing history. Reviewer checklists are
unchanged. Spec 013's final ledger records current runtime/backend/package/security proof.
**Status**: In progress locally; live tactical and isolated SQLite mission round-trips recorded in
`.handoff/spec012-live-validation.md`. Five Important review defects corrected with regression tests.
Browser failure/cancellation and excerpt masking locally verified on 2026-10-03. Full task-by-task
acceptance reconciliation remains separate; no merge/release. See `.handoff/spec012-verification.md`.

2026-10-03 blocker correction: counter-only public tiles are now rejected as content, with five
observed RED-to-GREEN regressions. Added ordinary-execution/shared-writer happy-path parity and
distinct persisted Manifest/Brief/evidence-frame race tests. These are fresh characterization
tests, not evidence that the original seam extraction was test-first. Dual-backend focused
checks completed with 57 passed and 2 backend-inapplicable skips, exit 0. FR-005 still needs observed caption DOM and a fresh
content-bearing browser round-trip; T010/T014/T025/T029/T030 remain open. Historical numeric-only
live receipts prove transport, not content acceptance. Reviewer-owned checklists are unchanged.

Subsequent owner-approved Chrome retry supplied the actual DOM: public content is in the
visible linked image alt label. Extractor correction observed RED-to-GREEN (11 tests), followed
by fresh actual MCP/browser/relay acceptance of three content-bearing records and canonical
SQLite mission frame readback. Live readback also exposed a phone-masking numeric-ID false
positive; the narrow regex-boundary correction passed 73 focused dual-backend tests with
2 backend-inapplicable skips. Full final-source gates and review are tracked in
`.handoff/spec012-caption-validation-20261003.md`; no PR/merge/release completion is claimed.

Final-source default full suite completed: 1913 passed, 374 condition/backend skips,
2 existing warnings, exit 0. Final independent review found no new Critical/Important issue
and accepted the content-bearing FR-005 correction. Whole-ledger reconciliation and remote
integration remain open; the earlier full PostgreSQL/Compose run is retained as pre-fix proof,
not substituted for final-source results.

## Phase 1: Setup

- [x] T001 Record owner plan approval and execution scope in specs/012-host-browser-search/spec.md and plan.md.
- [x] T002 Inspect current host APIs and tool inventory; record transport findings in .handoff/spec012-host-transport-gate-2026-10-02.md.

## Phase 2: Foundation / Transport Stop Gate

- [x] T003 Resolve and prove deterministic host result relay without model reconstruction; actual relay/readback recorded in .handoff/spec012-live-validation.md and final Spec 013 UAT ledger. Original transport-gate note remains historical.
- [ ] T004 Write failing typed preparation/bounds tests in tests/unit/test_host_browser_search.py.
- [x] T005 Implement strict request/session/query models in src/ignis/domain/host_browser_search.py; current preparation/bounds tests pass. T004's historical RED evidence remains separate.
- [ ] T006 Write failing actual MCP discovery/serialization smoke in tests/integration/test_host_browser_search_mcp.py.

The owner approved the localhost relay amendment. Foundation/tactical operations T004–T013 must exist
before T003's actual round-trip; no mock can complete that gate. The actual round-trip has since been
recorded; unchecked tasks below still require individual acceptance reconciliation, not bulk ticking.

## Phase 3: US1 — Authorized Public Search (P1 / MVP)

**Independent test**: Actual prepare, authorized Chrome extraction, actual submit and attributable
observation readback; no Market claim or default collector change.

- [ ] T007 [US1] Write failing preparation/refusal tests in tests/unit/test_host_browser_search.py.
- [x] T008 [US1] Implement tactical preparation and finite tickets in src/ignis/application/use_cases/host_browser_search.py.
- [x] T009 [P] [US1] Write deterministic public-card extractor tests with visible-grid fixtures in tests/integration/test_host_browser_extractor.py; numeric-only and observed visible image-label regressions have retained RED/GREEN evidence.
- [x] T010 [US1] Implement packaged extractor in src/ignis/infrastructure/connectors/host_browser/tiktok_search.js; make T009 green. Actual content-bearing installed/browser round-trip and final five-query collection verified.
- [x] T011 [P] [US1] Write wrong-page/query, malformed/oversized, partial and empty-answer tests in tests/unit/test_host_browser_search.py and tests/unit/test_host_browser_relay.py (consolidated validation coverage).
- [x] T012 [US1] Implement deterministic validation/normalization in src/ignis/infrastructure/connectors/host_browser/validator.py; make T011 green.
- [x] T013 [US1] Register additive prepare/submit handlers in src/ignis/interfaces/mcp/server.py; current schema/serialization tests and installed 44-tool catalog verified. T006's historical RED evidence remains separate.
- [x] T014 [US1] Run actual one-query MCP/host round-trip and record readback in .handoff/spec012-live-validation.md; meaningful content is additionally verified in .handoff/spec012-caption-validation-20261003.md and final Spec 013 collection, not inferred from old numeric-only receipts.

## Phase 4: US2 — Session Ownership and Termination (P1)

**Independent test**: Two queries reuse one session; fail/cancel/replay cannot start new collection or
close owner tabs. No runtime/browser transport permission expansion.

- [x] T015 [US2] Write expiry/replay/concurrent-submit/cancel tests in tests/unit/test_host_browser_search.py.
- [x] T016 [US2] Implement atomic ticket transitions/receipts in src/ignis/application/use_cases/host_browser_search.py; make T015 green.
- [x] T017 [US2] Add cancellation handler in src/ignis/interfaces/mcp/server.py and verify contract in tests/integration/test_host_browser_search_mcp.py.
- [x] T018 [US2] Document host session reuse, stop checks and task-owned cleanup in .agents/skills/ignis-collect/SKILL.md after verifying the canonical collection-skill path; actual lifecycle proof is in Spec 013 U09.
- [x] T019 [US2] Verify two-query/failure/cancel ownership through actual host tools; record in .handoff/spec012-live-validation.md.

## Phase 5: US3 — Mission Evidence Boundaries (P2)

**Independent test**: Fresh isolated mission uses complete confirmed scope and normal writer/journal/
frame/qualification; stale or replayed answers cannot write and unknown window cannot prove absence.

- [ ] T020 [US3] Write current-execution parity tests before extracting the ingestion seam in tests/integration/test_host_browser_mission.py.
- [x] T021 [US3] Extract common ingestion without public signature changes in src/ignis/application/use_cases/execute_mission.py; current ordinary/shared-writer parity is verified on both repositories. T020 chronology is not inferred from these characterization tests.
- [ ] T022 [US3] Write failing manifest/Brief/frame race, quota/falsifier and writer-conflict tests in tests/integration/test_host_browser_mission.py.
- [x] T023 [US3] Implement mission preparation/submit under existing writer in src/ignis/application/use_cases/host_browser_search.py; current scope-race/quota/falsifier/conflict cases pass, without claiming T022 historical RED order.
- [x] T024 [US3] Verify all-surface outcomes, observation associations and qualification missingness in tests/integration/test_host_browser_mission.py; final dual-backend gate and partial DEGRADED frame/withholding contracts verified.
- [x] T025 [US3] Run fresh local mission round-trip and frame readback; original sanitized proof in .handoff/spec012-live-validation.md, content-bearing proof in caption validation and final installed 136-observation frame in Spec 013's ledger.

## Phase 6: Cross-Cutting Verification and Delivery

- [x] T026 Update README.md, README.vi.md and docs/USER_GUIDE.md with additive contracts and limits; actual manifests/catalog contain 44 tools, final distribution/doc checks verified and version remains unchanged.
- [x] T027 Verify wheel extractor packaging and installed MCP discovery using tests/integration/test_host_browser_search_mcp.py; record exact artifact/revision in .handoff/spec012-verification.md.
- [x] T028 Run sanitized full tests, conventions and lint; record commands/results in .handoff/spec012-verification.md.
- [x] T029 Review complete implementation/security diff and fix validated findings test-first; bounded review corrections and final code re-review retained, latest security scan 2e6d4703-84b3-4e55-9d4c-9235b0e4e760 sealed with 37 changed source/configuration entries and zero findings. See Spec 013 final ledger; no shipping claim.
- [ ] T030 Reconcile acceptance and integration/activation status in specs/012-host-browser-search/tasks.md; leave merge/release actions gated.

## Dependencies and Parallel Examples

Setup → T003 transport gate → foundation → US1 → US2 → US3 → verification. Nothing downstream may
claim completion while T003 is blocked. T009/T011 can run independently after contracts/models exist;
T015 lifecycle tests may be written alongside extractor validation but implementation shares one file.
US3 parity fixtures can be prepared independently of US2 only after US1 contracts stabilize. No new
agents are dispatched by this ledger; parallel examples describe potential safe file ownership.

## Strategy and Rulings

### Final task evidence — 2026-10-04

Owner subsequently accepted integration with the documented historical test-first-order and unverified report-pixel exceptions: "Tao chốt, tạo PR và merge đi, để xong rồi qua Goal 2". Historical process checkboxes remain unchecked rather than fabricated as proof; they are no longer PO integration blockers. T030 requires actual PR/CI/merge readback, tracked in Spec 013's canonical ledger. No release is implied.

Fresh targeted command, managed session 77875, exited 0: host-browser unit, relay, packaged-JavaScript extractor, actual MCP schema/lifecycle and mission integration tests — **68 passed, 29 PostgreSQL-default skips in 10.34s**. Exact generated results: `.handoff/spec012-final-task-audit.xml`. This SQLite/default rerun is not PostgreSQL proof; the previously observed final disposable dual-backend command passed 750 cases with five backend-inapplicable skips and owned cleanup exit 0, recorded in Spec 013's canonical ledger.

The first supplemental audit command exited 4 before test collection: runtime isolation was passed to pytest, whose credential quarantine removes IGNIS_ENV_FILE. Running the same files with a clean process environment and the existing test quarantine corrected only the invocation. No source, schema, credentials or UAT evidence changed. Historical initial RED/before-seam claims remain unproven, not silently completed by this green run. T030 also remains open because integration/activation has not occurred. All current implementation claims link to tests, actual UAT or source review; checked tasks do not imply release.

MVP is US1 with actual browser/MCP evidence. Incremental delivery requires US2 safety before mission
use, then US3 parity and final review. Every code step needs observed RED→GREEN. Latest full suite:
1848 passed, 363 skipped, 2 existing warnings; remaining unchecked tasks are not completion claims.

Ruling: Stop at missing deterministic relay, rather than reconstructing records from tool transcript —
approved plan mandates this stop — cost if wrong: delayed implementation until a safe relay is available.
Ruling: The owner approved a task-bound loopback relay; implement its bounded lifecycle/security tests
before T003 — cost if wrong: reject unsafe ingress and retain the live gate as incomplete.
