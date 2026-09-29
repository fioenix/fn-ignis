# Tasks: YouTube Quota Management

**Input**: Design documents from `/specs/010-youtube-quota-management/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/

**Tests**: This feature follows mandatory TDD. Each behavior test must be observed failing before its production change.

**Organization**: Tasks are grouped by user story and kept as small, independently verifiable actions.

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Lock the provider model and additive schema before connector behavior changes.

- [X] T001 Add failing migration inventory and backend schema assertions for migration 024 in tests/unit/test_sql_packaging.py
- [X] T002 Add `youtube_quota_buckets` with constraints and RLS in sql/024_youtube_quota_ledger.sql and mirror it in src/ignis/infrastructure/persistence/sqlite_repository.py
- [X] T003 Add failing configuration contract tests for the three quota limits in tests/unit/test_env_example_matches_settings.py
- [X] T004 Add quota limit settings and documented defaults in src/ignis/config.py and env.example

**Checkpoint**: Migration 024 and operator defaults are expressed by tests and schema.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Define the typed policy and storage contract shared by all stories.

- [X] T005 Add failing policy, Pacific-Time rollover, and typed refusal tests in tests/unit/test_youtube_quota.py
- [X] T006 Define quota bucket, policy, snapshot, and clock values in src/ignis/domain/youtube_quota.py
- [X] T007 Extend ConnectorQuotaExceededException with secret-free structured quota details in src/ignis/domain/exceptions.py
- [X] T008 Add atomic reserve, exhaust, and snapshot methods to src/ignis/application/ports/repository_port.py
- [X] T009 Implement the quota manager admission policy in src/ignis/application/youtube_quota.py

**Checkpoint**: Domain policy is deterministic and does not depend on HTTP or process-local state.

---

## Phase 3: User Story 1 - Prevent Concurrent Quota Overspend (Priority: P1) MVP

**Goal**: All fn-ignis processes sharing a database reserve quota atomically before an uncached YouTube call.

**Independent Test**: More concurrent attempts than remaining capacity never admit more than the remaining quota; cache hits make no reservation; provider exhaustion blocks same-day retries.

### Tests for User Story 1

- [X] T010 [US1] Add failing SQLite concurrency, no-refund, exhaustion, and fresh-day repository tests in tests/unit/test_youtube_quota.py
- [X] T011 [P] [US1] Add failing PostgreSQL atomic-upsert contract tests in tests/unit/test_postgres_repository.py
- [X] T012 [P] [US1] Add failing connector admission tests for feed, search, metrics, cache hits, and upstream exhaustion in tests/unit/test_youtube_plugin.py

### Implementation for User Story 1

- [X] T013 [US1] Implement transactional SQLite quota operations in src/ignis/infrastructure/persistence/sqlite_repository.py
- [X] T014 [US1] Implement atomic PostgreSQL quota operations in src/ignis/infrastructure/persistence/postgres_repository.py
- [X] T015 [US1] Reserve and exhaust the correct quota bucket around every YouTube HTTP call in src/ignis/infrastructure/connectors/youtube/youtube_plugin.py
- [X] T016 [US1] Inject one repository-backed quota manager into YouTube plugins in src/ignis/interfaces/cli/scheduler.py and src/ignis/interfaces/mcp/server.py

**Checkpoint**: User Story 1 passes independently with no live API key or provider call.

---

## Phase 4: User Story 2 - Protect On-Demand Research Capacity (Priority: P2)

**Goal**: Scheduled searches stop at 70 while requested work can use the reserved 30 and borrow unused total capacity.

**Independent Test**: The 71st scheduled call is rejected, requested calls remain available through 100 total, and scheduled/requested identity reaches YouTube through every registry path.

### Tests for User Story 2

- [X] T017 [US2] Add failing 70/30 allocation and requested-borrowing tests in tests/unit/test_youtube_quota.py
- [X] T018 [P] [US2] Add failing trigger propagation tests for fetch, mission, and autonomous discovery paths in tests/unit/test_registry.py and tests/unit/test_autonomous_discovery.py

### Implementation for User Story 2

- [X] T019 [US2] Enforce scheduled and total search limits in src/ignis/application/youtube_quota.py and both persistence adapters
- [X] T020 [US2] Propagate IngressTrigger through search orchestration in src/ignis/infrastructure/connectors/registry.py and src/ignis/application/use_cases/autonomous_discovery.py
- [X] T021 [US2] Mark scheduler discovery as scheduled while keeping MCP discovery requested in src/ignis/interfaces/cli/scheduler.py and src/ignis/interfaces/mcp/server.py

**Checkpoint**: User Story 2 proves the capacity split without changing scheduler cadence.

---

## Phase 5: User Story 3 - Understand Quota State and Reset (Priority: P3)

**Goal**: Existing diagnostics explain the bucket, usage, limit, exhaustion state, and reset without exposing the key.

**Independent Test**: A controlled exhausted ledger appears in one connector health result with the contract fields and no credential material.

### Tests for User Story 3

- [X] T022 [US3] Add failing quota snapshot and secret-free diagnostic contract tests in tests/unit/test_youtube_quota.py and tests/unit/test_mcp_server.py

### Implementation for User Story 3

- [X] T023 [US3] Expose quota snapshots from YouTubeDataPlugin in src/ignis/infrastructure/connectors/youtube/youtube_plugin.py
- [X] T024 [US3] Add the quota object to verify_connectors_health results in src/ignis/interfaces/mcp/server.py

**Checkpoint**: All three stories are independently testable and integrated.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Remove the obsolete pre-June-2026 quota model and close public migration/documentation gates.

- [X] T025 Update stale quota cost calculations and tests in src/ignis/application/use_cases/ingest_trends.py and tests/unit/test_corpus_correctness.py without changing scheduler cadence
- [X] T026 Update migration 024 references and quota behavior in README.md, README.vi.md, docs/USER_GUIDE.md, docs/USER_GUIDE.vi.md, and server.json
- [X] T027 Update newest-migration and RLS convention assertions in tests/unit/test_sql_packaging.py and tests/unit/test_repo_conventions.py
- [X] T028 Run focused red/green suites from specs/010-youtube-quota-management/quickstart.md and fix only feature regressions
- [X] T029 Run `env -u YOUTUBE_API_KEY .venv/bin/pytest tests/unit/ -q` and record the exact result
- [X] T030 Run `git diff --check`, inspect `git status --short`, and verify no secret or unrelated owner change entered the branch

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup**: Starts immediately.
- **Foundational**: Depends on the schema/config contracts from Setup.
- **US1**: Depends on Foundational and is the MVP.
- **US2**: Depends on US1's atomic storage boundary.
- **US3**: Depends on US1 snapshots; it can proceed after US1 while US2 is implemented.
- **Polish**: Depends on all selected stories.

### User Story Dependencies

- **US1**: No story dependency after Foundational.
- **US2**: Uses US1's reservation primitive but is independently verified by allocation tests.
- **US3**: Reads US1's snapshot contract and does not depend on US2 behavior.

### Within Each User Story

- Write one behavior test, run it, and confirm the expected failure before production code.
- Implement the minimum production change for that failure.
- Run the focused test green before moving to the next behavior.
- Run the full unit suite before claiming completion.

### Parallel Opportunities

- T011 and T012 affect different files after T010 defines the shared semantics.
- T018 can be authored alongside T017 because it tests orchestration rather than policy math.
- US3 test authoring can begin after US1 snapshots exist while US2 trigger work continues.

---

## Parallel Example: User Story 1

```text
Task: Add PostgreSQL atomic-upsert contract tests in tests/unit/test_postgres_repository.py
Task: Add connector admission tests in tests/unit/test_youtube_plugin.py
```

---

## Implementation Strategy

### MVP First

1. Complete Setup and Foundational.
2. Complete US1 and prove cross-process atomic admission.
3. Validate US1 before adding allocation policy or diagnostics.

### Incremental Delivery

1. US1 prevents overspend.
2. US2 protects interactive capacity.
3. US3 makes refusals operable.
4. Polish synchronizes public migration surfaces and removes the obsolete quota model.

## Notes

- Do not use the live development key in tests.
- Do not add a new MCP tool or change the scheduler's default cadence.
- Do not refund admitted reservations.
- No task authorizes commit, push, migration, deployment, or release.
