# Research: No Author Identity at Rest

All findings were read from `main` at `11f4025` on 20/10/2026. File references are relative to the
repository root. Nothing here was verified against live platforms unless stated.

## R1. Where identity is removed

**Decision**: Apply one domain policy in the application layer, in
`application/use_cases/execute_mission.py::_execute_pass`, before `save_clusters` and
`save_signals`. Back it with a fail-closed guard inside both repositories' `_record_observations`,
which refuses any signal still carrying an author key or a handle-bearing URL.

**Rationale**:
- Every persisted observation passes through `save_signals` → `_record_observations`
  (`sqlite_repository.py:1876`, `postgres_repository.py:265`).
- The only live caller is `_execute_pass` (`execute_mission.py:650`). Host browser missions reach
  it through `_execute_authorized`.
- `save_clusters` runs first and derives cluster names from titles, so the policy must run before
  it.
- The repository guard turns a missed path into a failure instead of a silent leak. The dormant
  callers (`ingest_trends.py`, `cluster_signals.py`, `refinement_orchestrator.py`) are covered by
  the same guard.

**Alternatives considered**:
- Fix each connector. Rejected: this keeps the invariant at the mercy of every future connector.
- Guard only in the repository. Rejected: the repository has no mission declarations or marker key,
  and clustering would still see identity.

## R2. Which fields count as author identity

**Decision**: A domain module `domain/author_identity.py` owns one list of author field names. It
reuses `AUTHOR_METADATA_KEYS` and `ACCOUNT_ID_METADATA_KEYS` from `domain/self_content.py` and adds
the observed keys:
- `channel_id`, `channel_title`, `channel`
- `author_name`, `nickname`, `unique_id`, `uniqueId`
- `user`, `profile_url`, `avatar`

It also strips identity carried in nested comment records (`author`, `author_id`) and in
`video_url`.

**Rationale**: These are platform payload field names, not market vocabulary. Constitution V keeps
domain vocabulary data-driven; a structural schema is code. The module's docstring says so.

**Alternatives considered**: Seeding the list in `runtime_configs`. Rejected: an operator could
weaken a privacy invariant by editing configuration.

## R3. Author marker

**Decision**:
- `marker = HMAC-SHA256(mission_key, "<platform>:<account id, else normalised handle>")`, truncated
  to 16 hexadecimal characters (64 bits).
- No author value yields an `UNKNOWN` state with no marker.
- `mission_key` is 32 random bytes per mission. It is created on first collection and stored
  Fernet-encrypted with the existing `IGNIS_ENCRYPTION_KEY` (`infrastructure/auth/crypto.py`) in a
  new table `mission_author_keys`.

**Rationale**:
- With 64 bits and ten thousand authors, the collision probability is about 2.7e-12, which meets
  SC-002.
- HMAC with a per-mission key makes markers unlinkable across missions (SC-003).
- Encrypting the key under a secret that is not in the database means a copy of the database alone
  cannot test candidate handles against markers.
- Fernet is already a dependency and already protects `platform_credentials`.

**Alternatives considered**:
- Plain salted hash with the salt stored beside it. Rejected: a dictionary attack against a known
  handle needs only the database.
- A key file in the research folder. Rejected: PostgreSQL deployments have no parity for it, and
  Spec 014's caller storage is not on `main`.
- The current fixed salt with 4 hexadecimal characters (`tiktok_plugin.py:541`). Rejected: it is
  linkable across missions, leaks a two-character prefix and collides at around 300 authors.

**Missing encryption key**: collection continues, every author state becomes `UNAVAILABLE`, and
the mission records a visible limitation that distinct-author counts are unavailable.

## R4. Where markers and declared identity live

**Decision**: New columns on `mission_evidence` (mission × observation):
- `author_state` (`KNOWN` | `UNKNOWN` | `UNAVAILABLE` | `DECLARED`)
- `author_marker`
- `declared_account_id` (FK, `ON DELETE SET NULL`)

**Rationale**: `observations` and `sources` are canonical rows that several missions can reference
through `mission_evidence`. A per-mission marker on the observation would leak across missions,
whereas the association row is per mission by construction.

## R5. Content reference and links

**Decision**:
- `sources.external_id` comes only from a content identifier: the `METADATA_KEYS` or `URL_PATTERNS`
  in `domain/source_identity.py`.
- The `normalized_url_fallback` path is kept only for URLs that carry no social handle or profile
  segment, such as Google Trends news articles.
- `observations.source_url` stores a canonical identity-free link built from platform and content
  identifier, or `NULL`.

| Platform | Content identifier | Identity-free link |
|---|---|---|
| YouTube | `video_id` | `https://www.youtube.com/watch?v=<id>`, already in use |
| Instagram Reels | `reel_id` / shortcode | `https://www.instagram.com/reel/<code>/`, already in use |
| TikTok | `item_id` | **Unverified**: a link without `@handle` must be probed live |
| Threads | `post_id` / code | **Unverified**: a link without `@handle` must be probed live |

Until a live probe proves a handle-free form, that platform shows its content identifier with the
label "link unavailable" (SC-004). The probe uses a public page and no signed-in session; this is
not a real-session use under AGENTS.md Section 8.

**Rationale**: The resolver already prefers content identifiers. Only the URL fallback can put a
handle into `external_id`.

## R6. Observations with no content reference

**Decision**:
- Such an observation is kept with a new `identity_source` value `unverifiable_content`.
- Its `external_id` is `content:<sha256 of platform, normalised text and publication time>`.
- Qualification forces relation `CONTEXT_ONLY`, reusing `QualificationRelation.CONTEXT_ONLY` and
  the rule that CONTEXT purpose requires it.
- Both claim-binding triggers refuse a SUPPORT binding to such an observation (SC-010).

**Rationale**: The claim gate and triggers (`sqlite_repository.py:661-730`, `sql/025`) already
separate context from support. Adding one refusal reuses the existing fail-closed path.

## R7. Handles inside text

**Decision**:
- At ingress, `@mention` tokens in titles, captions, excerpts and comments are replaced with a
  placeholder token.
- A mention of a declared account becomes `@[declared:<declared_account_id>]`; any other mention
  becomes `@[user]`.
- At display time a declared token renders as the declared name. After the declaration is withdrawn
  it renders as `@[user]`.
- The mention regular expression is a character-class pattern, the allowed exception in
  `CLAUDE.md`, and carries a comment saying so.

**Rationale**: Observations are immutable. Storing a token rather than the handle lets withdrawal
remove the identity (FR-018) without rewriting evidence.

## R8. Declared accounts

**Decision**: A new mutable table `mission_declared_accounts` holds:
- `id`, `mission_id`, `platform`
- `account_key` (normalised handle or account identifier)
- `declared_name`, `declared_at`

The table is kept outside `MissionManifest`. Withdrawal deletes the row; `ON DELETE SET NULL`
clears evidence references, and tokens stop rendering a name.

**Rationale**: `MissionManifest` is frozen and digest-bound (`domain/research_workspace.py:207`).
Adding a mutable list to it would change existing digests and forbid withdrawal.

**MCP surface — owner gate (AGENTS.md Section 8)**:
- Recommended: one new tool, `set_mission_declared_accounts(mission_id, accounts)`, which replaces
  the mission's declaration set and returns it.
- The tool count rises by one: 47 → 48 once PR #51 merges (`main` has 44 today). Every governed
  tool-count surface changes with it.
- Alternative: an optional `declared_accounts` argument on `create_attention_mission`, plus a
  withdrawal path. Rejected: it changes an existing signature and still needs a second operation
  for withdrawal.
- The owner approved the new tool on 2026-10-20 (OG-1).

## R9. Reports and tool responses

**Decision**:
- Citations (`domain/harness_models.py:47`, `harness/strategic_reasoner.py:517`) set
  `author_or_channel` only for declared accounts.
- `templates/html/mission_report.html` lines 389, 595-597 and 701-702 render only declared names.
- `get_mission_analysis` replaces `stats.top_creators` with
  `author_concentration{distinct_authors, unknown, unavailable, top_share}` per channel.
- Atomic probes `get_tiktok_video_comments` and `extract_customer_pain_points` drop `author`,
  `author_id` and `video_url` handles, and return a per-response concentration, computed with an
  ephemeral key that is never stored.
- Evidence and qualification batches return the identity-free `source_url`.

**Consumers**: The response-shape change for `get_mission_analysis` and
`discover_market_opportunities` is an output contract change, not a signature change. It is listed
in `contracts/` with its consumers: the report builder, the `ignis-analyze` skill text and tests.

## R10. Evidence frame digests

**Decision**: Accept that frames built after the change digest identity-free metadata. Existing
frames and their digests are untouched, because legacy rows are not rewritten by this feature.

**Rationale**: `current_evidence_frame.py:57-80` digests metadata. SC-008 compares claims,
permissions and Gap Report outcomes, not digests. A legacy disposition that rewrites metadata
would invalidate stored digests; it is therefore an owner decision (FR-015) and outside this
feature.

## R11. Logs

**Decision**:
- Remove the handle-bearing URL from `tiktok_plugin.py:610` and the operator username from the
  Threads log at `threads_plugin.py:488`.
- The conformance test captures logs.
- `log_event` already sanitises, and journals carry no payloads.

## R12. Conformance check

**Decision**: A runtime integration test runs a SQLite mission through fake connectors. The fakes
place sentinel identities in every known author field, in URLs and in `@mentions`, for every
registered connector. The test then scans:
- every table
- research-folder files
- generated report HTML
- MCP responses
- captured logs

It asserts that no sentinel appears except those of declared accounts. A registry test fails when a
registered connector has no fixture, so future connectors are covered. A leaking fake connector is
the negative control (SC-007). The PostgreSQL run of the same test is skipped without a DSN and
reported as such.

**Alternatives considered**: An AST scan of connector metadata keys alone. Rejected: it cannot see
values assembled at runtime. It is kept only as a fast supplementary check.

## R13. Legacy inventory

**Decision**: `scripts/inventory_author_identity.py` opens the store read-only:
- SQLite: `mode=ro`
- PostgreSQL: `SET TRANSACTION READ ONLY`, from a DSN read from an environment variable whose
  value is never printed

It reports, per table and field, counts of rows with author keys, handle-bearing URLs and
handle-derived `external_id` values, as JSON with counts only. It is not an MCP tool, so the tool
surface is unchanged.

The dev Supabase run is a read under the owner's 02/10/2026 dev preauthorisation, and needs the DSN
present in the environment.

## R14. Migration

**Decision**: Use the additive `sql/031_author_identity_at_rest.sql` with matching SQLite DDL in
`_ensure_schema`. It covers:
- the new tables `mission_author_keys` and `mission_declared_accounts`
- the `mission_evidence` columns
- the `identity_source` CHECK extended with `unverifiable_content`

The SQLite change uses the existing rebuild-table pattern.

**Numbering**: `main` ends at `026`, while Spec 014 (PR #51) adds `027`–`030`. Number `031` avoids a
collision. This feature should be implemented after PR #51 merges, rebased on `main`, so the latest
migration is unambiguous and Spec 014's snapshot rows fall under FR-002 and FR-016. Pinned latest
migration surfaces must change with it: `tests/unit/test_sql_packaging.py:23`,
`tests/integration/conftest.py:60` and `test_public_distribution_contract.py`.

The migration adds structure and does not transform persisted evidence, so Constitution VI's
projection and digest requirements do not apply. Changing legacy data does (FR-015).

## R15. Self-content exclusion on the host browser path

**Decision**: `host_browser_mission.py` applies `partition_self_authored` before the identity
policy. Today host browser signals bypass the registry scope guard (`registry.py:749`), so the
operator's own content is not excluded on that path.

## R16. Free-text personal names

**Decision**: Out of scope (Clarification 4). The user guides state what is removed and that
names in free text are not.
