# Implementation Plan: UAT Evidence Integrity

**Branch**: `release/v0.8.0` (actual checkout retained) | **Date**: 2026-10-04 | **Spec**: [spec.md](spec.md)

## Summary

Finish initial UAT, turn observed defects into issues and lessons, implement query-bound response admission, then repeat all twelve UAT cases. Login, JSON traffic and caption keyword matches cannot prove search execution or commercial demand. Existing Spec 012 and owner edits remain intact.

## Technical Context

**Language/Version**: Python 3.11+; local 3.13.
**Primary Dependencies**: Existing FastMCP, Playwright, httpx, pytest; no new dependencies.
**Storage**: Isolated SQLite UAT plus PostgreSQL behavioral contracts. Owner-approved UAT-50 migration 026 changes only the partial-outcome CHECK; preserve every evidence row and ID, validate existing SQLite upgrades and disposable PostgreSQL, never apply to Supabase in this task.
**Testing**: TDD at capture/extraction/attestation boundary, actual stdio MCP, finite live UAT, maintained visual reports, installed wheel and final dual-backend gates.
**Target Platform**: Existing desktop operator and package runtimes.
**Project Type**: Agent harness / MCP package.
**Performance Goals**: Recorded finite query/sample/time limits; no background collection after termination.
**Constraints**: No secret/private-body logging, posts/messages, paid collection, MCP signature or connector-tier changes.
**Scale/Scope**: All U01–U12 cases in uat-ledger.md; not a Threads-only or unit-only substitute.

## Constitution Check

I: Explicit owner-delegated finite task; deterministic raw collection. II: Public authorized sessions only, visible failures, no fallback authority expansion. III: Existing source/mission/frame/qualification/claim authority; no fabricated live sufficiency. IV: Maintained templates only. V: Small query-proof seam with complete shared-consumer audit. VI: Owner approved migration 026 for isolated rehearsals; no release bump, integration remains separately evidenced.

Pre-design and post-design gates pass under these constraints; no exception requested.

## Phase 0: Research and baseline

Inspect live diagnostic and offline reproduction. Complete missing baseline qualification/Market/claims/error/render cases. Consumer research confirms shared capture serves Threads trending and Reels, while direct GraphQL serves suggestions too. Preserve those contracts. Current public post envelope is not live-verified: known fixtures provide supported legacy shapes, not an upstream guarantee. Unknown shapes fail closed; absent search navigation remains a distinct investigation.

## Phase 1: Design

1. One deterministic public query-response proof must admit both extraction and execution: exact supported request variable, successful status/no errors, recognized public post-search envelope.
2. Add optional query restriction to shared capture; default non-search behavior stays unchanged. Filter before retaining bodies, and extract only the admitted public result subtree. Audit cache admission so unrelated request keys do not prove a public-search operation.
3. Direct and browser paths use the same envelope rule. Valid empty search is accepted without needless fallback; unknown/error/missing answer fails attestation and remains DEGRADED. Sending a direct query is not returned-result proof.
4. Duplicate source identities may deduplicate records, but query proof stays independent. Keep the legacy first `matched_keyword` for clustering, retain ordered unique observed query hits in `matched_keywords`, and expose additive `probe_keywords` in qualification batches. Both browser transports and Graph API must preserve overlapping hits without repeated insight requests; existing observation metadata stores the list without a schema migration or historical backfill. Unknown windows remain null.
5. Preserve the local Attention saturation-advice fix; Market claims remain current-frame ledger only. Real business gaps and controlled positive-path contract fixtures remain separate.
6. Actual structural investigation verified server-rendered public results outside the XHR observer. Extend the existing browser tier to admit only a complete, error-free BarcelonaSearchResultsQuery result whose stream preloaderID matches the expected exact-query preloader on an HTTP-200 exact navigation request. Apply the existing public-envelope validator and project only admitted public results. Do not replace the connector, add stealth bypasses or silently widen sampling. Wrong-query/viewer/background/malformed/incomplete/empty cases need independent regressions.
7. Repeat every UAT case after all fixes; exact final wheel/runtime, visual artifacts, errors/cancellation, backend and review evidence are mandatory.

## Project Structure

```text
specs/013-uat-evidence-integrity/{spec,plan,research,data-model,quickstart,tasks,uat-ledger}.md
specs/013-uat-evidence-integrity/contracts/query-proof-and-uat.md
src/ignis/infrastructure/connectors/meta_browser_ingress.py
src/ignis/infrastructure/connectors/threads/threads_plugin.py
src/ignis/infrastructure/connectors/registry.py
src/ignis/infrastructure/harness/strategic_reasoner.py
tests/unit/{test_social_search_integrity,test_meta_browser_ingress,test_threads_direct_graphql,test_data_provenance}.py
tests/integration/test_evidence_grounded_market_mission.py
.handoff/  # ignored runtime evidence only
```

**Structure Decision**: Extend existing response/evidence boundaries; no second bridge, database or claim policy.

## Delivery

Each acceptance row needs baseline, issue/task linkage and final exact-revision proof. Default suite skips cannot replace real/backend coverage. Run code/security review, package/installed MCP and full final UAT. Actual authorized integration/activation or explicit park is required; this plan alone proves neither.
