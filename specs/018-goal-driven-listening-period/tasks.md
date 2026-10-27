---

description: "Task list for Spec 018: Goal-Driven Listening Period"
---

# Tasks: Goal-Driven Listening Period

**Input**: Design documents from `/specs/018-goal-driven-listening-period/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/mcp-surface.md,
quickstart.md

**Tests**: Included. The plan names the test files and quickstart step 6 requires them on both
backends; write each test before the code it covers and confirm it fails first.

**Organization**: Phases follow delivery order rather than spec priority: Part A (US1, US4) is
one pull request and needs no constitution wording; Part B (US2, US3) is a second pull request
that merges after the owner reviews the amendment wording (plan.md, Owner gates). US2 is P1 but
depends on the plan storage built for US1.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: Which user story this task belongs to (US1 to US4)

## Rules every task follows

- `src/` and `tests/` are English; no domain vocabulary as Python constants (CLAUDE.md, AGENTS.md
  section 3).
- SQLite and PostgreSQL behave the same (FR-011); every repository change lands in both.
- No author identity at rest (Constitution VII); the seen axis reports counts and content-only
  items.
- Ignis gains no scheduler or worker (FR-012).

---

## Phase 1: Setup

- [x] T001 Rebase `claude/goal-driven-period` on `main` and record a green baseline of
  `.venv/bin/pytest tests/unit/test_watchlist_period.py tests/unit/test_watchlist_definition.py tests/integration/test_watchlist_mcp.py tests/integration/test_watchlist_repository.py tests/integration/test_watchlist_period_storage.py`
- [x] T002 Capture the pre-feature created-view output for SC-004: run
  `GetWatchlistPeriodSnapshotUseCase` on the fixtures used by `tests/unit/test_watchlist_period.py`
  for one day, one week and one month view and store the JSON responses under
  `tests/fixtures/watchlist_period_created_baseline/` before any source change

---

## Phase 2: Foundational (listening plan storage)

**Purpose**: The append-only plan table and its domain type, which US1, US4 and US2 all read.

- [x] T003 [P] Write failing domain tests in `tests/unit/test_watchlist_listening_plan.py`: goal
  trimmed to 1..300 characters; `period_kind` in day, week, month; `snapshots_per_period` in
  1..1 (day), 1..7 (week), 1..28 (month); an invalid plan raises with reason code
  `INVALID_LISTENING_PLAN`; `plan_in_effect(plans, at)` returns the latest plan whose
  `effective_from` is at or before `at` in Asia/Ho_Chi_Minh, or None (data-model.md)
- [x] T004 [P] Write failing storage tests in `tests/integration/test_watchlist_listening_plan_storage.py`
  for both backends via the fixtures in `tests/integration/conftest.py`: save and list oldest
  first; saving a plan identical to the one in effect inserts nothing; an UPDATE is refused by the
  trigger; deleting the watchlist cascades; on PostgreSQL row-level security is enabled and
  client roles hold no grant
- [x] T005 Create `sql/035_watchlist_listening_plans.sql`: table `watchlist_listening_plans`
  (columns and checks per data-model.md, primary key `(watchlist_id, effective_from)`, foreign key
  to `watchlists(id)` on delete cascade), an update-refusing trigger mirroring
  `refuse_watchlist_version_update` in `sql/032_watchlists.sql`, RLS enabled, no client grants
- [x] T006 Add the matching inline SQLite DDL and update-refusing trigger in
  `src/ignis/infrastructure/persistence/sqlite_repository.py`
- [x] T007 Move the migration chain endpoint from 034 to 035 in `tests/integration/conftest.py`,
  `tests/integration/test_compose_init.py`, `tests/unit/test_sql_packaging.py`,
  `tests/unit/test_public_distribution_contract.py`, `README.md`, `README.vi.md`,
  `docs/USER_GUIDE.md` and `docs/USER_GUIDE.vi.md`
- [x] T008 Add the `ListeningPlan` value object, its validation and `plan_in_effect` to
  `src/ignis/domain/watchlist.py` (makes T003 pass)
- [x] T009 Add `save_listening_plan` and `list_listening_plans` to
  `src/ignis/application/ports/repository_port.py` and implement them in
  `src/ignis/infrastructure/persistence/sqlite_repository.py` and
  `src/ignis/infrastructure/persistence/postgres_repository.py`; forward them in any caller-store
  wrapper that forwards the other watchlist methods (check
  `src/ignis/infrastructure/persistence/workspace_repository.py`) (makes T004 pass)

**Checkpoint**: T003 and T004 pass on SQLite and PostgreSQL.

---

## Phase 3: User Story 1 - State what to compare (Priority: P1), Part A

**Goal**: A watchlist records the user's goal, comparison period and cadence; the period view
defaults to that period.

**Independent Test**: record goal "Track weekly demand for sun-protection jackets", period week,
3 snapshots; the period view without `period_kind` compares the last two complete weeks.

- [x] T010 [P] [US1] Write failing tests in `tests/integration/test_watchlist_mcp.py` for
  `set_watchlist_listening_plan` per contracts/mcp-surface.md: `SAVED`, `UNCHANGED` on an
  identical second call, `INVALID` with `INVALID_LISTENING_PLAN` for each refusal in quickstart
  step 2 and nothing written, `NOT_FOUND`; the call starts no run
- [x] T011 [P] [US1] Write failing tests in `tests/integration/test_watchlist_mcp.py` for
  `get_watchlist` returning `listening_plans` (oldest first) and `listening_plan` (in effect or
  null), with every existing field unchanged
- [x] T012 [P] [US1] Write failing tests in `tests/unit/test_watchlist_period.py`: without
  `period_kind` the plan in effect at the clock's now decides it; with no plan the result is
  `INVALID` with `PERIOD_KIND_REQUIRED`; an explicit `period_kind` overrides the plan (acceptance
  scenario 2); changing the plan leaves versions, runs and evidence unchanged (acceptance
  scenario 3, FR-003); a watchlist with no plan still loads, runs and renders with an explicit
  `period_kind` (FR-010, SC-006)
- [x] T013 [US1] Implement the set-plan use case and the additive `get_watchlist` fields in
  `src/ignis/application/use_cases/watchlists.py`
- [x] T014 [US1] Make `period_kind` optional in `GetWatchlistPeriodSnapshotUseCase` in
  `src/ignis/application/use_cases/watchlist_period.py` per the contract
- [x] T015 [US1] Register `set_watchlist_listening_plan` and make `period_kind` optional on
  `get_watchlist_period_snapshot` in `src/ignis/interfaces/mcp/server.py`; add a case to
  `tests/unit/test_watchlist_caller_scope.py` proving the new tool routes to the caller store
- [x] T016 [US1] Move the tool count from 52 to 53 and list the new tool everywhere the drift and
  documentation tests read: `tests/unit/test_tool_manifests_drift.py`, `openclaw.json` and any
  other manifest that test compares, `tests/unit/test_public_doc_conventions.py`,
  `tests/unit/test_public_distribution_contract.py`, `CLAUDE.md`, `BACKLOG.md`, `README.md`,
  `README.vi.md`, `docs/USER_GUIDE.md`, `docs/USER_GUIDE.vi.md`

**Checkpoint**: quickstart steps 1 and 2 pass on a store copy.

---

## Phase 4: User Story 4 - The routine follows the user's cadence (Priority: P2), Part A

**Goal**: The routine guide schedules the recorded cadence and asks for one when none exists.

**Independent Test**: for period week with 3 snapshots, the guide proposes three firings a week on
distinct days, states the requests per week, and creates the routine only after confirmation.

- [x] T017 [P] [US4] Write failing guidance tests in `tests/unit/test_ignis_routine_guidance.py`:
  the guide reads the plan with `get_watchlist`; asks for goal, period and cadence when none is
  recorded and saves them with `set_watchlist_listening_plan` only after the user states them;
  labels any suggestion as a suggestion; maps N per week to N distinct weekdays and N per month to
  N distinct days of the month (research R7); states requests per period; refuses faster than
  daily; waits for confirmation before creating the routine
- [x] T018 [US4] Update `src/ignis/interfaces/mcp/guides/ignis_routine.md` to satisfy T017
- [x] T019 [US4] Mirror the guide change into `.agents/skills/ignis-routine/SKILL.md` and run
  whatever mirror check the repository has for guides and skills

**Checkpoint (Part A pull request)**: quickstart steps 1 to 3 pass; T020 to T030 not started on
this branch.

---

## Phase 5: User Story 2 - Compare what the snapshots showed (Priority: P1), Part B

**Goal**: Per topic and channel, a seen axis averaged per snapshot, judged against the cadence in
effect for each period.

**Independent Test**: on G3's stored runs (store copy, clock frozen after a complete week), the
week view's seen cells count every relevant item of each snapshot, including items published
months earlier, divided by the snapshots held (SC-001).

- [x] T020 [P] [US2] Write failing pure tests in `tests/unit/test_watchlist_seen_axis.py`:
  snapshots showing 40 and 30 relevant items average 35 (acceptance 1); an item shown on 25/10 and
  26/10 counts in both snapshots and is first seen only in the first (acceptance 2); a channel
  missing more than 20 percent of the snapshots called for is `not_comparable` with `snapshots`
  and `snapshots_called_for` (acceptance 3, FR-006); a snapshot counts only for the keywords it
  queried; a failed or ceiling-limited outcome is not a snapshot; two runs in one day are two
  snapshots; a week plan of 3 with 3 snapshots is comparable with no other days run (SC-002); an unassessed observation yields `seen_period_unjudged_snapshots` (research R5); no
  plan in effect yields `seen_period_without_cadence`; each period uses the plan in effect at its
  start; `created_in_period` counts shown items published in the period (FR-007); every figure
  carries `axis: "seen"`
- [x] T021 [US2] Implement the seen-axis computation in `src/ignis/domain/watchlist_period.py`
  per data-model.md and research R2 to R5, reusing `MAX_MISSING_SHARE`, `channel_values` and
  `_term_lists` (makes T020 pass)
- [x] T022 [US2] In `src/ignis/application/use_cases/watchlist_period.py`, build snapshots from
  `get_latest_completed_probe_outcomes` per run and channel timed at `completed_at`, look up the
  plan in effect for each period, attach `seen` cells to each topic and `listening_plan` for both
  periods to the response
- [x] T023 [US2] Extend `tests/integration/test_watchlist_period_storage.py` so the seen axis
  reads the same on SQLite and PostgreSQL
- [x] T024 [US2] Update `src/ignis/interfaces/mcp/guides/ignis_listen.md` and its mirror
  `.agents/skills/ignis-listen/SKILL.md`: seen axis first, created view second, each labelled;
  never sum across channels or axes; extend the guide's existing test if one exists

---

## Phase 6: User Story 3 - Creation dates enrich the analysis (Priority: P2), Part B

**Goal**: The created view stays as Spec 016 defines it, labelled.

**Independent Test**: created-axis figures equal the T002 baseline field for field.

- [x] T025 [P] [US3] Write failing tests in `tests/unit/test_watchlist_period.py`: the created
  cells equal the T002 baseline with only `axis: "created"` added (SC-004, acceptance 1); every
  figure in a period response states its axis (SC-003, acceptance 2)
- [x] T026 [US3] Add `axis: "created"` to each existing channel cell in
  `src/ignis/domain/watchlist_period.py`, changing nothing else (makes T025 pass)
- [x] T027 [US3] Draft the Principles I and III amendment in `.specify/memory/constitution.md`
  per FR-013 (seen axis by exact ingestion clock beside the created view by publication time,
  each labelled; a watchlist may record the user's cadence without Ignis gaining a scheduler),
  with the version bump and Sync Impact Report the constitution's governance section requires;
  the owner reviews the wording in the Part B pull request

---

## Phase 7: Polish and acceptance

- [x] T028 Run `.venv/bin/pytest tests/unit/test_repo_conventions.py` and `ruff check` on the
  changed files
- [x] T029 Run quickstart step 6 on SQLite and PostgreSQL:
  `.venv/bin/pytest tests/unit/test_watchlist_listening_plan.py tests/unit/test_watchlist_seen_axis.py tests/integration/test_watchlist_listening_plan_storage.py`
  plus every test file touched above
- [x] T030 Run quickstart steps 1 to 5 on a copy of the caller store with the clock frozen after
  a complete week, and record the outcome in `.handoff/` (not `docs/`)

---

## Dependencies

- Phase 1 → Phase 2 → US1 → US4 (Part A).
- US2 depends on Phase 2 and on T014 (plan lookup in the period use case); US3 depends on T002
  only and can run beside US2, except T026 and T021 both edit `domain/watchlist_period.py`, so
  sequence them.
- Phase 7 runs per pull request.
- After each merge, applying `sql/035` to the local `fn-ignis-db` and reinstalling the wheel is an
  operational step outside this list.

## Parallel opportunities

- T003 and T004; T010, T011 and T012; T017 beside US1 implementation; T020 and T025.
- Part A and the Part B tests (T020, T025) can be written at the same time on separate branches.

## Implementation strategy

1. MVP is Part A: Phases 1 to 4, one pull request. It lets a user record goal, period and cadence,
   defaults the period view, and makes the routine follow the cadence.
2. Part B: Phases 5 and 6 on a branch from merged Part A, one pull request, merged after the owner
   reviews the amendment wording.
3. Each pull request ends with Phase 7.

## Part A execution evidence

- T001: existing branch `claude/goal-period-part-a` contains `ba2e064`; no rebase needed (owner instruction). Baseline: 103 passed, 25 skipped; PostgreSQL DSN absent.
- T002: captured fixed-clock day/week/month use-case responses before source changes; fixture adapter and JSON live in `tests/fixtures/watchlist_period_created_baseline/`.


## Part B execution evidence

- Scope: T020–T029 in `claude/goal-period-part-b`; no commits, MCP signature changes,
  external-store operations, or credentials. T030 belongs to the coordinator and is untouched.
- Workflow source: owner-supplied exact `coding-workflow.md` copy in the coordinator scratchpad;
  Spec Kit `speckit-implement`. Prerequisites resolved with `SPECIFY_FEATURE_DIRECTORY` pointing
  to this feature. Requirements checklist: 16/16 checked; no extension hooks configured.
- T020–T023: pure seen-axis tests and dual-backend storage tests authored; SQLite verified.
  PostgreSQL cases are collected but skipped locally without `IGNIS_TEST_POSTGRES_DSN`.
- T024 is complete within the owner's local scope exception: only the packaged guide and guide
  tests changed. The coordinator must mirror the guide into `.agents/skills/ignis-listen/SKILL.md`;
  `test_repository_skill_mirrors_the_packaged_guide` remains an expected failure until then.
- T025–T026: frozen pre-feature day/week/month JSON is unchanged. Full response equality holds
  after removing only `listening_plan`, topic `seen`, and each created cell's `axis` label.
- T027: proposed Principles I/III wording and Sync Impact Report are in
  `.specify/memory/constitution.md`, proposing 2.3.0. Ratified 2.2.1 remains effective pending
  owner review of the exact wording in the Part B PR.
- T028: changed Python files pass Ruff; repository convention checks pass.
- T029 remains unchecked: local targeted verification is recorded in
  `.handoff/spec018-part-b-verification.md`; PostgreSQL verification belongs to the coordinator.
- Implementation refinement to research R3: seen first sightings use earliest successful channel
  completion across all watchlist runs, rather than reusing the created view's capture-time
  first-sighting map. Tests cover reused observations, overlapping runs and historical channel
  completions across run-wide cutoffs. This preserves both research R2 and created-view parity.
- Clarifications record the conservative cadence-period mismatch behavior; no cadence conversion
  is invented when an explicit view overrides the plan's period kind.
