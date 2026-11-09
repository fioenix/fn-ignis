# Vocabulary and Category Contracts

## MCP: list_domain_lexicons

Name and parameters remain `list_domain_lexicons(domain: Optional[str] = None) -> str`.
The returned string is JSON. For a successful request the exact keys are:

```json
{
  "status": "SUCCESS",
  "total_lexicon_terms": 0,
  "domain_filter": null,
  "lexicons": []
}
```

Values shown are an empty-store example, not a required production result. Domain filtering,
lexicon row format/order and count semantics are unchanged. `industry_taxonomies` is removed,
not set to null/empty. The description stops promising industry mappings. Errors preserve
`{"status": "ERROR", "message": "..."}`. No tool is removed or added; registry count remains 53.

Consumers: MCP host agents; `handle_list_domain_lexicons`; `tests/unit/test_market_lexicons.py`;
repository port/adapters and `VocabularySynchronizer`. Remove internal taxonomy getters and
registration together so startup never queries the dropped table. No external request schema
changes, compatibility alias, empty getter or replacement taxonomy tool is introduced.

## Category projection

A new cluster uses the existing normalized majority of usable source metadata categories,
otherwise `unclassified`. The existing unusable-category guard stays; no-source and invalid-source
inputs containing old taxonomy keywords must not infer a category. Current majority tie
semantics are unchanged. Post-migration source code `beauty` remains valid for new clusters.

Dashboard text and graph category options include `unclassified` using existing rendering;
filtering selects matching nodes. Trend cards continue without a category badge. Mission
reports continue using source categories for macro trends and persisted claims for Market
content. No regenerated old saved files are promised: already exported HTML remains unchanged.

## Unchanged analytical contracts

Category-only cluster mutation leaves observation metadata, memberships, qualification
relations/reasons, frame fingerprint/digest, sufficiency result, claim status/wording and
Attention handoff selection unchanged. Observation metadata category is part of evidence
hashing and is expressly outside the migration. `momentum_category` and lexicon bucket
`category` are also distinct concepts and remain.
