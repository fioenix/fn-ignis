---

description: "Task list for Spec 017 — Host-Scheduled Watchlist Routines"
---

# Tasks: Host-Scheduled Watchlist Routines

**Input**: [spec.md](spec.md), [plan.md](plan.md), [research.md](research.md),
[contracts/routine-guide.md](contracts/routine-guide.md), [quickstart.md](quickstart.md)

**Tests**: Included and written first; each test task must be observed failing before its
implementation task.

**Prerequisites**: Spec 016 merged to `main` (watchlists, `start_watchlist_run`, ceilings); the owner
has ratified the Spec 016 constitution amendment (OG-1); and the golden-set baseline, ordered before
this spec in the decision record, has run and its recorded result is linked from `plan.md`. Stop
before T002 if any is missing.

## Phase 1: Setup

- [x] T001 Rebase on `main` after Spec 016 merges; record the base commit, the tool count, the
  constitution version and the golden-set baseline artifact in `plan.md`. Probe the current Claude
  Code Desktop scheduled-task tools: where a new task runs (local or cloud), its working folder, how
  it stores tool approvals, and whether a fresh firing reaches the local Ignis server with the
  workspace's caller root. Record the probe in `.handoff/spec017/host-probe.handoff.md`. Stop and
  report if the amendment is not ratified, the baseline is missing, or the probe contradicts the
  spec's Context.
  Done 22/10/2026: recorded in `plan.md`; probe in `.handoff/spec017/host-probe.handoff.md` (temporary task created with the owner's approval, run once, deleted).

## Phase 2: US1 and US2 — Set up a routine; each firing is one run (P1)

- [x] T002 Write failing tests in `tests/unit/test_ignis_routine_guidance.py`: the guide is packaged
  in the wheel; prompt `ignis_routine` and resource `fn-ignis://guide/ignis-routine` are listed and
  return it; a non-UUID `watchlist_id` is refused; serving starts no read; the SKILL body equals the
  packaged guide; the guide has the six contract sections; the routine template names
  `start_watchlist_run` and `execute_mission_ingress` once each and carries every FR-005
  prohibition; no credential placeholder, author field or OS scheduler command appears.
  Done 22/10/2026: `tests/unit/test_ignis_routine_guidance.py`; RED observed (9 of 10 failed, no guide).
- [x] T003 Write `src/ignis/interfaces/mcp/guides/ignis_routine.md` and
  `.agents/skills/ignis-routine/SKILL.md`; register the prompt and resource in `server.py` next to
  `ignis_track`; list them in the prompt and resource catalogs. T002 passes.
  Done 22/10/2026: guide, skill mirror, prompt, resource and `openclaw.json`; T002 passes.

## Phase 3: US3 and US4 — Change, stop, unsupported hosts (P2, P3)

- [x] T004 Extend T002's tests for the change, pause and remove section (delete only after
  confirmation) and the unsupported-host section; complete the guide.
  Done 22/10/2026 together with T002/T003: the change, pause and remove and the unsupported-host sections are in the same tests and guide.

## Phase 4: Polish

- [x] T005 [P] Document routines in README.md, README.vi.md, docs/USER_GUIDE.md and
  docs/USER_GUIDE.vi.md; Vietnamese through the vietnamizer core workflow.
  Done 22/10/2026: README.md, README.vi.md and both user guides; Vietnamese through the vietnamizer core workflow.
- [ ] T006 Run the Claude Code Desktop acceptance in [quickstart.md](quickstart.md) and record it in
  `.handoff/spec017/acceptance.handoff.md` (SC-001, SC-002, SC-003).
- [x] T007 Run the full suite, ruff, `git diff --check`, the package build and
  `scripts/wheel_mcp_smoke.py`; code and security review of the diff; dispose of findings with
  evidence before the PR.
  Done 22/10/2026 at the branch head: unit 2810 passed, integration on SQLite 1566 passed (PostgreSQL in CI); ruff and `git diff --check` clean; `uv lock --check` resolves; the built wheel ships `guides/ignis_routine.md` and `scripts/wheel_mcp_smoke.py` holds a session with 52 tools. Self-review of the diff: no tool or signature change, serving reads nothing, no credential or author field in the guide; the routine prompt names the watchlist the person wrote, which is their own text.
- [ ] T008 After activation, keep one real routine running on one golden-set watchlist for 14
  consecutive days and record the share of days with a completed run (SC-005) in
  `.handoff/spec017/routine-14-days.handoff.md`. The feature may merge before this finishes; the
  measurement is reported separately and sets no target.

## Dependencies

T001 gates everything. T002→T003→T004. T005 after T004. T006 needs T003 and Spec 016 merged. T007
last before the PR; T008 runs after activation and does not gate the merge.
