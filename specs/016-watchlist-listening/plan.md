# Implementation Plan: Watchlist Listening and Period Comparison

**Branch**: `codex/spec016-watchlist-listening` | **Date**: 2026-10-21 | **Spec**: [spec.md](spec.md)

**Status**: Drafted under the owner's overnight delegation of 21/10/2026; the decisions in
"Owner gates" below are the owner's to confirm. Depends on Spec 015 (migration 031, declared
accounts, tool `set_mission_declared_accounts`) being merged first.

## Summary

Add versioned watchlists, bind Attention missions to a watchlist version, and compute a read-only
watchlist-period snapshot: per topic and channel, two complete calendar periods' volume
indicators, rising and new terms, representative items and completeness, or the reason a channel
cannot be compared. The host agent renders it with a new packaged guide. Coverage is derived from
the probe outcomes runs already record; no scheduler is added.

## Technical Context

**Language/Version**: Python 3.11+ (CI 3.12).
**Primary Dependencies**: FastMCP and `mcp` as installed; no new dependency.
**Storage**: SQLite and PostgreSQL at parity; additive migration `sql/032_watchlists.sql`.
**Testing**: pytest; dual-backend fixtures in `tests/integration/conftest.py`; the migration-chain
marker for schema tests.
**Target Platform**: The local MCP server used by Claude Code, Claude Desktop and Codex.
**Constraints**: No scheduler or worker (Constitution I as amended); domain vocabulary in `sql/`
(Constitution V); period membership by publication time only for listening (amendment).
**Scale**: At most 10 topics × 20 keywords per watchlist; 13 months of observations.

## Constitution Check

| Principle | Status | Note |
|---|---|---|
| I. Mission-bound autonomy | Pass with amendment | Runs stay explicit missions; host routines need the Proposed amendment (FR-015). |
| II. Pluggable connectors | Pass | No connector change except the per-day request ceiling, read from `runtime_configs`. |
| III. Evidence-first | Amendment needed | Listening periods use publication time; collection windows and evidence frames keep the ingestion clock. Drafted as Proposed. |
| IV. Deterministic reports | Pass | The snapshot is deterministic; the guide constrains rendering like `ignis-track`. |
| V. Simplicity | Pass | Coverage derived from existing probe outcomes; three tables only. |
| VI. Evidence-gated migration | Pass | Additive migration; no stored evidence rewritten. Retention is an explicit action, not a migration. |

## Owner Gates

- **OG-1 (MCP surface)**: four new tools — `save_watchlist`, `get_watchlist`, `start_watchlist_run`,
  `get_watchlist_period_snapshot` — raising the count from 48 (after Spec 015) to 52. Existing
  signatures are unchanged. Taken under the overnight delegation; owner to confirm.
- **OG-2 (migration)**: additive `sql/032_watchlists.sql`. Taken under the overnight delegation.
- **OG-3 (constitution)**: the amendment text stays Proposed until the owner ratifies it.

## Project Structure

### Documentation (this feature)

```text
specs/016-watchlist-listening/
  spec.md, plan.md, research.md, data-model.md, quickstart.md, tasks.md
  contracts/mcp-surface.md
  checklists/requirements.md
```

### Source Code (repository root)

```text
sql/032_watchlists.sql                                  # new tables, owner-only
src/ignis/domain/watchlist.py                           # versions, periods, coverage, selection
src/ignis/application/use_cases/watchlist_period.py     # snapshot assembly
src/ignis/infrastructure/persistence/{sqlite,postgres}_repository.py
src/ignis/interfaces/mcp/server.py                      # four tools
src/ignis/interfaces/mcp/guides/ignis_listen.md         # period-view guide (packaged)
.agents/skills/ignis-listen/SKILL.md                     # same guide body as a skill
scripts/prune_expired_observations.py                   # explicit 13-month retention action
.specify/memory/constitution.md                          # Proposed amendment
tests/unit/test_watchlist_*.py, tests/integration/test_watchlist_*.py
```

## Complexity Tracking

None beyond the amendment. A dedicated coverage table was rejected in favour of deriving coverage
from `mission_probe_outcomes` (research R3).
