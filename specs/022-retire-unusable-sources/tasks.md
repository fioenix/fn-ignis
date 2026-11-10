# Tasks: Retire Unusable Source Connectors

**Input**: spec.md, plan.md, research.md, data-model.md, contracts/source-retirement.md, quickstart.md.
**Tests**: test-first, observed behavioral RED before each implementation seam.

## Phase 1: Setup

- [x] T001 Inspect baseline, scoped instructions and consumer map in specs/022-retire-unusable-sources/plan.md.
- [x] T002 Generate design artifacts under specs/022-retire-unusable-sources/ and initialize .handoff/022-verification.md.

## Phase 2: Foundation

- [ ] T003 Freeze the 42 surviving parameter schemas in tests/fixtures/source_retirement/survivor-schemas.json and establish serial offline test execution in .handoff/022-verification.md.

## Phase 3: US1 — Active catalog and admission (P1, MVP)

Independent proof: exactly 42 tools, no retired connector in composition or health; every retired
required/optional resource refused before a connector, quota or writer is touched.

- [ ] T004 [US1] Add catalog/composition/diagnostic/comments-session RED cases in tests/unit/test_source_retirement.py and update tests/unit/test_public_mcp_contract.py.
- [ ] T005 [US1] Remove eleven handlers and retired registrations in src/ignis/interfaces/mcp/server.py; remove setup RSS readiness probe in src/ignis/interfaces/cli/setup_bundle.py and registrations in scripts/generate_sample_case_studies.py.
- [ ] T006 [US1] Remove exclusive acquisition code and vocabulary registration wiring in src/ignis/infrastructure/connectors/ and src/ignis/infrastructure/config/vocabulary_loader.py; retain shared comments, identity, historical mappers and template-domain exclusions.
- [ ] T007 [US1] Add mission creation/execution/host-preparation RED cases in tests/unit/test_source_retirement.py.
- [ ] T008 [US1] Enforce typed retired-resource admission in src/ignis/domain/research_workspace.py, src/ignis/application/use_cases/create_attention_mission.py, confirm_market_brief.py, execute_mission.py, host_browser_mission.py, src/ignis/infrastructure/connectors/registry.py and MCP error serialization.
- [ ] T009 [US1] Resolve the surviving pain-point tool dependency recorded in specs/022-retire-unusable-sources/plan.md before changing src/ignis/interfaces/mcp/server.py::handle_extract_customer_pain_points.
- [ ] T010 [US1] Verify kept comments, YouTube, host-browser and self-content consumers; record exact commands in .handoff/022-verification.md and commit the complete seam.

## Phase 4: US2 — Watchlist continuation and retained evidence (P2)

Independent proof: mixed requests create survivor-only runs with retirement reasons, all-retired
requests create nothing, and old manifests/observations/outcomes/sessions remain readable unchanged.

- [ ] T011 [US2] Add mixed/all-retired and retained-evidence tests in tests/unit/test_source_retirement.py and tests/integration/test_source_retirement_storage.py; observe reduction RED.
- [ ] T012 [US2] Reduce only new run authority resources in src/ignis/application/use_cases/watchlists.py and return explicit retirement entries.
- [ ] T013 [US2] Document historical purpose of CHANNEL_ORDER/SAMPLED_CHANNELS in src/ignis/domain/watchlist_period.py and SUPPLY_SURFACE_PLATFORMS in src/ignis/domain/research_workspace.py; preserve template/read behavior.
- [ ] T014 [US2] Verify SQLite preservation and existing period/seen-axis contracts; record PostgreSQL-only checks as pending in .handoff/022-verification.md and commit the seam.

## Phase 5: US3 — Guidance and distribution (P3)

Independent proof: shipped catalogs match runtime, all governed tool counts are 42, and current
instructions route only to retained collection. Historical evidence documentation is labelled.

- [ ] T015 [US3] Add source-guidance regression checks in tests/unit/test_source_retirement.py; update catalog and smoke expectations in tests/unit/test_tool_manifests_drift.py, test_public_distribution_contract.py and scripts/wheel_mcp_smoke.py.
- [ ] T016 [US3] Update AGENTS.md Collection/count, CLAUDE.md, README*.md, docs/USER_GUIDE*.md, BACKLOG.md, active docs/agents/ guidance and source diagrams; update .agents/skills/ignis-*/ and src/ignis/interfaces/mcp/guides/ together.
- [ ] T017 [US3] Update openclaw.json and server.json; regenerate hermes_manifest.json and .hermes/tools.json with scripts/sync_tool_manifests.py --write; run distribution/doc/convention gates and commit the seam.

## Phase 6: Final verification

- [ ] T018 Review final diff, perform specs/022-retire-unusable-sources/quickstart.md checks, run Spec Kit convergence, and record completed/open tasks and review limits in .handoff/022-verification.md.

## Dependencies and execution

T001 → T002 → T003 → US1 (T004–T010) → US2 (T011–T014) → US3 (T015–T017) → T018.
Each test task precedes its matching implementation. T009 alone waits on owner disposition; no
replacement collection workflow is in scope. No new migrations, sources, features or dependencies.
MVP is US1; delivery here additionally requires US2 and US3. Commits are local, explicit-path only.

Parallel examples: US1 catalog research and admission research have independent outputs; US2
storage and period checks can be prepared separately; US3 English/Vietnamese edits could be split.
This execution uses no parallel agents or test processes because of the offline/serial boundary
and shared server ownership. No [P] tasks are authorized in this run.
