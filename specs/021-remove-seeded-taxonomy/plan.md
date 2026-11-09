# Implementation Plan: Remove the Seeded Industry Taxonomy

**Branch**: `021-remove-seeded-taxonomy` | **Date**: 2026-11-09 | **Spec**: [spec.md](spec.md)

**Input**: `specs/021-remove-seeded-taxonomy/spec.md`
**Inspected revision**: `cc0b04d6fb4cef307ccf4ffe1ccd80a9791052c9`

## Summary

Keep usable source categories and `unclassified`; remove taxonomy matching, registration,
loading and the vocabulary response key. Retire stored labels with an explicit, projected,
transactional migration on both backends. Preserve the 69 domain lexicon terms and all
historical SQL. The source inspection supports category-independent Market decisions and
frame digests, with an important distinction: some handlers still fetch cluster rows that
contain category. It is an incidental read, not an input to qualification or a verdict.

The owner decisions in the spec are fixed. This plan adds execution details, not a new
product decision. No implementation, test, database access or migration was performed while
preparing these artifacts. Existing documents and `.specify/feature.json` remain unchanged.

## Technical Context

**Language/Version**: Python 3.11+, PostgreSQL SQL; existing typed domain models.
**Primary Dependencies**: Existing FastMCP, psycopg, sqlite3, Jinja2, pytest; no new dependency.
**Storage**: SQLite default and PostgreSQL 16; existing stores and empty installations.
**Testing**: Targeted pytest unit/storage contracts, real PostgreSQL migration/RLS tests,
and the real Compose initialization test; RED before each behavior change.
**Target Platform**: Existing Python MCP/CLI deployments and packaged SQL in wheels/sdists.
**Project Type**: Python library, CLI and MCP service.
**Performance Goals**: No new runtime query or evaluator; remove taxonomy work. Projection
is an explicit linear scan of the selected store, with rows streamed in primary-key order.
**Constraints**: 53 tools, unchanged MCP parameters, no connector/scoring/Market gate changes;
no other cluster field or evidence mutation. One heavy job machine-wide, load average <12.
**Scale/Scope**: 14 former codes, 244 historical taxonomy keywords, two adapters, three stories.
No production store is assumed; actual store contents and environment remain unverified.

### Routing and Spec Kit depth gate

Source: `fnl-coding-router` and its `references/workflows/speckit.md`, then repository
`.agents/skills/speckit-plan/SKILL.md` and `speckit-tasks/SKILL.md` with `.specify/templates/`.
Route: **DEEP / migration**, plan → tasks → later implement. A persisted-data migration
fails the direct-implementation depth gate even if the matching-code deletion is small;
**tasks.md is required**. Owner instructions settle the next activities and gate; no Jev
judgment or credential access is needed for that deterministic choice. Research here is
source inspection; no external evaluator result is claimed. The setup script resolves the
already-correct feature pointer. No extension hooks are configured. Session title control
is not exposed in this host.

## Constitution Check

| Principle | Before research | After design / implementation obligation |
|---|---|---|
| I: explicit work, deterministic collection | Pass: bounded removal | No worker, scheduler, probe or evaluator added |
| II: connector authority | Pass: no live access | Connector categories and platform vocabulary remain intact |
| III: evidence-first, both backends | Conditional on tracing and parity | Trace completed; paired migration and unchanged frame/claim tests still required |
| IV: maintained report builders | Pass | Keep templates; validate `unclassified` in existing rendering/filtering |
| V: minimal, typed, data-driven | Pass | Codes exist only as frozen migration identifiers, never runtime classification vocabulary |
| VI: projection before change | Owner approved reset in spec | Publish exact snapshot projection before apply; match under lock, verify before commit; execution pending |
| VII: no author identity at rest | Pass | Projection exports counts/hashes only, no titles, metadata, author material or credentials |

Design satisfies these gates without a constitutional exception. A planning pass is not
migration acceptance. Runtime execution remains gated on observed RED/GREEN, projection,
rehearsal, independent review and applicable owner authorization.

## Project Structure

### Documentation (this feature)

```text
specs/021-remove-seeded-taxonomy/
├── spec.md                         # Existing; unchanged
├── plan.md
├── research.md
├── data-model.md
├── contracts/
│   ├── vocabulary.md
│   └── taxonomy-retirement.md
├── quickstart.md
└── tasks.md
```

### Source Code (planned changes, not made in this session)

```text
src/ignis/
├── application/ports/repository_port.py
├── infrastructure/clustering/semantic_clusterer.py
├── infrastructure/config/vocabulary_loader.py
├── infrastructure/migration/taxonomy_retirement.py  # New bounded projection/apply support
├── infrastructure/persistence/{sqlite,postgres}_repository.py
├── interfaces/mcp/server.py
└── resources.py
scripts/retire_industry_taxonomy.py                   # New explicit operator command
sql/039_remove_seeded_taxonomy.sql                   # New; recheck number before implementation
tests/unit/                                        # Classification, projection, caller, MCP
tests/integration/                                 # PostgreSQL and evidence parity
```

**Structure Decision**: Use the existing migration directory and a single operator script;
no general SQLite migration framework. The operator script runs from a matching checkout;
it does not widen the wheel/sdist member allowlist. `caller_storage.py` is a traced consumer, not a
permission to alter root ownership, configuration loading or ready-store authorization.

## Phase 0: Research result

See [research.md](research.md) for references and alternatives. In particular:

- `server.py:1635`, `:2614`, `:2751` converge on the persisted Market analysis contract.
- `get_mission_analysis.py:192` builds qualification/sufficiency from a snapshot;
  `current_evidence_frame.py:57` includes observation metadata and `cluster_id`, not
  `TopicCluster.category`; `research_workspace.py:1399`–`:1459` hashes those records.
- Attention handoff uses membership, qualification and independent sources, not category
  (`strategic_reasoner.py:313`). Dashboard and graph expose category for display/filtering.
- SQLite bootstrap recreates and re-seeds taxonomy today. `open_existing_ready` forbids
  upgrades and compares the complete core schema digest. Both paths need deliberate coverage.

## Phase 1: Design

### Classification and API

Preserve `_is_usable_category`, trimming/lowercasing and source-category majority selection.
Preserve current tie behavior; do not invent a new ordering contract. Without usable source
categories return `unclassified`. Delete the taxonomy matcher, thresholds, registration,
state, and exclusively used helpers/imports after checking references. Do not change token
matching, cluster IDs/membership, scoring, lexicon synonyms or language detection.

Remove `get_industry_taxonomies` from the port and both adapters only in the same increment
as removal of its synchronizer and MCP callers. The public tool remains
`list_domain_lexicons(domain: Optional[str] = None)`; only its success payload taxonomy key
and taxonomy-related description change. Preserve error shape and all other success keys.

### Projection, publication and exact-snapshot gate

The new script has explicit `project`, `apply`, and `verify` operations, described in
[contracts/taxonomy-retirement.md](contracts/taxonomy-retirement.md). It uses raw backend
connections, never repository initialization or caller configuration/credential loading.
Projection reads a transaction-consistent snapshot, computes all 14 counts including zero,
unchanged-field/evidence invariants and deterministic SHA-256 digests, then emits JSON to
stdout. The operator publishes that output locally under
`reports/migrations/021/<run-id>/projection.json` before apply; no database writes, automatic
file writes or network publication occur in `project`. The exact artifact is passed to apply.

Quiesce writers before projection; keep them stopped through verification. Apply takes a
write-blocking lock, re-reads and recomputes the baseline, and refuses any drift before its
first data mutation. Verification hashes actual post-state, not a second prediction.
Do not use a prior rehearsal's digest for another store. Keep a restorable snapshot outside
this code change. `t020_cutover.py` supplies the standstill/digest precedent;
`post_migration_verification.py` supplies independent post-state verification and both backend
readers. Reuse patterns, not their source/observation backfill or unrelated production steps.

### PostgreSQL retirement

Append `039_remove_seeded_taxonomy.sql` after verified current tip `038`. Use a single atomic
DO statement (no internal COMMIT), safe both in the full-chain runner and inside the operator
script's transaction. Lock/recheck table existence and update `topic_clusters.category` by
exact membership in the frozen codes; then `DROP TABLE ...` without CASCADE. Unknown dependent
objects must fail and roll back, not disappear. No application upsert or timestamp refresh.

For a populated cluster store, direct SQL without the prepared projection context fails
closed. The operator script acquires locks and checks the full baseline before setting a
transaction-local projection receipt and executing 039; it verifies actual post-state before
committing. The receipt is a backstop, not independent proof or authority. On an empty fresh
install, the SQL emits a deterministic zero-cluster projection notice before DDL; the init
log is its publication. This permits the unchanged 001–038 chain to run before the final drop.
A populated installation must use the explicit script even if zero labels match.

When the table is absent, return already-retired and perform no category UPDATE. This is the
completion marker: it preserves new source categories such as `beauty` on retries. An absent
table cannot establish the history of existing labels; report that limit, do not guess.

### SQLite retirement and startup

Remove taxonomy CREATE TABLE and the `tax_path` re-seeding block from new-store bootstrap;
keep lexicon-only extraction from historical 003 and all other vocabulary seeds. On an
existing taxonomy-bearing database, ordinary startup must refuse with an actionable explicit
migration message **before** `_create_tables_and_seed` or any schema/seed mutation. Do not
silently call apply. Fresh creation needs no persisted-label migration.

The operator script opens the existing file with `mode=rw`, acquires `BEGIN IMMEDIATE`, checks
the baseline, performs UPDATE and DROP with individual `execute` calls, verifies, then commits.
Rollback on every failure; do not use `executescript`, which can commit an existing transaction.
No `PRAGMA user_version` or broad schema rebuild is needed. A missing table is a strict no-op,
including when a new cluster now carries a former code. Existing-ready callers continue to
validate and refuse old schema, never acquire migration powers. After explicit retirement,
the supported fresh schema and migrated core digest must match; progress tables are preserved.

### Historical SQL and installation paths

Leave every existing migration, including 003, 006, 010, 021 and 022, byte-for-byte unchanged.
SC-001 explicitly permits keyword lists in those historical files. PostgreSQL fresh install
runs the complete ordered chain through 039 before exposing readiness. SQLite never executes
003 as a whole and must no longer parse its taxonomy arrays. Package the full SQL chain in
wheel/sdist; add 039 to the migration inventory, not SQLite seed replay.

Historical tests of 006/021/022 belong at their historical prefix. Final-chain tests expect
no taxonomy table/default/policy and retain every other security assertion. Reapplying 006
alone after retirement with Supabase roles is not a supported new upgrade sequence: its
unchanged policy creation targets the removed table. Full-chain replay on a populated retired
store is also not the migration retry contract: it recreates the legacy marker. Retry 039 or
the explicit apply command; never replay old seeds as an upgrade/startup mechanism.

## Validation and delivery order

1. Record the baseline and exact future targeted commands; do not run them during planning.
2. Add baseline evidence-parity tests and projection tests; observe genuine assertion RED
   for missing behavior, not missing import/command errors, then implement projection.
3. US1: observe category, synchronizer and fresh SQLite failures before deleting the fallback.
   Cover source majority, invalid source values, no source, and retained lexicons.
4. US2: observe projected reset/rollback/retry/stale-baseline failures on SQLite and real
   PostgreSQL; implement explicit retirement and full fresh-chain support. Test source-code
   collisions before migration and new source-coded clusters after migration independently.
5. US3: observe response-key failure, remove the key/readers together, then update guidance.
   Retain tests for all other response keys and exactly 53 tools.
6. Run only changed seams and traced consumer tests; run repository conventions as required
   during implementation. Real PostgreSQL, Supabase-role posture and Compose proof cannot be
   replaced by SQL text assertions. Obtain independent code/security reviews before merge.

US1 is the first reviewable behavior slice, not a separately deployable release: startup
retirement, API consumer removal and US2 must be integrated before enabling the new build.
No version bump, commit, push, merge, migration or release is authorized by this planning run.

## Open

- **Runtime proof pending (implementer/coordinator)**: no tests or database operations were
  authorized in this session. Actual counts/digests, rollback, packaged-install behavior,
  PostgreSQL privileges and schema parity need the targeted implementation/rehearsal evidence.
- **Deployment inventory pending (operator)**: enumerate the explicitly authorized local and
  PostgreSQL stores before apply; the spec's development-only assumption was not verified by
  connecting to any store. No production baseline is claimed.
- **Literal assumption qualification**: handlers fetch cluster rows that contain category;
  no category dependency was found in Market decisions or evidence/frame hashes. Keep the
  paired category-only mutation tests to make this separation executable.
- No owner decision is reopened and no settled outcome was found impossible. The historical
  SQL exception and saved-report exception are required interpretations already in the spec.

## Complexity Tracking

No constitutional violation is proposed. The projection module and one explicit operator
command exist because the two backends must share the reset predicate and verification rules;
adding a migration framework, provenance backfill or replacement classifier is out of scope.
