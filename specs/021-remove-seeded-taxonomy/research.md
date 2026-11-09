# Research: Remove the Seeded Industry Taxonomy

Inspected 2026-11-09 at `cc0b04d6fb4cef307ccf4ffe1ccd80a9791052c9`.
Evidence is static source inspection, not executed behavior. Paths below are repository-relative;
line references name the inspected revision. No database, test suite or credential was accessed.

## 1. Does the evidence path depend on cluster category?

**Decision:** Preserve all evidence and analytical code. Category-only changes must leave Market
qualification, sufficiency, claims, current-frame digests and Attention handoff unchanged.
**Rationale:** The inspected consumers below use observations, memberships, judgments and claims.
**Alternatives considered:** Removing cluster fetches or redesigning report flows would be an
unrelated refactor. Retain them and prove parity at their public boundaries.

| Surface | Verified path | Category finding |
|---|---|---|
| `discover_market_opportunities` | `src/ignis/interfaces/mcp/server.py:1635`–`:1706`; Market branch at `:1660` invokes `GetMissionAnalysisUseCase` | Fetches clusters before branching, but the Market response is the persisted analysis contract; category does not select claims |
| `get_mission_analysis`, Market | `server.py:2614`–`:2671`; `src/ignis/application/use_cases/get_mission_analysis.py:192`–`:275` | Snapshot → frame → `QualificationContext.build` → `assess_strategic_sufficiency` → current permitted claims; no cluster category input |
| `get_mission_analysis`, qualification/Attention | `server.py:2673`–`:2710`; `src/ignis/infrastructure/harness/strategic_reasoner.py:313`–`:410` | Judgments addressed by observation ID; candidates grouped by cluster ID and qualified by independent sources; topic label is presentation |
| Legacy/Attention reasoner | `strategic_reasoner.py:122`–`:248`, `:841`–`:903` | Cluster count/momentum and signal content matter; category does not. Lexicon bucket `category` is a different field and remains |
| `generate_mission_artifact` | `server.py:2751`–`:2835` | Market analysis contract passed to maintained builder; clusters fetched incidentally. Macro-trend category at `:2810` is source signal metadata, not stored cluster category |
| Snapshot | `src/ignis/infrastructure/persistence/evidence_snapshot.py:23` | Reads mission, manifest, brief, signals, qualifications, outcomes and claims; no cluster object |
| Evidence frame/hash | `src/ignis/application/use_cases/current_evidence_frame.py:57`–`:132`; `src/ignis/domain/research_workspace.py:1268`, `:1399`–`:1459` | Includes observation `cluster_id` and full observation metadata, not `topic_clusters.category`. Source metadata category must therefore remain byte-equivalent |
| Qualification fingerprint | `research_workspace.py:2036`–`:2059` | Immutable mission question / brief framing; not cluster category |
| Old migration digests | `scripts/post_migration_verification.py:277`–`:307`; `src/ignis/infrastructure/migration/legacy_projection.py:302` | Source/observation/mission/cluster-membership digests; membership means cluster ID, not category. They cannot prove category-only mutation by themselves |
| Caller identity/schema hashes | `src/ignis/infrastructure/caller_storage.py:105`; `sqlite_repository.py:682`–`:708` | Caller file identity and core schema hashes, not evidence hashes. Removing a table intentionally changes core schema digest |
| Dashboard/filter | `src/ignis/infrastructure/templates/html/trend_dashboard.html:96`; `html_builder.py:165`; `html/trend_graph.html:621`–`:660` | Category displayed and dynamically enumerated as a filter; `unclassified` needs no new category registry |
| Mission/card templates | `html/mission_report.html:193`, `:328`–`:332`, `:659`; `html/trend_card.html:61`–`:69` | Frame digest, handoff/topic labels and source macro-trend category; card does not print category |

The spec assumption is **confirmed as decision/digest independence**, but **not as literal
absence of reads**: `postgres_repository.py:972`–`:1114` and
`sqlite_repository.py:3091`–`:3218` materialize category in fetched clusters. No cluster object
serialization was found feeding an evidence hash. Cluster IDs and memberships must not be
regenerated during migration. Source metadata and watchlist-supplied category are out of scope.

## 2. Removal surface and retained vocabulary

**Decision:** Remove runtime taxonomy paths together; preserve historical SQL and unrelated
lexicon machinery.
**Rationale:** `semantic_clusterer.py:60`–`:155` owns matcher state/registration/helpers;
`:175`–`:234` implements source-first fallback; `:567` stores the result. The synchronizer
reads/registers taxonomy at `vocabulary_loader.py:175`–`:184`, `:228`–`:229`.
`repository_port.py:281`, `postgres_repository.py:2221`, `sqlite_repository.py:4204` and
`server.py:3762`–`:3785` complete the live taxonomy read path. `resources.py:1`–`:8` has
obsolete descriptive wording but its SQL resource-resolution mechanism stays.
**Alternatives considered:** Leaving a dormant table/getter or returning an empty response key
would violate the explicit removal decisions. A replacement classifier is outside this spec.

Static parsing of `sql/003_market_lexicons.sql` confirmed **14 rows / 244 keywords** and **69
terms** across `fashion`, `tech`, `ecommerce`, `common_vi`. `sql/010_taxonomy_coverage.sql`
also carries the historical list. These are historical exceptions under SC-001, not active
seed sources after retirement. Platform UI and language vocabulary keep their existing paths.

## 3. SQLite lifecycle is a separate migration path

**Decision:** An explicit raw-connection retirement command; startup refuses an unretired
existing store, while fresh bootstrap stops creating/seeding taxonomy.
**Rationale:** `sqlite_repository.py:1524` begins bootstrap's schema script; `:1686` creates
taxonomy; `:2092`–`:2105` extracts lexicons from 003/004; `:2110`–`:2122` refreshes taxonomy
every bootstrap; `:2130` onward seeds independent platform vocabulary. There is no numbered
SQL runner. Running the entire old seed would reintroduce the table. Existing-ready opening
at `:640`–`:680` is explicitly non-upgrading, and `:793` validates instead of initializing.
`caller_storage.py` pins `<root>/.fnignis/canonical.sqlite3`; it is not a migration runner.
**Alternatives considered:** Applying the drop inside `_create_tables_and_seed` risks partial
commits, violates projection-before-change and widens caller write authority. A general
migration ledger/framework is unnecessary: table absence is sufficient for this one cutover.

## 4. PostgreSQL ordering and historical tests

**Decision:** Append 039, leaving all earlier files intact. Change latest-state expectations,
while exercising historical guarantees at their historical migration prefix.
**Rationale:** Current latest file is `038_tiktok_attribution_locales.sql`, pinned in
`tests/unit/test_sql_packaging.py:28` and `tests/integration/test_compose_init.py:89`.
006 enables RLS/installs read policies while taxonomy exists; 010 expands it; 021 includes it
in the read-only vocabulary; 022's UUID comment mentions it, while its ALTER list affects
other tables. All execute before 039 on a new database. Full-chain Compose currently expects
57 tables and 16 UUID defaults (`test_compose_init.py:177`–`:193`); removal means **56 and 15**,
with exact names still asserted. Supabase-like final state loses only the taxonomy read policy.
**Alternatives considered:** Editing 003/010 would violate immutable historical migrations;
dropping earlier would break historical security stages; skipping files in fresh init would
weaken existing installation guarantees.

Existing tests explicitly replay 006 after the final chain. With Supabase roles present,
006's guarded policy creation (`sql/006_supabase_security_hardening.sql:76`–`:82`) attempts to
create a policy on the absent table. Keep the old replay claim at the pre-retirement prefix;
assert post-retirement table/policy absence independently. Full-chain replay on a disposable
historical fixture can still end with no taxonomy, but it is not the recommended populated-store
upgrade path. An isolated 039 retry must preserve new source codes.

## 5. Projection and transaction design

**Decision:** One versioned, deterministic Python projection shared by backend readers and an
independent post-state verifier; SQL holds its own frozen code set for the numbered migration.
The script never initializes repositories. It reads only explicit cluster/evidence/vocabulary
surfaces, never credentials, author encryption keys or configuration files.
**Rationale:** Counts alone miss substitutions. Include a hash of targeted IDs/old labels, all
cluster fields, cluster fields excluding category, expected post-clusters and unchanged evidence
sets. Compare actual stored post-state before commit. Codes are migration identifiers, not
industry knowledge used by runtime matching. Their migration-only exception needs an inline comment.
**Alternatives considered:** Reading codes from a mutable/dropped table is not replay-safe;
reclassifying titles changes scope; exporting row bodies would unnecessarily disclose evidence.

Prior art: `scripts/t020_cutover.py:151`–`:230` holds a standstill and compares digests;
`scripts/post_migration_verification.py:1`–`:24` explains why recomputing a prediction is not
post-state verification. Do not reuse its unrelated backfill, credential resolution or baseline.

## 6. Targeted acceptance changes

Rewrite obsolete taxonomy assertions in `test_bug09_category_classification.py` and
`test_taxonomy_coverage.py` into origin-only behavior and retirement checks; keep invalid-source
coverage. Add no-read synchronization assertions in `test_vocabulary_loader.py`, update
`test_market_lexicons.py`, `test_sql_packaging.py`, and explicit-ready protected-set expectations
in `test_sqlite_existing_ready.py`, `test_caller_youtube_pilot_cli.py` and
`test_caller_analysis_composition.py`. Extend `test_graph_artifact.py` and maintained builder
coverage for `unclassified`. Add category-only before/after evidence parity in
`tests/integration/test_decision_grade_evidence.py` and a focused frame unit test.

Real PostgreSQL is required for 039 atomic DDL/DML, permissions, stale baseline/locking,
rollback, full-chain and RLS assertions in `test_postgres_migration_contract.py` and
`test_postgres_rls_coverage.py`; actual Compose is required for `test_compose_init.py` init proof.
Update `AGENTS.md` vocabulary protocol, `docs/PROJECT_REVIEW_CONTEXT.md:172`–`:179` and the
schema statement at `BACKLOG.md:1103` during implementation only. Historical records remain
historical; do not mass-replace every occurrence of the word taxonomy.
