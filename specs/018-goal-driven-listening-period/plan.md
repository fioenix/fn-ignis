# Implementation Plan: Goal-Driven Listening Period

**Branch**: `claude/goal-driven-period` | **Date**: 2026-10-26 | **Spec**: [spec.md](spec.md)

**Status**: Drafted after the owner approved the clarified spec on 26/10/2026. The owner approved
OG-1, OG-2 and OG-3 on 26/10/2026 (see "Owner gates").

## Summary

A watchlist records the user's listening plan: a goal sentence, a comparison period and a research
cadence (snapshots per period), kept as an append-only history so each period is judged against the
plan in effect for it. The period snapshot gains a seen axis: per topic and channel, what the
snapshots taken in each period showed, averaged per snapshot, comparable when no more than 20
percent of the snapshots the plan calls for are missing. The existing figures stay as the created
view, unchanged and labelled. The routine guide schedules the recorded cadence and asks for one
when none is recorded. No scheduler is added.

## Technical Context

**Language/Version**: Python 3.11+ (CI 3.12).
**Primary Dependencies**: FastMCP and `mcp` as installed; no new dependency.
**Storage**: SQLite and PostgreSQL at parity; additive migration `sql/035_watchlist_listening_plans.sql`
and the matching inline SQLite DDL in `sqlite_repository.py`.
**Testing**: pytest; dual-backend fixtures in `tests/integration/conftest.py`; unit tests for the
pure seen-axis computation in `domain/watchlist_period.py`.
**Target Platform**: The local MCP server used by Claude Code, Claude Desktop and Codex.
**Constraints**: No scheduler or worker (Constitution I); every listening figure states its axis
(spec FR-004); created-view figures must be byte-identical before and after (SC-004).
**Scale**: At most 10 topics × 20 keywords per watchlist; a month holds at most 31 snapshots per
channel (cadence no faster than daily).

## Constitution Check

| Principle | Status | Note |
|---|---|---|
| I. Mission-bound autonomy | Pass with amendment | Each firing stays one explicit run. Recording the user's cadence is data, not a scheduler; the amendment states this (FR-013). |
| II. Pluggable connectors | Pass | No connector change. |
| III. Evidence-first | Amendment needed | The seen axis places observations by the exact ingestion clock of the snapshot; the created view keeps publication time. Drafted as Proposed. |
| IV. Deterministic reports | Pass | The snapshot stays deterministic; the `ignis_listen` guide is updated to render both axes with their labels. |
| V. Simplicity | Pass | One table, one tool; the seen axis reuses probe outcomes, judgments and `first_seen` already computed by the period use case. |
| VI. Evidence-gated migration | Pass | Additive migration; no stored evidence is read or rewritten by it. |
| VII. No author identity | Pass | No new identity field; the seen axis reports counts and content-only items as today. |

Post-design re-check (after Phase 1): unchanged; the design adds no field that carries identity and
no write path outside the listening-plan table.

## Owner Gates

- **OG-1 (MCP surface)**: one new tool `set_watchlist_listening_plan` (52 → 53 tools);
  `get_watchlist_period_snapshot.period_kind` becomes optional and defaults to the plan's period;
  `get_watchlist` and the snapshot gain additive response fields. See
  [contracts/mcp-surface.md](contracts/mcp-surface.md). AGENTS.md section 8 requires the owner's
  approval for the signature change.
- **OG-2 (migration)**: additive `sql/035_watchlist_listening_plans.sql`; the agent may decide it
  (AGENTS.md section 8, checked against Constitution VI) and records it here.
- **OG-3 (constitution)**: Principles I and III amendment as FR-013 states it.

Owner decision, 26/10/2026: OG-1, OG-2 and OG-3 approved. OG-3 approves the amendment's direction;
the owner reviews its exact wording in the Part B pull request before that pull request merges.

The feature lands in two pull requests: Part A (US1, US4: listening plan storage, the new tool,
the optional period kind that US1's acceptance needs, the routine guide) needs no amendment;
Part B (US2, US3: the seen axis, the `ignis_listen` guide and the amendment wording) merges after
the owner has reviewed that wording.

## Execution path (Spec Kit depth gate)

`speckit-tasks` then `speckit-implement`, not a direct pass: the change crosses a migration, an MCP
signature and a constitution amendment, and it lands in two ordered pull requests.

## Project Structure

### Documentation (this feature)

```text
specs/018-goal-driven-listening-period/
  spec.md, plan.md, research.md, data-model.md, quickstart.md
  contracts/mcp-surface.md
  checklists/requirements.md
```

### Source Code (repository root)

```text
sql/035_watchlist_listening_plans.sql                   # new append-only table, owner-only
src/ignis/domain/watchlist.py                           # ListeningPlan, validation, plan-in-effect lookup
src/ignis/domain/watchlist_period.py                    # seen-axis cells beside the created view
src/ignis/application/use_cases/watchlist_period.py     # snapshots per run and channel, plan lookup
src/ignis/infrastructure/persistence/{sqlite,postgres}_repository.py, workspace_repository.py
src/ignis/interfaces/mcp/server.py                      # new tool, optional period_kind
src/ignis/interfaces/mcp/guides/ignis_listen.md         # both axes, labels
src/ignis/interfaces/mcp/guides/ignis_routine.md        # cadence from the plan, ask when absent
.agents/skills/ignis-listen/SKILL.md, .agents/skills/ignis-routine/SKILL.md   # mirrors
.specify/memory/constitution.md                          # Proposed amendment (Part B)
README.md, README.vi.md, docs/USER_GUIDE.md, docs/USER_GUIDE.vi.md   # tool count, migration endpoint
tests/unit/test_watchlist_listening_plan.py, tests/unit/test_watchlist_seen_axis.py
tests/integration/test_watchlist_listening_plan_storage.py      # both backends
```

Consumers of the migration chain endpoint that move from 034 to 035: `tests/integration/conftest.py`,
`tests/integration/test_compose_init.py`, `tests/unit/test_sql_packaging.py`,
`tests/unit/test_public_distribution_contract.py`, the README and user-guide migration lines.

## Complexity Tracking

None. The seen axis is a second reading of data the period use case already loads; no new store,
worker or connector path.
