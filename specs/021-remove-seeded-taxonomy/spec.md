# Feature Specification: Remove the Seeded Industry Taxonomy

**Feature Branch**: `021-remove-seeded-taxonomy`

**Created**: 2026-11-09

**Status**: Implemented, merged (PR 125) and applied to both development stores on 2026-11-10; not released.

**Input**: Owner request (09/11/2026): "tao vẫn thấy là trong ignis không nên có các hardcode kiểu này", about the seeded industry taxonomy; followed by "Nhưng mà bộ taxonomy này có ý nghĩa với các nghiên cứu thị trường à" and, after the analysis, "OK làm đi". (Ignis should not carry this kind of hardcoding; the taxonomy adds little to market research; go ahead.)

## Outcome and why

Ignis ships a fixed list of 14 industries and 244 keywords and uses it to put a category label on topic clusters. The label decides nothing: the Claim Ledger, evidence qualification and sufficiency do not read it, and it only appears on reports and as a filter.

The list is domain knowledge that changes only with a release, since no tool edits it and the SQLite store is re-seeded from the file at each start. Its quality was also weak: in the September corpus, 179 of 342 classified clusters rested on one bare token, most of them coincidental. The 2026-09-25 decision already rejected expanding taxonomies as a fix, because better labels do not make an unrelated observation relevant. Since the 2026-10-21 decision, a research scope comes from the question or the watchlist the person writes, and the host agent judges relevance.

The observable proof: a cluster with no category from its source reads `unclassified`, no shipped file holds an industry keyword list, and earlier taxonomy-assigned labels are gone from stored clusters and from reports.

## Clarifications

### Session 2026-11-09

- Q: How does the `list_domain_lexicons` output change? → A: The `industry_taxonomies` key is removed; the tool's name and parameters are unchanged (owner decided).
- Q: What happens to the category already stored on existing clusters by the taxonomy? → A: It is reset to `unclassified` by a migration. This transforms persisted data, so Constitution VI applies (owner decided, in place of the option to keep the old labels).
- Q: What happens to the `industry_taxonomies` table? → A: A new migration drops it and the SQLite seeding stops; earlier migrations stay as written (owner decided).
- Q: Does this spec also remove the domain terms seeded in `market_lexicons`? → A: No. The 69 domain terms in `sql/003` (fashion, tech, ecommerce, common_vi) feed the quality evaluator and the strategic reasoner, so removing them changes scoring and needs its own measurement. They are recorded as follow-up work (owner decided).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Clusters carry only labels with a real origin (Priority: P1)

A person reads a mission report. A topic shows a category only when the source platform supplied one; otherwise it reads `unclassified`, rather than a guess from a keyword list.

**Why this priority**: This is the behaviour the removal exists for; everything else follows from it.

**Independent Test**: Cluster signals whose titles contain former taxonomy keywords, with and without a source-provided category, and read the resulting category.

**Acceptance Scenarios**:

1. **Given** signals with no source category whose titles contain former taxonomy keywords, **When** they are clustered, **Then** the cluster's category is `unclassified`.
2. **Given** signals with a usable source category, **When** they are clustered, **Then** the cluster keeps the most common source category, as it does today.
3. **Given** a newly installed store on either backend, **When** Ignis starts, **Then** no industry keyword list exists and clustering works.

---

### User Story 2 - Earlier taxonomy labels are removed from stored clusters (Priority: P2)

An operator upgrades an existing store. Clusters labelled by the taxonomy become `unclassified`, and the operator can see beforehand exactly what will change.

**Why this priority**: The owner chose one consistent reading of category across old and new clusters. It changes stored data, so it needs its own evidence.

**Independent Test**: Run the published projection and the migration on a rehearsal copy holding taxonomy-labelled and source-labelled clusters, then compare counts and the digest.

**Acceptance Scenarios**:

1. **Given** a store with clusters labelled with former industry codes, **When** the projection runs, **Then** it reports per-category counts, the invariants and a deterministic digest without changing data.
2. **Given** the published projection, **When** the migration runs, **Then** exactly the projected clusters read `unclassified` and every other cluster field is unchanged.
3. **Given** a cluster whose category is not one of the former industry codes, **When** the migration runs, **Then** its category is unchanged.
4. **Given** the migration has already run, **When** it runs again, **Then** nothing changes.

---

### User Story 3 - The product no longer exposes a taxonomy (Priority: P3)

An agent listing Ignis vocabulary sees only lexicons, and no document tells a contributor to extend an industry taxonomy.

**Why this priority**: It closes the contract and the guidance once the behaviour is gone.

**Independent Test**: Call `list_domain_lexicons` and read the keys; search the shipped files and agent guidance for the taxonomy.

**Acceptance Scenarios**:

1. **Given** the updated server, **When** `list_domain_lexicons` is called, **Then** the response has no `industry_taxonomies` key and every other key is unchanged.
2. **Given** the repository, **When** `AGENTS.md` is read, **Then** the vocabulary protocol no longer names an industry taxonomy path.

### Edge Cases

- A source category that happens to equal a former industry code, such as `beauty`, cannot be told apart from a taxonomy label on a stored cluster. The migration resets it too, and the projection reports that this cannot be distinguished. New clusters keep such a source category.
- A store where the table is already absent: the migration succeeds and changes nothing.
- A store with no taxonomy-labelled cluster: the projection reports zero and the migration only drops the table.
- A mission report or dashboard generated before the upgrade is a saved file and keeps its old labels.
- The migration fails partway: no cluster is changed and the table is not dropped.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Clustering MUST assign a category only from a usable source-provided category; otherwise the category MUST be `unclassified`.
- **FR-002**: Ignis MUST NOT ship, seed, load or register an industry keyword list, on any backend or install path.
- **FR-003**: `list_domain_lexicons` MUST omit `industry_taxonomies`, and MUST keep its name, parameters and all other response keys.
- **FR-004**: A new migration MUST set the category of clusters holding a former industry code to `unclassified`, and MUST drop the `industry_taxonomies` table. Earlier migrations MUST stay as written.
- **FR-005**: Before the migration changes data, a projection MUST publish the per-category counts, the invariants and a deterministic digest (Constitution VI). The projection MUST NOT write.
- **FR-006**: The migration MUST change no cluster field other than category, no observation, no claim and no evidence frame.
- **FR-007**: The migration MUST apply as one all-or-nothing step and MUST be safe to run again, on both PostgreSQL and SQLite.
- **FR-008**: A cluster with category `unclassified` MUST render on every report and filter as it does today.
- **FR-009**: The number of MCP tools MUST stay 53, and no connector, collection or Market gate behaviour MUST change.
- **FR-010**: `AGENTS.md` and the other contributor guidance MUST stop naming an industry taxonomy path. Platform-interface labels and language-detection vocabulary MUST remain seeded data.
- **FR-011**: The 69 domain terms seeded in `market_lexicons` MUST remain unchanged by this feature.

### Key Entities

- **Topic cluster**: A stored topic grouping; its category is either from the source or `unclassified`.
- **Former industry code**: One of the 14 codes seeded by the taxonomy, used only to identify the stored labels to reset.
- **Migration projection**: The read-only report of what the migration will change, with counts, invariants and a digest.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: No shipped file contains an industry keyword list, apart from the unchanged historical migrations.
- **SC-002**: On a test corpus, 100% of clusters without a source category read `unclassified`, and 100% of clusters with a usable source category keep it.
- **SC-003**: On a rehearsal copy, the number of clusters changed equals the projected number exactly, and no field other than category differs on any cluster.
- **SC-004**: The tool list still reports 53 tools, and the only difference in the `list_domain_lexicons` output is the removed key.
- **SC-005**: Running the migration a second time changes zero rows.

## Assumptions

- The persistent stores in use are development stores; there is no production environment.
- The evidence path does not read cluster category. This was found by search and must be confirmed during planning, including `discover_market_opportunities` and the qualification branch of `get_mission_analysis`.
- Removing the 14 industry codes from the migration's projection list after it ships is out of scope; the migration holds its own copy of the codes.
- Follow-up work, not in this spec: the 69 domain terms in `market_lexicons`, the unused public ingestion path that reads lexicon seeds, and any category a person supplies through a watchlist.
