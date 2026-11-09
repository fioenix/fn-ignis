# Operator Contract: Taxonomy Retirement

Planned interface, not an existing executable. Implementation owns
`scripts/retire_industry_taxonomy.py` and
`src/ignis/infrastructure/migration/taxonomy_retirement.py`.

## Operations

```text
retire_industry_taxonomy.py project --sqlite PATH
retire_industry_taxonomy.py project --postgres-service NAME
retire_industry_taxonomy.py apply --sqlite PATH --baseline FILE
retire_industry_taxonomy.py apply --postgres-service NAME --baseline FILE
retire_industry_taxonomy.py verify --sqlite PATH --baseline FILE
retire_industry_taxonomy.py verify --postgres-service NAME --baseline FILE
```

Select exactly one backend. PostgreSQL uses an operator-provisioned libpq service/approved
credential injection, not command-line credentials, `.env` discovery or automatic configuration
loading. Never echo connection details. SQLite `project`/`verify` require an existing file via
URI `mode=ro` and `query_only`; PostgreSQL uses a READ ONLY, REPEATABLE READ transaction.
No schema initialization, migration, seed, key lookup or application startup occurs on reads.
Unknown schema/unsupported serialization is an error, not an empty successful projection.

`project` emits the receipt from [../data-model.md](../data-model.md) to stdout and never writes
the database or output files itself. An operator captures and publishes it as
`reports/migrations/021/<run-id>/projection.json`, in the authorized store's local report area.
The file must exist, be readable and be reviewed before `apply`; no remote publication is
implied. Emit only counts, hashes, invariant results and fixed limitations, not row bodies,
cluster IDs, titles, raw evidence, personal data or secret-bearing errors.

`apply` requires that exact baseline. It rejects backend/target/predicate/format mismatch,
failed baseline invariants or fresh content/schema drift under the write lock. Reject an
unpublished/missing baseline before mutations. On SQLite use `mode=rw`, `BEGIN IMMEDIATE`,
individual statements and rollback; on PostgreSQL use one transaction and lock cluster and
legacy taxonomy writes plus the protected evidence tables needed to establish standstill.
Acquire locks in a fixed order, with a bounded timeout, and recheck table presence after waiting.
Do not hold a stale snapshot before acquiring the locks. Every apply failure rolls back.

The first apply changes exactly pending category rows and drops the table; actual post-state
must equal the expected cluster digest, noncategory/evidence invariants and expected schema
before commit. Report actual changed count, post digests, invariant results and commit outcome.
A failed commit is not success. A retry with the original baseline and absent table succeeds
with zero writes only if the original expected post-state still matches; after normal new data
arrives, require a fresh already-retired projection. New source categories are never reset on
that retry. `verify` independently reads stored rows and compares them with the original
expected post-state; a second project call is not equivalent verification.

Exit codes: `0` applied/verified or validated no-op; `1` drift/invariant/refusal; `2` cannot run
or invalid input. Emit a stable reason code and sanitized explanation; no stack trace or DSN.

## PostgreSQL numbered-file contract

`sql/039_remove_seeded_taxonomy.sql` holds the same 14 codes; no live lookup of taxonomy rows.
A single DO statement owns conditional UPDATE and DROP, with no internal commit, no CASCADE,
no helper persisted function and no new grants. The external apply transaction also owns the
baseline comparison and post-state verification.

If taxonomy is absent, do nothing. If it is present and clusters are populated, require a
transaction-local `ignis.taxonomy_projection_digest` receipt set by the script **after** locked
baseline validation. Direct SQL without it refuses. The setting is not an authorization token
and cannot replace the runbook. Fail-closed runtime guards are backstops under Constitution VI.

If the cluster store is empty, publish a JSON NOTICE containing all 14 zero counts, zero target
count, the category-only/no-evidence-change invariants and a deterministic empty-target SHA-256
before the drop. The fresh-init runner retains that notice as the local publication. This
zero-cluster path must be covered on actual PostgreSQL, with and without Supabase roles.
It never licenses a populated upgrade without a baseline.

The whole historical chain may create/seed taxonomy before 039; the **ready** fresh store has
neither table nor rows. No startup or later seed replay runs 003/010 after 039. Upgrade existing
stores by the explicit command/new migration, not by replaying the entire historical directory.

## Required negative controls

- Same counts, different target ID/category: baseline comparison refuses before writes.
- Changed noncategory timestamp/score, observation, claim binding or manifest: refuse drift.
- Failure after UPDATE but before DROP: transaction rollback restores labels and table.
- Failure after DROP but before commit: rollback restores labels and table.
- Absent table plus a newly inserted source-labelled `beauty` cluster: zero writes.
- Edited taxonomy rows: frozen 14-code predicate remains unchanged.
- Empty target set with table present: publish zero changes, drop table, preserve all rows.
- Historical source category equal to a former code: reset and disclose indistinguishability.
- Repeated read-only projections: identical content digests and no database/schema changes.
- One backend unavailable: report unavailable; do not substitute a mock or the other backend.
