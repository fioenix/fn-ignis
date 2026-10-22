# Implementation Plan: Host-Scheduled Watchlist Routines

**Branch**: `codex/spec017-routine-setup` | **Date**: 2026-10-21 | **Spec**: [spec.md](spec.md)

**Status**: Drafted under the owner's overnight delegation of 21/10/2026; implemented 22/10/2026
after Spec 016 merged and the amendment was ratified.

**T001 record (22/10/2026)**: base `main` at `2f08c47`; 52 tools; constitution 2.2.1 (the Spec 016
amendment ratified in 2.2.0); golden-set baseline of 22/10/2026 in the owner's local
`.handoff/product/golden-set-runs/2026-10-22/` (scores also in Spec 016 T019). Host probe in
`.handoff/spec017/host-probe.handoff.md`: a manual task created from this session fired locally in
the repository folder, reached the local Ignis server, resolved the caller root (1 workspace, no
`ROOT_REQUIRED`), and was saved in the session's Auto mode. The probe refines FR-007 and FR-020
(spec clarifications of 22/10/2026) and contradicts nothing else in the Context.

## Summary

Add one packaged guide, `ignis-routine`, served as the MCP prompt `ignis_routine` and the resource
`fn-ignis://guide/ignis-routine` and mirrored as `.agents/skills/ignis-routine/SKILL.md`. It tells
the host agent how to turn an explicit user request into one Claude Code Desktop scheduled task that
runs one watchlist daily, and how to list, change, pause and remove it. The guide carries the
routine prompt template. Ignis gains no tool, table, dependency, scheduler or worker.

## Technical Context

**Language/Version**: Python 3.11+ (CI 3.12); the deliverable is mostly a Markdown guide.
**Primary Dependencies**: FastMCP prompt and resource registration as used by `ignis_track`.
**Storage**: None. The routine lives in the host (`~/.claude/scheduled-tasks/{taskId}/SKILL.md`).
**Testing**: pytest unit tests in the style of `tests/unit/test_ignis_track_guidance.py`; one
manual Claude Code Desktop acceptance run recorded in `.handoff/spec017/`.
**Target Platform**: Claude Code Desktop local scheduled tasks reaching the local Ignis MCP server.
**Constraints**: Constitution I as amended by Spec 016 (routines only on explicit request, none
inside Ignis); `test_ignis_skills.py` keeps "daily" and "scheduler" out of `ignis-collect` and
`ignis-analyze`, so routine guidance lives only in the new guide.

## Constitution Check

| Principle | Status | Note |
|---|---|---|
| I. Mission-bound autonomy | Needs the Spec 016 amendment | Each firing is an explicit watchlist run; the schedule is host-owned and user-requested. Today's text forbids an "unattended scheduled sweep", so merge waits for ratification (FR-012). |
| II. Pluggable connectors | Pass | No connector change; ceilings come from Spec 016. |
| III. Evidence-first | Pass | No analysis change. |
| IV. Deterministic reports | Pass | No report change; a period view on a firing follows the Spec 016 guide. |
| V. Simplicity | Pass | Guide only; no tool, table or dependency. |
| VI. Evidence-gated migration | Pass | No migration. |

## Owner Gates

- **OG-1 (constitution)**: the Spec 016 amendment must be ratified before merge.
- **OG-2 (MCP surface)**: one new prompt and one new resource; no tool or signature change. Taken
  under the overnight delegation; owner to confirm.

## Project Structure

### Documentation (this feature)

```text
specs/017-watchlist-routines/
  spec.md, plan.md, research.md, quickstart.md, tasks.md
  contracts/routine-guide.md
  checklists/requirements.md
```

### Source Code (repository root)

```text
src/ignis/interfaces/mcp/guides/ignis_routine.md   # packaged guide with the routine prompt template
src/ignis/interfaces/mcp/server.py                 # prompt ignis_routine, resource fn-ignis://guide/ignis-routine
.agents/skills/ignis-routine/SKILL.md               # identical body
openclaw.json / catalogs listing prompts and resources
tests/unit/test_ignis_routine_guidance.py
```

## Complexity Tracking

None. An Ignis-side routine table and a `trigger` field on `start_watchlist_run` were rejected
(research R2): the host already lists, pauses and removes its tasks, and a second record would drift
from it.
