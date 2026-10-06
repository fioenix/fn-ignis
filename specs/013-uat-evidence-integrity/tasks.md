# Tasks: UAT Evidence Integrity

**Input**: spec.md, plan.md, research.md, data-model.md and contracts/query-proof-and-uat.md.
**Organization**: Independent user stories; observed RED→GREEN required for each production fix. No checked task implies shipping.

**Owner disposition — 2026-10-04**: Goal 1 accepted for PR/merge before Goal 2 with documented historical test-first-order and unavailable independent pixel-proof exceptions. T006/T018/the visual portion of T022 remain unchecked as technical observations, not PO integration blockers. See uat-ledger.md. T027 still requires actual integration readback; no release is implied.

## Phase 1: Setup

- [x] T001 Record the full owner delegation and acceptance scope in specs/013-uat-evidence-integrity/spec.md and uat-ledger.md.
- [x] T002 Audit shared collector consumers and response/attestation authority in specs/013-uat-evidence-integrity/research.md.
- [x] T003 Finish missing initial qualification and claim-path UAT evidence in uat-ledger.md using isolated stdio harnesses; actual TikTok qualification and controlled permitted/stale/foreign/idempotent claim paths recorded. Real Market and final repetition remain separate mandatory tasks.

## Phase 2: Foundation

- [x] T004 Create and link confirmed defects and navigation investigation issues in specs/013-uat-evidence-integrity/issues.md; actual issues #46–#48 created and read back.
- [x] T005 Write offline browser capture fixtures for exact request query and public result envelopes in tests/unit/test_meta_browser_ingress.py; real capture callbacks exercise request/status/envelope restrictions and generic default behavior.

## Phase 3: US1 — Exact Public Query Proof

**Independent test**: Wrong/background/error/unknown responses authorize no observation or execution; exact valid public result and empty result are separately proven; non-search consumers retain behavior.

- [ ] T006 [US1] Observe failing wrong-query/background/sibling-record tests in tests/unit/test_social_search_integrity.py and tests/unit/test_meta_browser_ingress.py.
- [x] T007 [US1] Implement optional request-query capture restriction in src/ignis/infrastructure/connectors/meta_browser_ingress.py; targeted capture tests verified, broader outcome regressions remain T006/T010.
- [x] T008 [US1] Add public post-envelope and valid-empty/fallback regressions in tests/unit/test_threads_direct_graphql.py; six observed behavioral failures before the direct-path change, then GREEN.
- [x] T009 [US1] Apply the same proof before direct/browser extraction and attestation in src/ignis/infrastructure/connectors/threads/threads_plugin.py; known legacy envelopes supported, live current-envelope/navigation acceptance still pending.
- [x] T010 [US1] Verify wrong/empty/partial query outcomes and unaffected Reels/trending/suggestions in tests/unit/test_registry.py and tests/unit/test_meta_browser_ingress.py; fresh final setup/registry/Meta/direct/Relay command passed 105 cases, preserving generic walking and non-search consumers. This is local parity, not final real Market coverage.
- [x] T011 [US1] Demonstrate actual navigation/capture cause with sanitized .handoff/ diagnostics; actual matched server-rendered Relay result proves the XHR-only collector misses an executed search; recorded in research.md.
- [x] T012 [US1] Reproduce and correct the verified capture defect in meta_browser_ingress.py without tier expansion; observed missing Relay positive-path RED, then actual two-query collection restored. Broader final gates remain open.
- [x] T013 [US1] Verify actual two-query connector response proofs and duplicate attribution in specs/013-uat-evidence-integrity/uat-ledger.md; #49 observed four RED cases, direct/browser/Graph and SQLite qualification regressions GREEN, then actual public two-query collection retained both query labels on the overlapping post. Final dual-backend/mission/export UAT and integration remain T021–T027.

## Phase 4: US2 — Evidence-Grounded Decision

**Independent test**: Actual Attention has no commercial inference; actual Market either returns supported current claims or an honest Gap Report; controlled positive-path evidence stays test-only.

- [x] T014 [US2] Reproduce and suppress Attention saturation advice in tests/unit/test_data_provenance.py and src/ignis/infrastructure/harness/strategic_reasoner.py; read fresh actual MCP/export back.
- [x] T015 [US2] Execute real typed qualification/replay/stale/foreign batch UAT using .handoff/ isolated MCP harness and record in uat-ledger.md; 47 actual TikTok observations reviewed/submitted, stale and foreign rejected, replay counts unchanged. Final repetition remains T021.
- [x] T016 [US2] Execute confirmed core/alternatives/null/falsifier Market collection and honest sufficiency UAT using .handoff/ bounded harness; actual 153-observation two-channel frame fully assessed, real insufficient recommendation WITHHELD, maintained Gap export read back. Final repetition and visual inspection remain T018/T021/T022.
- [x] T017 [US2] Execute separately controlled positive Claim Ledger and stale/foreign/idempotent negative paths through actual MCP; one PERMITTED controlled claim, identical replay ID, stale digest and foreign qualified-binding refusals recorded in uat-ledger.md. Final repetition remains T022.
- [ ] T018 [US2] Inspect maintained report citations/limitations visually and reconcile final render proof in specs/013-uat-evidence-integrity/uat-ledger.md.

## Phase 5: US3 — Lessons and Complete Second UAT

**Independent test**: Every baseline issue has prevention and every U01–U12 row has actual final proof after all fixes.

- [x] T019 [US3] Record durable observed lessons through Obsidian CLI under 04-PROCEDURAL/Lessons/ and link dispositions in specs/013-uat-evidence-integrity/issues.md; baseline and final lesson updates were created/read back, with complete task reconciliation recorded under T026.
- [x] T020 [US3] Recheck setup isolation and actual installed-wheel runtime using tests/unit/test_scoped_setup.py and maintained scripts/wheel_mcp_smoke.py Session; final installed CLI Codex-only provisioner exited 0 under fresh owned HOME/SQLite, preserved unrelated synthetic clients and Codex entry, then the generated command established 44-tool MCP/read-only configuration/stdin exit 0 with unchanged env and no invented workspace. Fresh setup/parity tests passed 105 cases. Owner clients and sessions were not operated on.
- [x] T021 [US3] Rerun final actual TikTok/Threads collection and qualification UAT; installed-wheel mission 8b1daae7 completed 59 TikTok and 77 Threads observations, all 136 independently reviewed and persisted; stale/foreign refusals and idempotent replay verified. Dates/window/audience representativeness remain unmeasured. See final post-026 ledger entry; visual/security/integration gates remain open.
- [ ] T022 [US3] Rerun final Market/claim/visual/error/cancel/termination cases using .handoff/ UAT harnesses and existing tests/integration/test_host_browser_search_mcp.py; actual host lifecycle, final 136-observation Market Gap and final installed Attention/controlled claim/export readbacks are verified. Visual inspection remains open; see the final security/package entry in uat-ledger.md.
- [x] T023 [US3] Update permanent verified user guidance in docs/USER_GUIDE.md and docs/USER_GUIDE.vi.md without changing public signatures or version; source/installed export paths and pending-only migration sequence documented, final documentation/distribution checks passed 160 cases with one explicit skip.

## Phase 6: Cross-Cutting Delivery

- [x] T024 Run final default and non-skipped backend tests, conventions/lint/package gates; post-026 default 2007 passed/379 skipped/two warnings, actual dual-backend/Compose 750 passed/five backend-specific skips with owned cleanup exit 0, clean journey 10 passed. Final build/lock/Ruff exit 0, installed final wheel discovers 44 tools and completes read-only configuration/termination. Pixel and integration acceptance are not part of this task.
- [x] T025 Complete code/security review and regression corrections; bounded independent code reviews closed the reproduced defects. Fresh security scan 2e6d4703-84b3-4e55-9d4c-9235b0e4e760 is sealed and read back: all 37 current changed source/configuration entries reviewed, zero candidates/findings. Exact snapshot and report reference are in issues.md and uat-ledger.md; this is not repository-wide assurance or shipping.
- [x] T026 Reconcile every Spec 012 and Spec 013 acceptance task against actual evidence in both tasks.md ledgers; final lesson appended/read back and Spec 012 behavior tasks linked to actual tests/runtime/review. Historical test-first-order tasks remain unchecked pending owner disposition; visual and integration tasks stay open. Reconciliation is not complete acceptance or shipping.
- [ ] T027 Verify authorized integration/activation or explicitly park that boundary in BACKLOG.md and specs/013-uat-evidence-integrity/uat-ledger.md; no implicit release.

## Dependencies and Parallel Examples

## Review Remediation — 2026-10-04

- [x] T028 Reproduce native TikTok wrong-query/landed-page attestation through actual capture callbacks, then bind response and DOM admission to the requested public search; six observed RED failures, wrong/empty/populated response and wrong-page DOM refusal verified locally. Final real UAT/review remains T021/T025.
- [x] T029 Reproduce nested Threads quote promotion and result-limit displacement on direct/browser search; two observed RED failures, root-only selection/deduplication/limits and generic non-search consumers verified locally. Final real UAT/review remains T021/T025.
- [x] T030 Reproduce native TikTok unknown counters/publication through analysis; eight observed DOM/JSON RED failures, measured zero versus missing views (never substitute likes), publication freshness and native/host consumer parity verified locally. Combined 180 regression/convention tests passed; final real UAT/review remains T021/T025.
- [x] T031 Correct mixed-query partial coverage: owner-approved 026 preserves evidence and original attestation; populated SQLite upgrade/replay/rollback and actual disposable PostgreSQL preservation/security/replay tests pass. Full gates observed 2007 default passes and 750 integration passes. Reviewed rebuilt wheel completed a fresh bounded actual mission; historical FAILED mission remains unchanged. Partial DEGRADED is neither measured absence nor required-channel sufficiency. Whole-branch security, visual and integration remain open.
- [x] T032 Correct installed-wheel report output location: two observed RED cases, source-checkout behavior preserved, 173 targeted passes/16 backend skips and actual rebuilt-wheel positive/Gap exports under isolated HOME verified. User guides updated; independent bounded review found no blocking code defect, and the foreign-binding evidence limitation was corrected with a distinct key and specific qualification refusal. Whole-branch code/security/final gates remain T024/T025. No historical artifact was moved and no report template changed.

These are confirmed code-review blockers, not inferred security vulnerabilities. T025 and final UAT remain open until all three corrections are verified.

Setup → issues → shared response proof → query navigation → final source UAT → final decision UAT → review/integration. Remaining baseline qualification/claim cases may run alongside independent offline response-proof work, but must finish before final UAT acceptance. T008 fixtures can be prepared independently of T007 implementation. T014 is already locally verified, but final US2 depends on US1 specificity. Lessons/issue writing can proceed alongside offline fixtures. No implementation worker is automatically dispatched by this ledger.

## Strategy

US1 is the first usable increment, not a substitute for the requested complete goal. Initial missing cases and all final U01–U12 cases remain required. Two independent corrections leaving the same end-to-end invariant red trigger the architecture checkpoint before a third. Newly discovered defects extend this ledger and issue map before code depends on them.
