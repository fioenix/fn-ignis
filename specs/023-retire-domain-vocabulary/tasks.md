# Tasks: Retire Seeded Market Domain Vocabulary

**Input**: [spec.md](spec.md), [plan.md](plan.md). Tests come first in each story: observe the RED before the change.

## Phase 1: User Story 1 — no seeded vocabulary in matching or language checks (P1)

- [ ] T001 [US1] Add failing tests in `tests/unit/test_vocabulary_loader.py` (or the closest existing module): with market-domain rows in a temporary SQLite store and a synchronized `StrategicMarketReasoner` and `QualityEvaluator`, `"Lazada sale 11.11 giảm giá"` does not match `shopee`, `"How to make bánh mì tại nhà"` does not match `n8n`, and `"Make a chatbot with n8n and zapier"` is not localized for VN. Observe RED on the baseline.
- [ ] T002 [US1] Add a parity test: after synchronization, foreign stopwords, noise blacklist, ambiguous unigrams, foreign phrases and Portuguese words still reach their engines.
- [ ] T003 [US1] Remove `register_terms`, `_custom_lexicon` and the `custom_lexicon` argument from `quality_evaluator.py` and `strategic_reasoner.py`; remove `register_synonym_groups`, `_synonym_index` and the expansion loop from `strategic_reasoner.py`; stop `vocabulary_loader.py` and `handle_register_domain_lexicon` in `server.py` from calling them. Drop `MarketVocabulary` fields and helpers left with no reader. T001–T002 green.
- [ ] T004 [US1] Update the `register_domain_lexicon` tool description so it no longer promises Quality Gate or Ingress recognition; name and parameters unchanged. `tests/unit/test_public_mcp_contract.py` green.

## Phase 2: User Story 2 — no seeded market rows in any store (P2)

- [ ] T005 [US2] Add failing tests: a fresh temporary SQLite store has 0 `system` rows in `tech`, `ecommerce`, `fashion`, `common_vi`, `global_saas_ai`, `global_ecommerce`, `global_fashion`; a store pre-loaded with those rows has 0 after bootstrap and after a second bootstrap; machinery-domain row counts are unchanged; an operator (`created_by != 'system'`) row in `tech` survives.
- [ ] T006 [US2] Remove the seven domains' rows from `sql/003_market_lexicons.sql` and `sql/004_global_lexicons.sql`; add `sql/040_retire_market_domain_vocabulary.sql` (idempotent, `system` rows only, header in the style of `sql/020`); register it in the SQLite bootstrap retirement list and in the packaging and PostgreSQL migration contracts. T005 and `tests/unit/test_sql_packaging.py` green.

## Phase 3: User Story 3 — no dead reader (P3)

- [ ] T007 [US3] Delete `src/ignis/application/use_cases/ingest_trends.py`, its construction and `"ingest_use_case"` entry in `server.py`, and `src/ignis/infrastructure/harness/refinement_orchestrator.py`. For each test using them (`test_corpus_correctness.py`, `test_vocabulary_loader.py`, `tests/integration/test_ingest_orchestration.py`), re-point it to `ConnectorRegistry.fetch_from_all` when it proves a gate that path still has, or delete it when it proves only the removed code; list each disposition in the commit body.
- [ ] T008 [US3] Correct guidance that promises domain terms improve matching or quality (`docs/`, `.agents/skills/ignis-*`, `src/ignis/interfaces/mcp/guides/`, README pair); leave dated history alone.

## Phase 4: Acceptance

- [ ] T009 Run the touched modules (at most two per command, `uptime` first), `tests/unit/test_public_mcp_contract.py`, `tests/unit/test_sql_packaging.py` and `tests/unit/test_repo_conventions.py`; record results in `.handoff/023-verification.md`.
- [ ] T010 Rerun the read-only localization measurement over the development store's 634 titles against the new code without applying the migration to it; expect 572 localized. Record it in `.handoff/023-verification.md`.
- [ ] T011 Close the backlog item in `BACKLOG.md` with the measured numbers and add `fetch_from_all` as the remaining dead-code debt.
