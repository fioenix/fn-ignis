# Implementation Plan: Close Spec 023 Follow-ups

**Branch**: `024-close-spec-023-follow-ups` | **Date**: 2026-11-11 | **Spec**: [spec.md](spec.md)
**Baseline**: `89971c2` (v0.10.0 plus the released banner).

## Summary

Align the PostgreSQL upsert with SQLite, correct guidance, and remove the untargeted ingress pass, moving
each live gate's proof to `search_with_outcomes`.

## Workflow and depth gate

Path: `specify → plan → tasks → implement`. Depth: **NORMAL**, trigger **consumers**. Direct implementation
fails the depth gate: test proofs must move in order before code is deleted. No migration, dependency or
tool-signature change.

## Constitution Check

PASS. I is strengthened: no untargeted discovery code remains. V: surgical removal, no new vocabulary.
VI: no evidence migration. VII: `_apply_scope_guard` stays, because `search_with_outcomes` calls it.

## Consumer map

| Seam | Areas and disposition |
|---|---|
| Upsert | `persistence/postgres_repository.py::register_lexicon_terms`: `ON CONFLICT (domain, term) DO UPDATE SET category = EXCLUDED.category, created_by = EXCLUDED.created_by`. Parity test in `tests/integration/test_meta_host_evidence_backend_parity.py` or the closest two-backend module. |
| Guidance | `AGENTS.md` (done by the coordinator). `list_domain_lexicons` description in `interfaces/mcp/server.py`; regenerate with `scripts/sync_tool_manifests.py --write`. |
| Registry | `connectors/registry.py`: remove `fetch_from_all`; remove `_stamp_discovered_provenance`, `_build_probe_keywords`, `_collect_pass_results`, `_safe_fetch` only if no other caller remains. Keep `_apply_scope_guard`, `_safe_search`, `search_with_outcomes`, `search_across_all`. |
| Port members | `application/ports/connector_port.py::feed_yields_candidate_topics` and `default_feed_scope`, with their overrides in `youtube_plugin.py`, `threads_plugin.py`, `reels_plugin.py`: remove only when nothing else reads them, including `tests/unit/test_source_map_matches_connectors.py`. The connectors' untargeted fetch method stays if the port or a health path requires it; record the decision in the commit body. |
| Tests to move | `test_self_content_scope.py`, `test_regional_script_gate.py`, `test_connector_daily_ceiling.py`, `test_registry.py`, `test_corpus_correctness.py`, `test_google_suggestion_integrity.py`, `test_source_map_matches_connectors.py`, `tests/integration/test_ingest_orchestration.py`. Each: re-point to `search_with_outcomes` where the gate exists there, otherwise delete and record why. |
| Backlog | Close the `fetch_from_all` debt in `BACKLOG.md`, and record the upsert alignment. |

## Validation

Targeted modules through the load-aware wrapper, at most two per command, `PYTHONPATH=src`. The PostgreSQL
parity case and the full suite run in CI. Code and security reviews are posted before merge.
