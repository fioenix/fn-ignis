# Validation Guide: Remove the Seeded Industry Taxonomy

This is a future implementation/rehearsal guide. **No command below was run during planning.**
The new retirement command/test files do not exist yet. Do not treat their design as a pass.

## Prerequisites

- Work on `021-remove-seeded-taxonomy`; verify revision and preserve unrelated work.
- Implement the tasks with observed behavioral RED before each change. Use the existing venv;
  do not install dependencies or read `.env` files as an incidental setup step.
- Use disposable synthetic stores or explicitly authorized rehearsal copies. For PostgreSQL,
  the operator provides a libpq service and test DSN by approved injection; never print it.
- Stop writers for cutover. Keep a restorable backup and establish its target identity without
  copying credentials into reports. A rehearsal receipt is not another store's baseline.
- Heavy jobs run serially through the canonical `heavy_run.py` wrapper and machine-wide
  `/Users/fioenix/.finolabs/vibecode/state/heavy.lock`, only with one-minute load average <12.
  Read the installed wrapper's help before use; do not bypass its lock or start parallel Docker,
  PostgreSQL, Compose, browser or whole-package jobs. No full test suite is requested.

## Targeted behavior proof

Record command, revision, assertion failure, fix and result in
`.handoff/021-taxonomy-verification.md`. Missing imports, absent executables and unavailable
PostgreSQL are setup failures, not behavioral RED. For new code use a minimal callable/no-op
scaffold so assertions demonstrate the missing behavior. Existing unchanged behavior may
already pass; record it as parity, never fabricate a failure.

After implementing each relevant task, run its focused cases, then the affected file set once:

```bash
.venv/bin/pytest tests/unit/test_bug09_category_classification.py tests/unit/test_taxonomy_coverage.py tests/unit/test_vocabulary_loader.py
.venv/bin/pytest tests/unit/test_taxonomy_retirement.py tests/unit/test_sqlite_existing_ready.py tests/unit/test_caller_analysis_composition.py tests/unit/test_caller_youtube_pilot_cli.py
.venv/bin/pytest tests/unit/test_market_lexicons.py tests/unit/test_sql_packaging.py tests/unit/test_graph_artifact.py tests/unit/test_taxonomy_evidence_parity.py
.venv/bin/pytest tests/unit/test_repo_conventions.py
```

Run expensive caller/packaging tests through the same heavy-job wrapper when they spawn
subprocess/build work; split groups to retain serial machine-wide execution. The paths named
above include planned new files. Preserve existing source-category and vocabulary tests.

Expected results: no-source and rejected-source clusters become `unclassified`; usable source
majority stays; fresh SQLite has no taxonomy; all 69 retained domain terms and platform/language
vocabulary still load; MCP success keys differ only by taxonomy removal and tool count is 53;
dashboard/graph display and filter `unclassified`; Market/Attention parity checks hold.

## Real PostgreSQL and full-chain proof

Run the following **separately**, through the heavy-job wrapper, on disposable authorized
PostgreSQL. Use the existing fixtures in `tests/conftest.py` and integration conftest; missing
DSN/roles or skipped tests remain an explicit unverified gate.

```bash
.venv/bin/pytest tests/integration/test_taxonomy_retirement.py
.venv/bin/pytest tests/integration/test_postgres_migration_contract.py
.venv/bin/pytest tests/integration/test_postgres_rls_coverage.py
.venv/bin/pytest tests/integration/test_decision_grade_evidence.py
IGNIS_TEST_COMPOSE_INIT=1 .venv/bin/pytest tests/integration/test_compose_init.py
```

Verify the real ordered 001–039 chain with and without Supabase roles. Final state has no
taxonomy table/policy/default, 56 public tables and 15 UUID defaults for the inspected chain,
with exact object identities checked. Historical-prefix tests retain 006/021/022 guarantees;
standalone 006 replay after final retirement is not the supported upgrade path. Package tests
must cover the SQL chain in the installed layout and fresh SQLite without taxonomy reseeding.

## Rehearsal and explicit cutover

The following commands are the planned interface; `<run-id>` and paths identify one chosen
store. The operator creates the report directory and captures stdout before apply. Substitute
a controlled libpq service for `--sqlite` on PostgreSQL; do not pass a DSN/password on argv.

```bash
python scripts/retire_industry_taxonomy.py project --sqlite /absolute/rehearsal.sqlite3 > reports/migrations/021/<run-id>/projection.json
python scripts/retire_industry_taxonomy.py apply --sqlite /absolute/rehearsal.sqlite3 --baseline reports/migrations/021/<run-id>/projection.json
python scripts/retire_industry_taxonomy.py verify --sqlite /absolute/rehearsal.sqlite3 --baseline reports/migrations/021/<run-id>/projection.json
```

Before apply, review per-code counts, reset total, invariants, snapshot digest and source-code
collision warning. Publish by making the captured local receipt available to the coordinator;
no remote upload is part of this procedure. Apply refuses a missing/stale baseline under lock.
After success, changed count equals the projection; only category differs; taxonomy is absent;
actual cluster/evidence/schema digests equal the expected post-state. Run verify independently.

Re-run immediately with the original baseline: zero writes and unchanged post-state. Then
insert a synthetic new source-labelled `beauty` cluster, publish a fresh already-retired
projection and apply again: still zero writes and `beauty` survives. An already absent table
with old-looking categories is also a no-op, with its provenance limitation disclosed.

For rollback proof, inject failures after UPDATE and after DROP before commit in disposable
fixtures. Both backends must retain the original table and complete cluster rows. Change one
target ID without changing counts to prove stale-baseline rejection; change one score,
timestamp or evidence binding to prove the invariant guard is effective.

Finally reopen the migrated SQLite store through ordinary startup and existing-ready analysis.
The core schema matches a fresh build; progress data and caller scope remain intact. Render
fresh dashboard/graph/mission artifacts through existing builders. Previously saved HTML is
not rewritten. A missing PostgreSQL/Compose pass prevents claiming complete backend delivery.
