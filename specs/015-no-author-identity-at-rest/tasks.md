---

description: "Task list for Spec 015 — No Author Identity at Rest"
---

# Tasks: No Author Identity at Rest

**Input**: Design documents from `specs/015-no-author-identity-at-rest/`

**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md),
[data-model.md](data-model.md), [contracts/mcp-surface.md](contracts/mcp-surface.md),
[quickstart.md](quickstart.md)

**Tests**: Included. FR-013 requires an automated conformance check, and the repository works
test-first: each test task must be observed failing before its implementation task starts.

**Organization**: Tasks are grouped by user story. Paths are relative to the repository root.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependency on an incomplete task)
- **[Story]**: User story from spec.md (US1–US4)

---

## Phase 1: Setup

**Purpose**: Settle the base revision and shared fixtures.

- [x] T001 Wait for PR #51 to merge (OG-2 approved 2026-10-20: Spec 015 lands after Spec 014), then rebase `codex/no-author-identity-at-rest` on `main`. Record in `specs/015-no-author-identity-at-rest/plan.md` the base commit, the latest migration (expected `030`) and the tool count (expected 47). If either differs, stop and report before T006. Done 20/10/2026: PR #51 merged as `474916f`; the branch is rebased on it; latest migration `030_mission_follow_up_admission.sql`; 47 tools in `server.py` and README.md.
- [x] T002 [P] Create sentinel identity fixtures in `tests/fixtures/author_identity_sentinels.py`. Cover one recognisable value per author field from research R2, per platform. Add handle-bearing URLs for TikTok and Threads, `@mention` text with Vietnamese diacritics, and one operator self-account. Done 21/10/2026: also covers Reels, Google Trends (publisher only) and the host browser path, plus one declared brand account.

---

## Phase 2: Foundational (blocks every user story)

**Purpose**: Domain policy, marker, schema, key storage and the repository guard.

- [x] T003 [P] Write failing unit tests for field stripping in `tests/unit/test_author_identity_policy.py`. Cover every key in research R2, nested comment authors, `video_url` handles, and confirm that non-author metadata is preserved unchanged.
- [x] T004 [P] Write failing unit tests for markers in `tests/unit/test_author_marker.py`:
  - the marker is stable within one mission and differs across missions;
  - ten thousand distinct authors are counted exactly;
  - a missing author gives `UNKNOWN`;
  - a missing encryption key gives `UNAVAILABLE`.
- [x] T005 Implement `src/ignis/domain/author_identity.py`. It holds:
  - the author field list, reusing the key lists in `src/ignis/domain/self_content.py`;
  - `strip_author_identity`;
  - the HMAC-SHA256 marker truncated to 16 hex characters;
  - `@mention` tokenisation (`@[user]`, `@[declared:<id>]`), whose regex is commented as the character-class exception;
  - `AuthorConcentration`.

  T003 and T004 must pass.

  Done 21/10/2026: RED observed as `ModuleNotFoundError` for both test files; then 56 passed. Stripping removes author keys and handle-bearing links at any depth, and keeps comment counts. `assign_author` also returns `DECLARED` for a declared account, tested here. Deviation: `@mention` tokenisation is not in this module yet. It moves to T030, after its failing tests in T029, so that it is written test-first.
- [x] T006 Write `sql/031_author_identity_at_rest.sql` per data-model.md. It covers:
  - the tables `mission_author_keys` and `mission_declared_accounts`;
  - the `mission_evidence` columns `author_state`, `author_marker` and `declared_account_id`;
  - the `identity_source` CHECK extended with `unverifiable_content`.

  Mirror the DDL and the rebuild-table upgrade in `src/ignis/infrastructure/persistence/sqlite_repository.py` (`_ensure_schema`).
- [x] T007 Update the pinned latest-migration surfaces for `031`: `tests/unit/test_sql_packaging.py`, `tests/integration/conftest.py` and `tests/unit/test_public_distribution_contract.py`. Add a SQLite upgrade rehearsal test in `tests/unit/test_author_identity_schema.py`, covering a pre-031 database upgraded in place with counts unchanged.
  - Done 21/10/2026 (T006–T007). On SQLite, `observations` and `mission_evidence` are rebuilt from the same DDL text a fresh store uses, so an upgraded caller store keeps the supported core schema digest; the same-mission rule for a declaration is a trigger, since SQLite cannot null one column of a composite key. PostgreSQL uses a composite key with `ON DELETE SET NULL (declared_account_id)`. Also updated: `test_compose_init.py` (newest migration, two tables), `test_postgres_rls_coverage.py` (owner-only inventory for 031), the README and USER_GUIDE migration paragraphs (Vietnamese ones through the vietnamizer core workflow). Evidence: `test_author_identity_schema.py` 9 passed, and with the upgrade disabled 6 of 9 failed; unit suite on SQLite 2533 passed, 4 skipped, 1 deselected (`test_t020_cutover::test_a_pooler_is_not_refused_for_its_name`, a local-only failure that needs the worktree `.venv`); on a disposable TimescaleDB pg16, the migration-chain tests 105 passed and the PostgreSQL integration cases (`-k postgres`) 824 passed, 23 skipped, with no database left behind.
- [x] T008 Add repository methods `get_or_create_mission_author_key` and `destroy_mission_author_key` to `src/ignis/infrastructure/persistence/sqlite_repository.py` and `postgres_repository.py`. Fernet comes from `src/ignis/infrastructure/auth/crypto.py`. Test in `tests/unit/test_mission_author_keys.py` that the key is never returned decrypted to any caller other than the policy.
  - Done 21/10/2026. RED observed as `AttributeError` (no such method); then 7 passed on SQLite. Without a persistent `IGNIS_ENCRYPTION_KEY`, or when the stored key no longer decrypts after a key rotation, the method returns None and the policy marks authors `UNAVAILABLE`. The key is stored only as Fernet ciphertext and is not logged. `crypto.py` gains `encrypt_secret_bytes`, `decrypt_secret_bytes` and `decrypt_mission_author_key`, shared by both repositories. Parity: `tests/integration/test_mission_author_keys_parity.py` 6 passed on SQLite and a disposable TimescaleDB pg16, with no database left behind. A first attempt reached another session's container on a busy port; it is not counted, and the runner now picks a free port and stops if its own container does not start.
- [x] T009 Add a fail-closed guard in `_record_observations` of both repositories. It refuses a signal whose metadata holds an author key, or whose `source_url` or `external_id` holds a handle or profile segment. Test the refusal in `tests/unit/test_author_identity_guard.py`.
  - Done 21/10/2026 together with T015 (`9024405`): enabling the guard alone turned 11 test files red until the policy existed. The guard runs before the first row of a batch, so a refusal leaves nothing behind; the refusal names the kind of leak, never its value. Shared checks live in `infrastructure/persistence/author_identity_guard.py`. RED observed: 7 of 8 in `tests/unit/test_author_identity_guard.py` failed (no refusal, URL-only content skipped); then green. A handle URL as the only identity is refused at the URL and again at the key.

**Checkpoint**: The policy, schema, keys and guard exist; no caller uses them yet.

---

## Phase 3: User Story 1 — Research without keeping who said it (P1) 🎯 MVP

**Goal**: No author identity in any durable store, response, report or log, except declared accounts.

**Independent Test**: The sentinel mission in quickstart step 1 leaves zero undeclared sentinel values anywhere, and still produces observations and claims.

### Tests for User Story 1

- [x] T010 [US1] Write the failing conformance test in `tests/integration/test_author_identity_conformance.py`. It uses the dual-backend fixture with fake connectors, built from T002, for every registered connector and for host browser submissions, and scans:
  - Done 21/10/2026 (`261bc97`). Fixtures cover all six connector classes found by a file glob plus the follow-up bridge's YouTube subclass (covered by its parent's fixture); Google Trends and Creative Center plant no sentinel because their payload names no person, and a test asserts every other fixture plants one. RED observed: on the T013 source (before T015) the mission scan found 30+ leaks across tables, the report and MCP responses; the host browser case stayed red (strict xfail) until T016. The leaking connector is caught in `observations` on both backends.
  - all tables;
  - research-folder files;
  - generated report HTML;
  - MCP responses;
  - captured logs.

  Include a registry-coverage test that fails when a registered connector has no fixture, and a leaking negative-control connector that must fail (SC-001, SC-007). This phase scans author fields and URLs; `@mention` sentinels in text join the scan in T030.
- [x] T011 [P] [US1] Write the failing parity test in `tests/integration/test_author_identity_parity.py`. An existing mission fixture must produce the same claims, permissions and Gap Report outcome with the policy on (SC-008).
  - Done 21/10/2026 (`4daec45`). The claim fixture runs plain and with author fields and channel links passed through `apply_author_policy`; claims, permissions, Gap Report gates and the ledger match, for a permitted and a withheld case. RED was an `ImportError` only (no `ignis.application.author_policy` before T015): removing author fields changes no claim, so this is a non-regression check by design.
- [x] T012 [P] [US1] Write failing unverifiable-source tests in `tests/unit/test_unverifiable_source.py`. Cover the observation being kept with `unverifiable_content`, its forced `CONTEXT_ONLY` qualification, and the SUPPORT binding refused by both claim triggers (SC-010).
  - Done 21/10/2026 with T018 (`71d787d`). RED observed: `ImportError` for `require_verifiable_relation`, then behavioural RED once it existed: the use case recorded a support judgment and a claim resting only on unverifiable content was PERMITTED. The trigger case is also in `tests/integration/test_unverifiable_source_triggers.py` for both backends.

### Implementation for User Story 1

- [x] T013 [US1] In `src/ignis/domain/source_identity.py`, refuse the handle or profile URL fallback, add the `unverifiable_content` identity (`content:<sha256>`), and add the identity-free canonical link builder for YouTube, Reels, TikTok (`share/video/<item_id>`) and Threads (`threads.com/t/<shortcode>`, keeping the shortcode as the content reference) per research R5. Extend `tests/unit/test_source_identity.py`.
  - Done 21/10/2026, before T009/T015 as the dependency order requires: T015 needs the link builder to drop a handle-bearing URL without losing the content reference it carries. RED observed as `ImportError` (no `IDENTITY_UNVERIFIABLE_CONTENT`, no `identity_free_source_url`); then `test_source_identity.py` and `test_migration_reconciliation_audit.py` 91 passed, and the unit suite on SQLite 2552 passed, 4 skipped, 1 deselected (the local-only `test_t020_cutover` pooler case). `resolve_source_identity` takes optional `content_text` and `published_at`; without them, as the audit and backfill call it, a profile URL now resolves to nothing rather than to a handle-bearing key. The Threads link is built from the permalink's shortcode first, so the alias co-witness with the numeric `post_id` still holds. The repositories start passing the text in T009/T015.
- [x] T014 [US1] Probe live public pages, without a signed-in session, for handle-free TikTok and Threads content links. Record the outcome in `specs/015-no-author-identity-at-rest/research.md` R5. Add a platform to the link builder only when the probe proves the form opens the content; otherwise keep "link unavailable". Done 20/10/2026: TikTok `share/video/<id>` and Threads `t/<shortcode>` verified; the builder change moves into T013.
- [x] T015 [US1] In `src/ignis/application/use_cases/execute_mission.py` (`_execute_pass`), apply the policy before `save_clusters` and `save_signals`, and write `author_state`, `author_marker` and `declared_account_id` on `mission_evidence` in both repositories.
  - Done 21/10/2026 with T009 (`9024405`). `TrendSignal.author_assignment` is a non-persisted field (compare=False) that both writers read in `_record_observations`, so the journal path (`commit_collection_observations`) records the same facts. A mission row whose signal skipped the policy is recorded UNKNOWN; NULL stays reserved for pre-031 rows. Reattached observations (`attach_mission_evidence`, `commit_collection_membership`) keep the row they already have. Ordering deviation: T013 ran first (`aa804f8`) because dropping a handle URL without the link builder lost the content id. 11 test files moved to identity-free data. Consumer impact left open for T025: `creator_diversity_score` read `channel_title`, so for new missions it falls back to its no-data default (70) until markers feed it.
- [x] T016 [US1] In `src/ignis/application/use_cases/host_browser_mission.py`, apply `partition_self_authored` before the policy. Keep validator acceptance of handle URLs in `src/ignis/infrastructure/connectors/host_browser/validator.py` and drop the handle at the policy. Extend `tests/unit/test_self_content_scope.py`.
  - Done 21/10/2026 (`c191ca0`). RED observed: the operator's own post was stored and the receipt echoed the handle link. The in-memory ticket keeps the submitted link until ingestion (the marker needs the handle); every receipt returned to a caller carries the share link. `ConnectorPluginRegistry.self_identities` exposes the known accounts.
- [x] T017 [P] [US1] In `src/ignis/infrastructure/connectors/tiktok/tiktok_plugin.py`, remove the fixed-salt comment pseudonymisation and the handle-bearing log line. In `src/ignis/infrastructure/connectors/threads/threads_plugin.py`, remove the operator username from the log line.
  - Done 21/10/2026 (`5ce5728`). RED observed for the comment pseudonym, the handle in two log lines (including the unparseable-URL warning) and the operator name in the Threads verdict. Comments keep the platform comment id, not a salted hash.
- [x] T018 [US1] Apply forced `CONTEXT_ONLY` for unverifiable content in `src/ignis/domain/research_workspace.py`. Add the SUPPORT refusal to the SQLite trigger in `sqlite_repository.py` and to the PostgreSQL trigger in `sql/031_author_identity_at_rest.sql`. T012 must pass.
  - Done 21/10/2026 with T012 (`71d787d`). Unverifiable content is refused a support or contradiction judgment (`UNVERIFIABLE_SOURCE`); context, exclusion and UNASSESSED stay open. A new trigger `refuse_unverifiable_claim_support` on both backends, added to `sql/031` (unreleased) and the SQLite claim-trigger block. "Forced" is implemented as refusal, not coercion, so the stored judgment is always the judge's own.
- [x] T019 [US1] Make citations identity-free in `src/ignis/infrastructure/harness/strategic_reasoner.py` and `src/ignis/domain/harness_models.py`, setting `author_or_channel` only for declared accounts. In `src/ignis/infrastructure/templates/html/mission_report.html`, render a declared name or nothing, and a link or "link unavailable".
  - Done 21/10/2026 (`c75c48e`), declared names with T021. RED observed: citation named the channel and the report rendered the channel, inquiry author and handle link. Rows stored before the policy are covered: the builder strips each signal and rebuilds the link, and shows "link unavailable" otherwise.
- [x] T020 [US1] Update the MCP response shapes in `src/ignis/interfaces/mcp/server.py` and `src/ignis/application/use_cases/get_mission_analysis.py`, `get_evidence_qualification_batch.py`, per `contracts/mcp-surface.md`. Remove `top_creators`, the comment `author`/`author_id`, `inquiries[].author` and handle-bearing URLs, and add `source_verifiable`.
  - Done 21/10/2026 (`0beddf1`). RED observed in all five new tests. `author_concentration` is added by T025/T026, not here. Rows and connector payloads that still hold identity are stripped at the response boundary too.
- [x] T021 [US1] Write a failing test, then implement the approved tool `set_mission_declared_accounts` (OG-1). The test is `tests/integration/test_declared_accounts.py`. The repository methods for `mission_declared_accounts` go in both repositories, and the tool in `src/ignis/interfaces/mcp/server.py`. Follow the contract's normalisation, duplicate refusal, mission-scope refusal and replace-set semantics, with declarations applying only to content collected after `declared_at` (SC-009).
  - Done 21/10/2026 (`b630c9d`, follow-up `3222fb9`). RED: `ModuleNotFoundError`. Replace semantics keep a restated account's id and declared_at, so attribution survives a restatement. The full PostgreSQL run caught a clock defect: `declared_at` came from the database clock while `captured_at` comes from the host, so content collected right after a declaration could go unattributed; both backends now stamp in process, with a test that pins it.
- [x] T022 [US1] Raise every governed tool-count surface by one. Regenerate the Hermes manifests with `scripts/sync_tool_manifests.py --write`. Update the contract, drift, distribution and doc-convention tests, `scripts/wheel_mcp_smoke.py` expectations, README.md, README.vi.md, CLAUDE.md, AGENTS.md, openclaw.json, BACKLOG.md and `.github/workflows/ci.yml`. `tests/unit/test_public_distribution_contract.py` and `tests/unit/test_tool_manifests_drift.py` must pass.
  - Done 21/10/2026 (`b630c9d`, follow-up `cfc135b`). Hermes manifests regenerated with `scripts/sync_tool_manifests.py --write`; the BACKLOG branch sentence was edited through the vietnamizer workflow (Jev ran but returned `invalid_response` for most patterns, so the core workflow decided; one V18 fix). The Vietnamese guides changed only the number. Three more catalog pins surfaced in the full run and were fixed in `cfc135b`.
- [x] T023 [US1] Run T010 and T011 to green on SQLite, plus PostgreSQL when `IGNIS_TEST_POSTGRES_DSN` is present. Record the commands, revision and skips in `.handoff/spec015/us1.handoff.md`.
  - Done 21/10/2026. Full suite on SQLite at `cfc135b`: 4103 passed, 1002 skipped, 1 deselected (the local-only `test_t020_cutover` pooler case). `tests/integration -k postgres` on a disposable TimescaleDB pg16 against an export of `3f192d9`: 884 passed, 23 skipped, 0 failed, no database left behind; the earlier run at `b630c9d` found three failures, fixed in `3222fb9` and `db0d2c1`. ruff clean. Commands, commits and open points are in `.handoff/spec015/us1.handoff.md`.

**Checkpoint**: The MVP promise holds and is enforced.

---

## Phase 4: User Story 2 — Tell many voices from one voice (P2)

**Goal**: Distinct-author counts and concentration per mission and channel, unlinkable across missions.

**Independent Test**: Quickstart step 2, plus a two-mission integration fixture with a known author distribution.

- [x] T024 [P] [US2] Write failing integration tests in `tests/integration/test_author_concentration.py`. Cover:
  - 10 observations from 2 authors counted as 2;
  - the same authors in two missions sharing no marker;
  - unknown authors never merged;
  - `UNAVAILABLE` with its visible limitation when the encryption key is absent.
  - Done 21/10/2026 with T025 (`5ca096d`). RED observed for three of four (no `author_concentration` key; diversity stuck at its no-data default of 70); markers across missions were already disjoint from T015. Also covers the quality scorecard reading markers.
- [x] T025 [US2] Add `author_concentration` (`distinct_authors`, `unknown`, `unavailable`, `top_share`) per channel to `src/ignis/application/use_cases/get_mission_analysis.py` and its serializer in `src/ignis/interfaces/mcp/server.py`.
  - Done 21/10/2026 (`5ca096d`). Concentration is computed from every mission signal, grouped by platform; rows stored before 031 count as unknown. A visible `author_concentration_limitation` appears when any sighting is UNAVAILABLE. The MCP serializer passes the use-case result through unchanged. Addition beyond the task text: `creator_diversity_score` now reads markers, which closes the consumer gap T015 opened.
- [x] T026 [US2] Add a per-response `author_concentration` with an ephemeral, never-stored key to `get_tiktok_video_comments` and `extract_customer_pain_points` in `src/ignis/interfaces/mcp/server.py`.
  - Done 21/10/2026 (`175fe21`). RED observed (no `author_key` argument). The server makes a 32-byte key per call; the plugin marks commenters under it only when given one; the server aggregates and removes the markers before the response. No repository call stores the key.
- [x] T027 [US2] Call `destroy_mission_author_key` from `delete_mission_signals` in both repositories, but not from `prune_mission_evidence`. Test that markers of a deleted mission can no longer be recomputed in `tests/unit/test_mission_author_keys.py`.
  - Done 21/10/2026 (`8051148`). RED observed on SQLite. The key is deleted inside the same transaction as the evidence on both backends (rather than through a second call to `destroy_mission_author_key`), so a failure cannot leave one without the other. Parity on a disposable PostgreSQL: 8 passed.
- [x] T028 [US2] Extend the `ignis-analyze` skill text in `.agents/skills/ignis-analyze/SKILL.md` and its distributed copies. Explain how to read concentration as a seeding signal without implying who the authors are.
  - Done 21/10/2026 (`f450d1c`). RED observed in `tests/unit/test_ignis_skills.py`. The skill has no other distributed copy in the repository.

**Checkpoint**: US1 and US2 work independently.

---

## Phase 5: User Story 3 — Handles inside the content itself (P3)

**Goal**: Undeclared `@mentions` and handles in stored text become `@[user]`; declared mentions are kept as tokens and render by name.

**Independent Test**: Quickstart step 3 mention cases with Vietnamese fixtures.

- [x] T029 [P] [US3] Write failing tests in `tests/unit/test_mention_tokens.py`. Cover:
  - "@linh.nguyen mua ở đâu vậy" stored as "@[user] mua ở đâu vậy";
  - the declared `@brandx` kept as a token and rendered "@Brand X";
  - after withdrawal, the token rendered as "@[user]";
  - email and phone redaction unchanged.
  - Done 21/10/2026 with T030 (`743ea23`). RED: `ImportError` for `render_mention_tokens`.
- [x] T030 [US3] Apply tokenisation to titles, captions, excerpts and comments at the policy. Add declared-token rendering to the report builder in `src/ignis/infrastructure/templates/html/` and to the MCP serializers in `src/ignis/interfaces/mcp/server.py`. Add the helper to `src/ignis/infrastructure/security/pii_sanitizer.py`. Extend the T010 conformance scan to the `@mention` sentinels from T002.
  - Done 21/10/2026 (`743ea23`). Tokenisation covers the title and every metadata string except the requester's query keys (`PROBE_KEY_ALIASES`, `matched_keywords`, `query`), which also key Google sources. Rendering covers the report (through the `sanitize_pii` filter), `get_mission_analysis` titles and evidence batch titles and excerpts; citation JSON in `discover_market_opportunities` keeps the token, which names no person. The extended conformance scan failed on the pre-T030 source with three `@mention` leaks and passes now.

**Checkpoint**: US1–US3 work independently.

---

## Phase 6: User Story 4 — Know what older data already holds (P4)

**Goal**: A read-only count of author identity already stored, with no values shown and no writes.

**Independent Test**: Quickstart step 6 against a seeded fixture database.

- [x] T031 [P] [US4] Write failing tests in `tests/unit/test_inventory_author_identity.py`. Use a seeded SQLite fixture and check counts per table and field, that no identity value appears in the output, and that the file is unchanged after the run.
  - Done 21/10/2026 with T032 (`757845c`). RED observed for three of five tests (no script yet); the PostgreSQL case is `tests/integration/test_inventory_author_identity_postgres.py`.
- [x] T032 [US4] Implement `scripts/inventory_author_identity.py`. SQLite opens with `mode=ro`. PostgreSQL uses `SET TRANSACTION READ ONLY` with the DSN read from the environment variable named by `--database-url-env`, and the value is never printed. Output is JSON counts only.
  - Done 21/10/2026 (`757845c`). Counts per table and field: metadata rows holding author fields with the keys found, handle links, handle-derived source keys and `@mentions` in `observations`, `sources`, `trend_signals` and `topic_clusters`. A connection failure prints the error type only.
- [x] T033 [US4] Run the inventory on the local caller SQLite. If the DSN is present, also run it on the dev Supabase project under the owner's 02/10/2026 dev preauthorisation. Record the counts and anything not run in `.handoff/spec015/inventory.handoff.md`.
  - Done 21/10/2026 for the local stores; the dev Supabase run is not done. The caller store `.fnignis/canonical.sqlite3` holds 5 observations whose metadata carries `channel_id` and `channel_title`, and nothing else; the default `ignis.db` is empty. Both files hashed identically before and after. No DSN variable was set in the session environment, so Supabase was not inventoried. Details and the OG-3 options are in `.handoff/spec015/inventory.handoff.md`.
- [x] T034 [US4] OWNER GATE OG-3: present the inventory and the disposition options (keep, anonymise, delete), together with their effect on stored frame digests (research R10). Record the owner's decision in `specs/015-no-author-identity-at-rest/spec.md` Clarifications. Apply nothing in this feature without that decision and a pre-action manifest (FR-015).
  - Decided 22/10/2026: anonymise. Recorded in `spec.md` Clarifications, session 2026-10-22. The inventory was rerun that day: the caller store still holds 5 observations with `channel_id` and `channel_title` and nothing else, file hash unchanged. Dev Supabase was again not inventoried: the session sandbox refused the connection (OperationalError), and the classifier refused running it outside the sandbox.
- [x] T039 [US4] Failing tests, then `scripts/anonymise_author_identity.py`: dry run by default printing a manifest (target rows per table and field, affected missions, bound claims, account-derived source keys left as they are), `--apply` in one transaction followed by a readback. Reuses the collection policy through `ignis.application.author_policy`, so a compliant row is unchanged. SQLite and PostgreSQL.
  - Done 22/10/2026. RED observed (ImportError: no `strip_stored_identity`), then 5 SQLite tests in `tests/unit/test_anonymise_author_identity.py` and the PostgreSQL case `tests/integration/test_anonymise_author_identity_postgres.py` pass, the latter on a disposable TimescaleDB pg16 container. The policy function lives in `ignis.application.author_policy` beside the collection pass.
- [x] T040 [US4] Dry run, then apply, on the caller store; record the manifest and the readback in `.handoff/spec015/anonymise.handoff.md`.
  - Done 22/10/2026 for the caller store: the manifest listed 5 observations (field `metadata` only), 1 mission and 1 bound claim; apply read back 0 remaining targets and 5 rows changed, and the inventory afterwards counts 0 everywhere. File hash `525af7a6377b885b` before, `af32e7d2b2994c5c` after; integrity check ok. Dev Supabase is out of scope: the owner decided on 22/10/2026 not to inventory or anonymise it, since it is a development store and the script is tested on SQLite and PostgreSQL. Any legacy identity there stays at rest; the same commands apply if that changes.

---

## Phase 7: Polish & Cross-Cutting

- [x] T035 [P] Document what is and is not removed, including that free-text names are not removed (FR-012), and how to declare accounts. Update README.md, README.vi.md, docs/USER_GUIDE.md and docs/USER_GUIDE.vi.md. The Vietnamese files go through the vietnamizer workflow.
  - Done 21/10/2026 (`de83d02`). The Vietnamese text went through the vietnamizer workflow: Jev ran with partial coverage (19 patterns hit the request limit), and the core workflow decided four edits (V17 twice, V14, V18).
- [x] T036 [P] Draft a constitution amendment that adds a privacy principle ("no author identity at rest"), with its impact report and MINOR version bump, as `Proposed` for the owner in `.specify/memory/constitution.md`. Do not ratify it.
  - Done 21/10/2026 (`1b17ace`) as a Proposed section at the end of the constitution, with its impact report; the effective version stays 2.1.0.
  - Ratified by the owner 21/10/2026 as Principle VII of constitution 2.2.0.
- [x] T037 Run the quickstart steps, `.venv/bin/pytest tests/`, ruff, `git diff --check`, `uv lock --check`, the package build and `scripts/wheel_mcp_smoke.py`. Record the exact commands, revision, results and skips in `.handoff/spec015/regressions.handoff.md`.
  - Done 21/10/2026 at `1b17ace`. Full suite on SQLite: 4126 passed, 1008 skipped, 1 deselected. `tests/integration -k postgres` on a disposable TimescaleDB pg16 against an export of the same commit: 890 passed, 23 skipped, no database left behind. ruff on `src tests scripts` clean; `git diff --check` clean; `uv lock --check` exit 0; `uv build` produced the wheel and sdist; `scripts/wheel_mcp_smoke.py` against the installed wheel: 48 tools, a real tool call, the tracking guide and a clean exit. Quickstart steps 1-5 run inside the suite; step 6 ran as T033. Recorded in `.handoff/spec015/regressions.handoff.md`.
- [x] T038 Run a code and security review of the full diff, covering the auth, private-data and untrusted-input boundaries. Dispose of the findings with evidence before any PR. Opening, merging or pushing a PR needs the owner's explicit authority.
  - 21/10/2026, review findings 1-17 from the parent session's T038 review fixed test-first (each RED observed, PostgreSQL-only cases on a disposable container): `b79a86d` (1, 4, 8, 9, 17), `cd98d05` (2, 3, 6, 13), `1ba4813` (5, 7, 15, 16), `db8f49f` (10, 11), `7cf8241` (12, 14). At `7cf8241`: full suite on SQLite 4182 passed, 1020 skipped, 1 deselected; `tests/integration -k postgres` 901 passed, 23 skipped, 1 failed, no database left behind. The failure, `test_research_work_postgres_controls.py::test_postgres_admission_clock_after_observed_physical_wait[authority-mission-postgres]`, was the server closing the connection during a timing test while the SQLite suite ran alongside; the file passed 32/32 twice in isolation on a fresh container. The review itself stays with the parent session.
  - 21/10/2026, review: two read-only reviewers covered persistence, domain, crypto and SQL (key handling, injection, migration idempotency, backend parity) and the application, MCP, connector and report layers (responses, logs, receipts, escaping, mission scope). They reported 17 findings, every one disposed of above; no XSS, SQL injection or key-handling defect was found. The parent session re-ran the original reproductions at `80486e5`: handle links (Unicode, percent-encoded, full-width, scheme-less, Instagram stories), Unicode and glued mentions, forged declared tokens, tuples and in-text profile links are all removed, while e-mail addresses and content links stay. The owner authorised pushing and merging spec PRs on 21/10/2026.

---

## Dependencies & Execution Order

- **Setup (T001–T002)**: T001 gates everything because it fixes the migration number and the tool count. T002 can start at once.
- **Foundational (T003–T009)**: depends on T001. T003 and T004 run in parallel, then T005; T006 then T007; T008 and T009 follow T006.
- **US1 (T010–T023)**: depends on Phase 2. The tests T010–T012 come first. T013 precedes T015. T021 precedes T022. T023 closes the phase.
- **US2 (T024–T028)**: depends on Phase 2 and T015; independent of the US1 report changes.
- **US3 (T029–T030)**: depends on T005 and, for declared tokens, T021.
- **US4 (T031–T034)**: depends only on T006, so it can run in parallel with US1–US3.
- **Polish (T035–T038)**: after the stories in scope.

## Parallel Opportunities

- T002 alongside T001's waiting period.
- T003 and T004.
- T011 and T012 alongside T010.
- T017 alongside T013–T016.
- US4 (T031–T033) alongside US1 after T006.
- T035 and T036.

## Implementation Strategy

1. **MVP**: Phases 1–3. The invariant is enforced across every connector, with declared accounts. Stop and validate quickstart steps 1, 4 and 5.
2. Add US2 (concentration), then US3 (mention tokens). Each is validated independently.
3. US4 can ship in parallel, since it is read-only. Its OG-3 disposition is a separate owner decision.
4. Polish, full regression and review last. No push, PR or merge without owner authority.
