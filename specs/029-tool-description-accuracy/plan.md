# Implementation Plan: Tool Description Accuracy

**Branch**: `029-tool-description-accuracy` | **Date**: 2026-11-14 | **Spec**: [spec.md](spec.md)

## Summary

Rewrite five `@mcp.tool` description strings in `src/ignis/interfaces/mcp/server.py`, regenerate
the Hermes manifests with `scripts/sync_tool_manifests.py --write`, and rerun the Spec 028 eval on
Sonnet and Haiku to test the 50% pass criterion.

## Technical Context

**Files**: `src/ignis/interfaces/mcp/server.py` (five description strings),
`hermes_manifest.json` and `.hermes/tools.json` (regenerated),
`specs/029-tool-description-accuracy/result.md` (eval comparison), `BACKLOG.md` (AGX-2 status).

**Testing**: `tests/unit/test_tool_manifests_drift.py`, `tests/unit/test_public_mcp_contract.py`,
`tests/unit/test_tool_selection_eval.py` (the eval fixture still fits the catalog),
`tests/unit/test_repo_conventions.py`. Then the eval, 3 runs per model.

**Constraints**: description text only; names, parameters and schemas unchanged (FR-003).

## Evidence for each description

Handler behaviour was mapped on 14/11/2026 and spot-checked by hand:

- `discover_market_opportunities` (`handle_discover_market_opportunities`): read-only; refuses
  context-only input (`CONTEXT_ONLY`), unknown missions and MARKET missions without a confirmed Brief
  (`BLOCKED`, points to `confirm_market_brief`). MARKET returns the Claim Ledger or a Gap Report that
  withholds Opportunity Index, demand gap, white space, saturation and recommendations. ATTENTION
  returns no opportunities. Legacy missions without a surface still return indexed topics.
- `get_mission_analysis`: read-only; same gates; returns stats, top signals (limit 1–50, optional
  platform) and author concentration; MARKET adds only the Claim Ledger or Gap Report; ATTENTION
  adds a quality scorecard, channel summaries and insights but no opportunities; legacy missions
  without a surface still return scored topics with recommendations.
- `execute_mission_ingress`: collects and writes; refuses a terminal mission (`TERMINAL`), missing
  manifest or authority (`BLOCKED`), a MARKET mission without a confirmed Brief (`BLOCKED`) and a held
  writer slot (`CONFLICT` with `active_run_id`, see `release_mission_writer`). Host-browser sources
  run through `prepare_host_browser_search` in MISSION mode.
- `get_current_session_mission`: `repository.get_mission(session_id)` matches `id` or `shortcode`
  only on SQLite (`WHERE id = ? OR shortcode = ?`); the PostgreSQL repository also matches
  `session_id` and an id prefix.
- `verify_connectors_health`: writes a sentinel cluster to the store, writes audit alerts, and calls
  each connector's `is_healthy()`, which contacts live sources (YouTube reserves quota); Threads is
  reported without a network probe.

## Constitution Check

No change to collection, evidence, report builders, migrations or author identity. Principle V
(surgical): five strings plus regenerated manifests. Pass.

## Depth gate (Spec Kit)

Direct path, no `tasks.md`: one seam (description strings and their derived manifests), known
consumers (the two manifests and the drift tests), no ordering, no migration or dependency. MCP tool
names and parameters are unchanged, so the owner-gated signature boundary is not crossed.
