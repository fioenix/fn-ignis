# Feature Specification: Retire Seeded Market Domain Vocabulary

**Feature Branch**: `023-retire-domain-vocabulary`

**Created**: 2026-11-11

**Status**: Draft

**Input**: Owner request (11/11/2026): "Có thể làm ngay, không cần chờ ai — làm đi", pointing at the backlog item
"69 từ miền trong `market_lexicons` … cần đo riêng trước khi bỏ" and the small debt "đường discovery Google
Trends đã chết". (Do the items that need nobody's input.)

## Outcome and why

Spec 021 removed the seeded industry taxonomy, but the seeded market domain vocabulary survived it. That
vocabulary is a taxonomy in all but name: hand-picked terms grouped by industry (`tech`, `ecommerce`,
`fashion`, `common_vi`, and the `global_*` domains from `sql/004`). It drives two mechanisms, and both are
wrong by construction:

1. **False synonyms.** Terms sharing a `(domain, category)` bucket are registered as expansions of each
   other, so topic matching treats `shopee`, `lazada` and `tiktok shop` as the same keyword, and treats
   `n8n` as matching any title with the English word `make`.
2. **False Vietnamese evidence.** Every market term of three or more characters joins the Vietnamese core
   words used to accept unaccented text, so English loanwords such as `make`, `review`, `outfit` and
   `chatbot` count as proof a title is Vietnamese.

The observable proof: neither mechanism exists, the seeded rows are gone from every store, and nothing a
user reads changes on current evidence.

## Evidence (measured on 2026-11-11, development SQLite store, read-only)

| Measurement | Result |
|---|---|
| Rows in the seven market vocabulary domains | 104, all `created_by = 'system'`: `tech` 24, `ecommerce` 21, `fashion` 15, `common_vi` 9 (the backlog's 69), plus `global_saas_ai` 15, `global_ecommerce` 11, `global_fashion` 9 |
| Localization verdicts that change when the vocabulary is removed, over 634 stored observation titles | 0 (572 localized either way) |
| Keyword × title matches that exist only through a synonym expansion, over 37 stored mission keywords | 0 (no stored keyword is in the synonym index) |
| `"Make a chatbot with n8n and zapier"` judged Vietnamese | Yes with the vocabulary, no without |
| `"Lazada sale 11.11 giảm giá"` matches keyword `shopee` | Yes with the synonym groups |
| `"How to make bánh mì tại nhà"` matches keyword `n8n` | Yes with the synonym groups |

Consumers traced in code: `VocabularySynchronizer.synchronize_vocabulary` registers the vocabulary into
`QualityEvaluator.register_terms`, `StrategicMarketReasoner.register_terms` and
`StrategicMarketReasoner.register_synonym_groups`. Two more readers are unreachable from any tool:
`IngestTrendsUseCase` (built in `server.py`, never called; its only caller of
`ConnectorRegistry.fetch_from_all` in `src/`) and `AutonomousRefinementOrchestrator` (no caller in `src/`).

## Clarifications

### Session 2026-11-11

- Q: Remove only the seeded rows, or the mechanisms too? → A: Both mechanisms and the seeds. `register_domain_lexicon` keeps its name and parameters; its description stops promising market-term recognition (owner decided).
- Q: What happens to rows already in existing stores? → A: Delete them by migration; no backup is required (owner decided). Lexicon rows are vocabulary, not evidence, so Constitution VI's evidence-migration rule does not apply.
- Q: Are the dead Google Trends discovery path and the unused refinement orchestrator removed here? → A: `IngestTrendsUseCase` and `AutonomousRefinementOrchestrator` are, as the remaining readers of this vocabulary; removing them keeps every tool contract (agent decided; basis: AGENTS.md section 8, internal refactors that keep every contract).
- Q: `ConnectorRegistry.fetch_from_all` becomes unreachable once `IngestTrendsUseCase` goes — remove it too? → A: No. Six test files use it to prove the self-content, regional-script and daily-ceiling gates; removing it first needs those proofs moved to the live mission path. It stays as a backlog debt (agent decided; basis: Proportion, unknown coverage loss).
- Q: `_contiguous_phrase` reads only `canonical_name` — in scope? → A: No. It is cluster labelling, unrelated to this vocabulary; it stays in the backlog's small debts (agent decided; basis: Proportion).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Topic matching and language checks use no seeded vocabulary (Priority: P1)

A requester runs a mission or reads a quality scorecard; a title counts as on-topic only when it carries the
keyword, and counts as Vietnamese only on linguistic evidence.

**Why this priority**: The two mechanisms are the defect.

**Independent Test**: Run the topic-match and localization checks on the synthetic titles in Evidence with a
repository that holds market-domain rows.

**Acceptance Scenarios**:

1. **Given** market-domain rows in the store, **When** `"Lazada sale 11.11 giảm giá"` is matched against `shopee`, **Then** it does not match.
2. **Given** market-domain rows in the store, **When** `"Make a chatbot with n8n and zapier"` is checked for Vietnamese, **Then** it is not localized.
3. **Given** the mission path synchronizes vocabulary, **When** it runs, **Then** foreign stopwords, noise blacklist, ambiguous unigrams and language-detection vocabulary are still registered as before.

---

### User Story 2 - Stores hold no seeded market vocabulary (Priority: P2)

An operator lists lexicons on a new or an upgraded store and finds no seeded market domain rows.

**Independent Test**: Bootstrap a fresh SQLite store and upgrade one that holds the 104 rows; list the domains.

**Acceptance Scenarios**:

1. **Given** a fresh store, **When** it bootstraps, **Then** none of the seven domains has a `system` row.
2. **Given** a store holding the 104 system rows, **When** it starts or migrates, **Then** they are deleted, and a restart does not bring them back.
3. **Given** the same store, **When** lexicons are listed, **Then** every machinery domain keeps its rows unchanged.

---

### User Story 3 - Code and guidance carry no dead path (Priority: P3)

A contributor reading the code and tool descriptions finds no unreachable reader of the vocabulary and no
promise a tool does not keep.

**Acceptance Scenarios**:

1. **Given** the repository, **When** it is searched, **Then** `IngestTrendsUseCase` and `AutonomousRefinementOrchestrator` are gone and the catalog still has 41 tools with unchanged names and parameters.
2. **Given** the `register_domain_lexicon` description, **When** it is read, **Then** it no longer claims Quality Gate or Ingress recognition of market terms.

### Edge Cases

- An operator registered terms into one of the seven domains: the migration deletes only `system` rows; operator rows stay, inert.
- An operator registers a market term after this change: it is stored and listed, and no engine reads it.
- A Vietnamese title with diacritics: accepted as before; the diacritic rule never depended on the vocabulary.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Vocabulary synchronization MUST NOT register market-domain terms as localization evidence or as synonym groups.
- **FR-002**: Topic matching MUST NOT expand a keyword through lexicon buckets.
- **FR-003**: Registration of foreign stopwords, noise blacklist, ambiguous unigrams, language-detection and attribution vocabulary MUST behave as before.
- **FR-004**: Shipped seeds MUST NOT insert rows into the seven market domains, and a migration MUST delete their `system` rows on PostgreSQL and SQLite, idempotently.
- **FR-005**: `IngestTrendsUseCase` and `AutonomousRefinementOrchestrator` MUST be removed; a test that proves a still-live gate through them is re-pointed, not deleted. `ConnectorRegistry.fetch_from_all` stays.
- **FR-006**: Every MCP tool MUST keep its name and parameters; the catalog stays at 41.
- **FR-007**: No persisted evidence (observations, signals, missions, claims) MAY change.

### Key Entities

- **Market vocabulary domain**: one of the seven retired `market_lexicons` domains listed above; after this change no engine reads it.
- **Machinery domain**: a domain that drives a mechanism (stopwords, noise, detection, attribution, templates); unchanged.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: The three synthetic titles in Evidence give the "without vocabulary" result.
- **SC-002**: On the development store, the localization verdict of all 634 stored titles is unchanged.
- **SC-003**: After migration, the seven domains hold 0 `system` rows on a fresh and on an upgraded store.
- **SC-004**: The catalog lists 41 tools with unchanged signatures.

## Assumptions

- There is no production environment; the stores are development stores.
- Constitution V's rule that domain vocabulary stays data-driven is not weakened: no vocabulary moves into code.
