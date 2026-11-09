# Data Model: Taxonomy Retirement

## Topic cluster (retained)

`TopicCluster` in `src/ignis/domain/entities.py:65` stores `category` with default
`unclassified`. Persistence also holds ID, canonical name, topic label, cross-platform score,
summary and timestamps. The migration must enumerate actual columns so a future added column
cannot silently escape its preservation digest.

- New clusters: existing usable source-category majority, stripped and lowercased; otherwise
  `unclassified`. Keep the current minimum length and numeric/metric rejection behavior.
- Existing clusters, only while the legacy taxonomy table exists: exact old code →
  `unclassified`; every other category, including null/empty values, is unchanged.
- No lowercasing, trimming, substring matching, classification or provenance inference during
  migration. A source label equal to a retired code is reset as the spec expressly requires.
- ID, signal/observation membership, names, summaries, scores and all timestamps are unchanged.
- Source observation metadata and user watchlist labels are separate entities and unchanged.

## Former industry code (migration-local)

Frozen sorted values:

```text
auto, beauty, ecommerce, education, entertainment, fashion, finance, food,
health, news, realestate, sports, tech, travel
```

The Python migration module and PostgreSQL 039 each hold this exact immutable set, with an
inline explanation that these are retired data identifiers, not a runtime lexicon. A parity
test checks their exact equality to the historical code set, not a duplicated keyword corpus.
Neither projection nor apply derives the set from the installed taxonomy table, which might
have been edited or removed. No industry names or keyword arrays are copied into runtime code.

## Industry taxonomy (removed)

Table fields are `id`, `industry_code`, `industry_name`, `keywords`, `created_at`.
Drop the table and its owned indexes/constraints/RLS policies only. No CASCADE into unrelated
objects, no archive table and no replacement taxonomy. Historical migration files remain.

## Projection receipt (new local artifact; not a database entity)

| Field | Meaning |
|---|---|
| `format_version` | `ignis-taxonomy-retirement-v1` |
| `migration_id` | `039_remove_seeded_taxonomy` |
| `backend` / `store_identity` | Backend and non-secret target identity; never a DSN/password |
| `table_present` / `state` | `PENDING` or `ALREADY_RETIRED`; missing table makes the target set empty |
| `former_codes` / `former_codes_digest` | Frozen predicate and canonical identity |
| `cluster_count` | All persisted clusters, including categories that will not change |
| `matching_code_counts` | All 14 counts, including zero; informational even after retirement |
| `reset_counts` / `reset_total` | Actual pending change, zero if already retired |
| `target_digest` | Sorted cluster IDs plus original categories; identities are hashed, not exported |
| `clusters_before_digest` / `clusters_expected_after_digest` | Entire rows before / predicted category-only after |
| `cluster_noncategory_digest` | All actual cluster columns except category |
| `protected_sets` | Per-set row counts and digests for unchanged evidence and retained lexicons |
| `schema_before_digest` / `schema_expected_after_digest` | Only taxonomy-owned objects may disappear |
| `invariants` / `limitations` | Exact preservation checks and indistinguishable source-code collision notice |
| `projection_digest` | SHA-256 of canonical semantic receipt, excluding this field and run timestamp |

The protected sets are canonical `sources`, `observations`, `mission_evidence`, legacy
`trend_signals`/`signal_metrics`, `research_missions`, `mission_manifests`,
`market_brief_revisions`, `mission_run_journals`, `mission_probe_outcomes`,
`mission_evidence_qualifications`, `mission_claims`, `mission_claim_evidence`, and
`market_lexicons`. Preserve complete stored rows and counts, including binding rows. Do not
read `platform_credentials`, `mission_author_keys` or caller configuration. Live frame digests
are derived from the unchanged protected rows; integration tests additionally compare actual
frame objects and permitted/withheld claims before and after retirement.

## Canonical encoding

Version the serialization, sort table/column names, sort rows by stable primary/composite key,
and hash length-delimited canonical JSON records (`sort_keys=True`, `ensure_ascii=False`,
compact separators). Tag scalar types; preserve null versus empty, exact strings and exact
numeric values. Encode datetimes in UTC at stored precision, UUIDs in standard text, bytes as
hex, and JSON values with sorted object keys and original array order. Refuse unsupported or
non-finite values rather than silently coercing them. No volatile run time, file path or SQL
connection rendering belongs in a content digest. Include schema/version and row counts to
avoid collisions between different record domains. Test deterministic reordered reads and a
single-field negative control. A baseline is compared only with its own backend/store; no
claim of byte-identical SQLite/PostgreSQL raw storage is necessary.

## State transitions

```text
legacy table present -> read-only PENDING projection -> publish exact receipt
  -> quiesce/recheck under write lock -> UPDATE + DROP + actual verification -> commit
  -> table absent / ALREADY_RETIRED
```

Drift, missing projection, failed invariant, unexpected dependent object or injected failure
causes rollback and leaves the pre-state intact. Table already absent → no data change,
regardless of source categories created since retirement. Fresh SQLite starts without the
table; fresh PostgreSQL creates it historically and removes it at the end of the chain.
There is no persistent migration-state row to add, no partial state to repair automatically,
and no permission for read-only analysis to migrate a caller store.
