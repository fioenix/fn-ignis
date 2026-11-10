# Implementation Plan: Retire Seeded Market Domain Vocabulary

**Branch**: `023-retire-domain-vocabulary` | **Date**: 2026-11-11 | **Spec**: [spec.md](spec.md)
**Baseline**: `b08af56`; owner decisions in the spec's Clarifications.

## Summary

Stop using market-domain lexicon rows as localization evidence and as synonym groups, delete the 104 seeded
rows from shipped seeds and from existing stores, and remove the two unreachable readers of that vocabulary.
Every MCP tool keeps its name and parameters; no persisted evidence changes.

## Workflow and depth gate

Source: `finolabs-vibecode:fnl-coding-router`, repository Spec Kit skills (`.agents/skills/speckit-*`; the
Claude session reads them as files because they are not registered as Claude skills, an integration gap).
Path: `specify → plan → tasks → implement`. Depth: **NORMAL**, trigger **consumers**. The direct path fails
the depth gate: the change crosses a migration boundary and three seams (engines, seeds/migration, dead
code), so `tasks.md` orders them. No security-review trigger beyond a tool description change; the posted
security review still runs before merge.

## Technical Context

- Python 3.11+, existing pytest; no dependency change.
- Both SQLite and PostgreSQL adapters run the new migration; local proof uses temporary SQLite only.
- The development store `.fnignis/canonical.sqlite3` holds the 104 rows; the owner waived a backup.

## Constitution Check

PASS. I–IV unchanged. V: no vocabulary moves into code; the change removes a mechanism and its data, and the
remaining machinery domains stay data-driven. VI: lexicon rows are not evidence; no evidence transform.
VII unaffected.

## Consumer map

| Seam | Areas and disposition |
|---|---|
| Synchronization | `infrastructure/config/vocabulary_loader.py`: `synchronize_vocabulary` stops calling `register_terms` and `register_synonym_groups`. Decide from callers whether `MarketVocabulary.positive_terms` and `by_domain_and_category` still have a reader; remove fields with none. `is_market_vocabulary_domain` stays only if a reader remains. |
| Engines | `harness/quality_evaluator.py`, `harness/strategic_reasoner.py`: remove `register_terms`, `_custom_lexicon` and the `custom_lexicon` constructor argument; `StrategicMarketReasoner` also loses `register_synonym_groups`, `_synonym_index` and the expansion loop in `_matches_topic_strictly`. The detector's `extra_terms` parameter stays for any other caller; pass nothing from these engines. |
| Tool handler | `interfaces/mcp/server.py` `handle_register_domain_lexicon` (around line 3286): stop live-registering terms into the two engines; keep foreign-stopword and noise registration. Update the `register_domain_lexicon` description only; name and parameters unchanged. |
| Seeds | `sql/003_market_lexicons.sql`: delete the rows of `tech`, `ecommerce`, `fashion`, `common_vi`; keep the table DDL and `foreign_stopwords`. `sql/004_global_lexicons.sql`: delete the `global_*` rows; keep `noise_blacklist`. |
| Migration | New `sql/040_retire_market_domain_vocabulary.sql`, modelled on `sql/020`: `DELETE FROM market_lexicons WHERE created_by = 'system' AND domain IN (seven domains)`; idempotent. Add it to the SQLite bootstrap retirement list (`sqlite_repository.py` around line 2149) and to whatever list ships or applies PostgreSQL migrations and the packaged `sql` resources (`test_sql_packaging.py` names the contract). |
| Dead code | Delete `application/use_cases/ingest_trends.py` and its construction and `"ingest_use_case"` entry in `server.py`; delete `harness/refinement_orchestrator.py`. `ConnectorRegistry.fetch_from_all` stays. |
| Tests | Remove tests that only assert the removed behaviour (`test_market_lexicons.py`, `test_round2_regressions.py` synonym/register cases, `test_vocabulary_loader.py` seed-keyword case). `test_corpus_correctness.py` and `tests/integration/test_ingest_orchestration.py` use `IngestTrendsUseCase`: where a test proves a gate that the live path still uses, re-point it to `fetch_from_all` or the live entry point; where it proves only the removed use case, delete it. Record each disposition in the commit body. |
| Guidance | Search `docs/`, `.agents/skills/ignis-*`, `src/ignis/interfaces/mcp/guides/`, README pair for promises that registered domain terms improve matching or quality; correct them. `BACKLOG.md` item closes with the measured numbers. |

## Validation

1. RED first: the three synthetic titles from the spec's Evidence give the wrong result on the baseline.
2. Targeted runs only, at most two modules per command, `uptime` checked first: the touched unit modules,
   `tests/unit/test_public_mcp_contract.py`, `tests/unit/test_sql_packaging.py`,
   `tests/unit/test_repo_conventions.py`.
3. SC-002 rerun: the read-only measurement over the development store's 634 titles shows 572 localized,
   unchanged. SC-003: bootstrap a temporary SQLite store and an upgraded copy holding the 104 rows; both end
   with 0 `system` rows in the seven domains after a restart.
4. Posted code and security reviews before merge (`fnl-review-gate`).
