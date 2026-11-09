# Tasks: Remove the Seeded Industry Taxonomy

**Input**: `specs/021-remove-seeded-taxonomy/`
**Prerequisites**: `spec.md`, `plan.md`, `research.md`, `data-model.md`, `contracts/`, `quickstart.md`
**Route**: DEEP / migration; the Spec Kit depth gate requires this task list.
**Status**: Implementation in progress; local evidence in `.handoff/021-taxonomy-verification.md`. Real PostgreSQL/Compose proof remains open.

## Format and execution rules

`- [ ] Tnnn [P?] [USn?] Description with exact paths`.
`[P]` permits independent file work only after the phase prerequisite; it never permits
concurrent heavy test jobs. Run PostgreSQL/Compose/build/caller subprocess jobs serially under
the canonical heavy-job lock, with one-minute load average below 12.

Tests are mandatory because the owner explicitly requested test-first order. For each behavior
change, record an assertion failing for the intended reason before the implementation task,
then record GREEN. Missing symbols/files, missing credentials and skipped tests are not RED.
A new module/script may get a minimal callable scaffold returning a no-op so its assertions can
fail behaviorally; do not implement the target behavior before recording RED. Existing parity
assertions may already pass and must be reported as such. Keep each RED/GREEN record, command,
revision and limitation in `.handoff/021-taxonomy-verification.md` during implementation.

## Phase 1: Setup

- [X] T001 Confirm branch/revision, scoped rules, unchanged owner decisions and current SQL tip against `specs/021-remove-seeded-taxonomy/plan.md`; record authorized stores, execution limits and the targeted command set in `.handoff/021-taxonomy-verification.md`. Recheck 039 is free before creating it; do not change branches or inspect credentials.
- [X] T002 Inventory the actual call sites and historical/latest-state assertions from `specs/021-remove-seeded-taxonomy/research.md`; record the removal checklist, exact pre-change hashes of `sql/001` through `sql/038` and the 69 retained domain-term tuples in `.handoff/021-taxonomy-verification.md`, without running a database or build merely for inventory.

## Phase 2: Foundational evidence and projection

**Goal**: Define the exact immutable baseline and create a usable read-only projection before
any persisted-data mutation is implemented. All stories depend on this phase.

- [X] T003 Add parity tests in `tests/unit/test_taxonomy_evidence_parity.py` and `tests/integration/test_decision_grade_evidence.py`: vary only stored cluster category and compare Market discovery, Market/Attention qualification analysis, generated mission content, frame digests, claims and handoff IDs; preserve signal metadata and memberships. Add an observation/claim-content negative control to show the comparison detects relevant changes. Record the existing behavior result, not invented RED.
- [X] T004 Add projection behavior tests in `tests/unit/test_taxonomy_retirement.py`: all 14 counts including zero, exact IDs/old values in hashed target identity, stable reordered reads, same-count substitution detection, all-column/noncategory hashes, protected evidence digests, collision warning and absent-table no-op. Observe assertion RED against a minimal no-op projection before T006.
- [X] T005 Add CLI/read-boundary tests in `tests/unit/test_taxonomy_retirement.py`: raw read-only SQLite connection, no repository initialization or credential/config discovery, stdout-only sanitized receipt, correct backend selection, malformed/unsupported inputs and stable exit reasons. Observe assertion RED before T007; use synthetic files/services only.
- [X] T006 Implement frozen code identifiers, backend snapshot readers and versioned deterministic projection/actual-post-state comparison in `src/ignis/infrastructure/migration/taxonomy_retirement.py` per `data-model.md`; protect all specified evidence sets and lexicons, never read credential/key tables. Turn T004 GREEN without copying a keyword corpus.
- [X] T007 Implement `project` and read-only `verify` in `scripts/retire_industry_taxonomy.py` using T006 and `contracts/taxonomy-retirement.md`; no implicit output-file write, seed, caller configuration or `.env` load. Turn T005 GREEN and demonstrate repeated projection equality without database/schema mutation on a disposable fixture.

**Checkpoint**: Projection is executable and independently verified, but no migration is accepted.

## Phase 3: User Story 1 — Clusters carry only labels with a real origin (P1)

**Goal**: Source categories survive; keyword guesses disappear.
**Independent test**: Through the actual vocabulary synchronization/clustering path, compare
former-keyword signals with/without usable source categories and inspect a fresh SQLite store.

### Tests before changes

- [ ] T008 [P] [US1] Replace inference expectations in `tests/unit/test_bug09_category_classification.py` and `tests/unit/test_taxonomy_coverage.py` with no-source/invalid-source → `unclassified` through the production synchronization path, using isolated synthetic legacy taxonomy rows only to expose the old fallback; observe wrong-category assertion RED. Retain usable-source majority, normalization, short/numeric rejection and valid `beauty` source coverage without depending on the removed registration API after GREEN.
- [ ] T009 [P] [US1] Add a forbidden-taxonomy-read spy and unchanged retained-domain/platform/language registrations in `tests/unit/test_vocabulary_loader.py`; assert fresh and repeated SQLite bootstrap never creates taxonomy in `tests/unit/test_taxonomy_retirement.py`. Observe query/table-presence RED before T011–T012; compare all 69 retained tuples, not just a nonzero lexicon count.

### Implementation

- [ ] T010 [US1] Remove `_Taxonomy`, `_taxonomies`, `register_taxonomies`, taxonomy-only accent helpers/imports and `MIN_CATEGORY_KEYWORD_HITS`/`MIN_CATEGORY_SIGNAL_SHARE` from `src/ignis/infrastructure/clustering/semantic_clusterer.py`; retain `_is_usable_category`, majority handling, tokenization and `unclassified` fallback. Turn T008 GREEN.
- [ ] T011 [US1] Remove taxonomy reads/registration from `src/ignis/infrastructure/config/vocabulary_loader.py`; preserve lexicon registration, quality/reasoner terms, stopwords, ambiguous unigrams and platform/language vocabulary. Turn the no-read assertions in T009 GREEN.
- [ ] T012 [US1] Remove taxonomy DDL and `tax_path` refresh from `src/ignis/infrastructure/persistence/sqlite_repository.py`, preserving lexicon-only 003/004 extraction and all other seeds. Update the taxonomy wording only in `src/ignis/resources.py`; keep SQL resolution and packaging behavior. Turn fresh/repeated bootstrap assertions GREEN. This intermediate build must not open legacy stores before US2's startup gate is integrated.
- [ ] T013 [US1] Run the targeted classification/vocabulary tests named in `specs/021-remove-seeded-taxonomy/quickstart.md`, including the existing grouping regression in `tests/unit/test_bug04_semantic_clustering.py` when traced helpers are affected; record source-category parity and unchanged memberships in `.handoff/021-taxonomy-verification.md`. Fresh PostgreSQL acceptance joins US2's full-chain test.

**Checkpoint**: First reviewable behavioral MVP. Not independently deployable to existing stores.

## Phase 4: User Story 2 — Earlier taxonomy labels are removed (P2)

**Goal**: Exact projected resets and table retirement, atomically and safely repeatable on both
backends.
**Independent test**: Publish projection on a synthetic/rehearsal legacy store, apply, compare
actual rows/digests, inject rollback failures, and retry before/after new source-coded data.

### Tests before changes

- [ ] T014 [P] [US2] Add SQLite apply tests in `tests/unit/test_taxonomy_retirement.py` for all 14 codes, outside-code/null categories, historical source-code collision, table absent/empty target, unchanged timestamps and every other field, rollback after UPDATE/after DROP, stale same-count baseline and retry preserving a new source-coded cluster. Observe intended reset/transaction assertions RED against a no-op apply before T019.
- [ ] T015 [P] [US2] Add startup refusal and post-cutover ready-store parity tests in `tests/unit/test_sqlite_existing_ready.py`; update absent-taxonomy protected-set expectations in `tests/unit/test_caller_analysis_composition.py` and `tests/unit/test_caller_youtube_pilot_cli.py`. Prove old store refusal precedes every schema/seed write and ready analysis never migrates. Observe assertion RED before T020; preserve all remaining denied-write assertions.
- [ ] T016 [P] [US2] Add real PostgreSQL scenarios in `tests/integration/test_taxonomy_retirement.py` matching T014, plus locked baseline recheck, bounded lock failure, direct populated SQL refusal without receipt, zero-cluster publication NOTICE, edited taxonomy rows, unexpected dependent-object rollback and owner-role execution. Observe behavioral RED on a pre-039 database/no-op apply before T018–T019. **Requires real PostgreSQL; mocks are not acceptance.**
- [ ] T017 [P] [US2] Update final-state assertions in `tests/integration/test_compose_init.py`, `tests/integration/test_postgres_migration_contract.py` and `tests/integration/test_postgres_rls_coverage.py`: absent taxonomy/table/default/policy, exact remaining identities, 56 tables/15 UUID defaults and only the remaining lexicon read policy. Retain 006/021/022 historical-prefix security/replay tests; add real whole-chain end-state/retry coverage without promising standalone 006 on a retired Supabase schema. Also add the 039 packaged-chain/no-SQLite-seed expectation in `tests/unit/test_sql_packaging.py` and observe its inventory RED before T018. Observe final-state RED before T018. **Requires real PostgreSQL and, for the init path, Compose.**

### Implementation

- [ ] T018 [US2] Add `sql/039_remove_seeded_taxonomy.sql` as one atomic conditional DO statement, with frozen codes, populated-store projection receipt guard, fresh-empty projection NOTICE, absent-table no-op, category-only UPDATE and DROP without CASCADE; no internal COMMIT, helper grants or edits to historical SQL. Turn SQL retirement/fresh-chain cases from T016–T017 GREEN on actual PostgreSQL.
- [ ] T019 [US2] Implement explicit transactional `apply` in `src/ignis/infrastructure/migration/taxonomy_retirement.py` and `scripts/retire_industry_taxonomy.py`: baseline identity/drift validation under lock, individual SQLite statements under `BEGIN IMMEDIATE`, PostgreSQL 039 inside the owning transaction, actual post-state verification before commit and rollback on every failure. Turn T014/T016 GREEN; no repository bootstrap or secret discovery.
- [ ] T020 [US2] Add early legacy-taxonomy refusal before ordinary bootstrap in `src/ignis/infrastructure/persistence/sqlite_repository.py`; keep `open_existing_ready` validation-only and prove fresh/migrated core schema parity. Trace `src/ignis/infrastructure/caller_storage.py` and existing caller composition without broadening caller roots/config/authorization. Turn T015 GREEN.
- [ ] T021 [US2] Complete the packaging contract prepared RED in T017: update the expected latest migration names in `tests/unit/test_sql_packaging.py` and verify 039 is in the continuous wheel/sdist SQL chain but not SQLite seed replay. Verify historical SQL hashes remain identical and packaged-resource startup never recreates taxonomy. Do not widen `pyproject.toml` package members just to ship the operator script.
- [ ] T022 [US2] Run T014–T017 and affected caller/packaging tests serially per `specs/021-remove-seeded-taxonomy/quickstart.md`; independently exercise project → publish → apply → verify → retry on both authorized rehearsal backends. Store local receipts in `reports/migrations/021/<run-id>/` and evidence links in `.handoff/021-taxonomy-verification.md`; if a backend is unavailable, keep this task open.

**Checkpoint**: Both backend migrations and fresh installs have observed evidence. No live apply
is implied by fixture acceptance; the chosen store still needs its own exact baseline.

## Phase 5: User Story 3 — The product no longer exposes a taxonomy (P3)

**Goal**: Vocabulary response exposes only lexicons and guidance no longer instructs contributors
to extend a taxonomy.
**Independent test**: Exact MCP key/schema/tool inventory checks and scoped guidance inspection.

### Tests before changes

- [ ] T023 [P] [US3] Change `tests/unit/test_market_lexicons.py` to assert the exact success/error payload contracts, domain-filter semantics, no taxonomy read and unchanged 53-tool inventory/signatures; observe extra-key/read RED before T025. Reuse the existing MCP registry discovery instead of hardcoding an artificial tool list.
- [ ] T024 [P] [US3] Extend `tests/unit/test_graph_artifact.py` and `tests/unit/test_taxonomy_evidence_parity.py` to render `unclassified` through dashboard/graph/card/mission builders, inspect dynamic graph filter data, and compare Market/Attention outputs before/after stored-category reset. Existing rendering may already pass; record parity, not RED. Any discovered rendering defect needs its own assertion RED before changing `src/ignis/infrastructure/templates/html/`.

### Implementation

- [ ] T025 [US3] Remove only the taxonomy response field/read and description promise from `src/ignis/interfaces/mcp/server.py`; remove `get_industry_taxonomies` from `src/ignis/application/ports/repository_port.py` and both `src/ignis/infrastructure/persistence/postgres_repository.py` and `sqlite_repository.py`. Reconcile taxonomy-only test doubles in `tests/integration/test_decision_grade_evidence.py`. Turn T023 GREEN; keep names, parameters, other keys and 53 tools.
- [ ] T026 [US3] Update the Data-Driven Vocabulary Protocol in `AGENTS.md`, schema facts in `docs/PROJECT_REVIEW_CONTEXT.md`, and the schema statement in `BACKLOG.md` to remove active taxonomy guidance while preserving lexicon/data-driven/diacritic/platform-language rules and historical context. Preserve original language; apply Vietnamizer/manual reader pass to changed human-facing Vietnamese prose. Do not edit the settled `specs/021-remove-seeded-taxonomy/spec.md`.
- [ ] T027 [US3] Run the targeted MCP/rendering/evidence parity checks and inspect shipped runtime references against `specs/021-remove-seeded-taxonomy/contracts/vocabulary.md`; record that historical SQL keyword lists and migration-only codes are the only intentional remnants, with no live taxonomy getter/seed/registration path, in `.handoff/021-taxonomy-verification.md`.

**Checkpoint**: All three stories meet their independent assertions; integration remains gated
on the final targeted evidence and review.

## Phase 6: Polish and cross-cutting acceptance

- [ ] T028 Run `.venv/bin/pytest tests/unit/test_repo_conventions.py`, scoped lint/diff checks and only the affected consumer set from `specs/021-remove-seeded-taxonomy/quickstart.md`; record fresh results and skips in `.handoff/021-taxonomy-verification.md`. Run no full suite without the owner's request; do not repeat unchanged passing heavy jobs.
- [ ] T029 Re-evaluate all FR-001–FR-011 and SC-001–SC-005 against source/test/receipt evidence in `.handoff/021-taxonomy-verification.md`; update `specs/021-remove-seeded-taxonomy/tasks.md` only for observed completed work. Keep missing real PostgreSQL/Compose, rehearsal or data-baseline evidence open. Obtain independent code/security review under the router gates before a later authorized merge; this task grants no commit/push/merge/release authority.

## Dependencies and execution order

```text
T001 → T002 → {T003, T004, T005} → T006 → T007
  → US1 (T008–T013)
  → US2 (T014–T022)
  → US3 (T023–T027)
  → T028 → T029
```

Within phases, each implementation depends on its named RED task. T018 enables the numbered
SQL cases; T019 enables CLI transaction cases. T020 depends on successful explicit retirement;
T017 prepares packaging RED before 039 exists; T021 completes that check after T018. Never
claim a post-change assertion was observed RED retroactively.
US1 fresh PostgreSQL AC remains pending until T017/T018. US2 final caller behavior is integrated
with US3 getter removal before the build is activated. Do not deploy intermediate stories.

### Parallel examples (file work only)

- US1: T008 classification tests and T009 synchronization/fresh-store tests touch different
  files; their executions still follow machine load rules. T010/T011/T012 remain ordered.
- US2: T014, T015, T016 and T017 can be authored independently after US1; no two agents own the
  same file, and PostgreSQL/Compose runs are serialized. T018/T019/T020 integrate sequentially.
- US3: T023 MCP tests and T024 rendering/parity tests can be authored independently. T025
  consumer removal and T026 guidance do not require concurrent execution.

These are decomposition opportunities, not authorization to start agents or concurrent jobs.

## Requirement coverage and implementation strategy

| Requirement | Main tasks |
|---|---|
| FR-001 / SC-002 | T008–T013 |
| FR-002 / SC-001 | T009–T012, T017–T021, T025–T027 |
| FR-003 / SC-004 | T023, T025, T027 |
| FR-004 / SC-003 | T014, T016, T018–T022 |
| FR-005 | T004–T007, T014, T016, T019, T022 |
| FR-006 | T003–T004, T014, T016, T019, T024 |
| FR-007 / SC-005 | T014–T020, T022 |
| FR-008 | T024, T027 |
| FR-009 | T003, T011, T023–T025, T027 |
| FR-010 | T009, T026–T027 |
| FR-011 | T002, T009, T012, T022 |

The MVP is US1's source-only category behavior, reviewed locally. The releasable increment
contains all stories: projection and transactional upgrade are prerequisites for consistent
old/new data, and the tool consumer must stop reading the dropped table. Demonstrate each
story independently, then integrate without broadening scope. No new version, dependency,
classifier, credential path or migration framework is needed.

**Task inventory**: 29 tasks; setup 2, foundational 5, US1 6, US2 9, US3 5, final acceptance 2.
