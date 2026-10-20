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

- [ ] T001 Wait for PR #51 to merge (OG-2 approved 2026-10-20: Spec 015 lands after Spec 014), then rebase `codex/no-author-identity-at-rest` on `main`. Record in `specs/015-no-author-identity-at-rest/plan.md` the base commit, the latest migration (expected `030`) and the tool count (expected 47). If either differs, stop and report before T006.
- [ ] T002 [P] Create sentinel identity fixtures in `tests/fixtures/author_identity_sentinels.py`. Cover one recognisable value per author field from research R2, per platform. Add handle-bearing URLs for TikTok and Threads, `@mention` text with Vietnamese diacritics, and one operator self-account.

---

## Phase 2: Foundational (blocks every user story)

**Purpose**: Domain policy, marker, schema, key storage and the repository guard.

- [ ] T003 [P] Write failing unit tests for field stripping in `tests/unit/test_author_identity_policy.py`. Cover every key in research R2, nested comment authors, `video_url` handles, and confirm that non-author metadata is preserved unchanged.
- [ ] T004 [P] Write failing unit tests for markers in `tests/unit/test_author_marker.py`:
  - the marker is stable within one mission and differs across missions;
  - ten thousand distinct authors are counted exactly;
  - a missing author gives `UNKNOWN`;
  - a missing encryption key gives `UNAVAILABLE`.
- [ ] T005 Implement `src/ignis/domain/author_identity.py`. It holds:
  - the author field list, reusing the key lists in `src/ignis/domain/self_content.py`;
  - `strip_author_identity`;
  - the HMAC-SHA256 marker truncated to 16 hex characters;
  - `@mention` tokenisation (`@[user]`, `@[declared:<id>]`), whose regex is commented as the character-class exception;
  - `AuthorConcentration`.

  T003 and T004 must pass.
- [ ] T006 Write `sql/031_author_identity_at_rest.sql` per data-model.md. It covers:
  - the tables `mission_author_keys` and `mission_declared_accounts`;
  - the `mission_evidence` columns `author_state`, `author_marker` and `declared_account_id`;
  - the `identity_source` CHECK extended with `unverifiable_content`.

  Mirror the DDL and the rebuild-table upgrade in `src/ignis/infrastructure/persistence/sqlite_repository.py` (`_ensure_schema`).
- [ ] T007 Update the pinned latest-migration surfaces for `031`: `tests/unit/test_sql_packaging.py`, `tests/integration/conftest.py` and `tests/unit/test_public_distribution_contract.py`. Add a SQLite upgrade rehearsal test in `tests/unit/test_author_identity_schema.py`, covering a pre-031 database upgraded in place with counts unchanged.
- [ ] T008 Add repository methods `get_or_create_mission_author_key` and `destroy_mission_author_key` to `src/ignis/infrastructure/persistence/sqlite_repository.py` and `postgres_repository.py`. Fernet comes from `src/ignis/infrastructure/auth/crypto.py`. Test in `tests/unit/test_mission_author_keys.py` that the key is never returned decrypted to any caller other than the policy.
- [ ] T009 Add a fail-closed guard in `_record_observations` of both repositories. It refuses a signal whose metadata holds an author key, or whose `source_url` or `external_id` holds a handle or profile segment. Test the refusal in `tests/unit/test_author_identity_guard.py`.

**Checkpoint**: The policy, schema, keys and guard exist; no caller uses them yet.

---

## Phase 3: User Story 1 — Research without keeping who said it (P1) 🎯 MVP

**Goal**: No author identity in any durable store, response, report or log, except declared accounts.

**Independent Test**: The sentinel mission in quickstart step 1 leaves zero undeclared sentinel values anywhere, and still produces observations and claims.

### Tests for User Story 1

- [ ] T010 [US1] Write the failing conformance test in `tests/integration/test_author_identity_conformance.py`. It uses the dual-backend fixture with fake connectors, built from T002, for every registered connector and for host browser submissions, and scans:
  - all tables;
  - research-folder files;
  - generated report HTML;
  - MCP responses;
  - captured logs.

  Include a registry-coverage test that fails when a registered connector has no fixture, and a leaking negative-control connector that must fail (SC-001, SC-007). This phase scans author fields and URLs; `@mention` sentinels in text join the scan in T030.
- [ ] T011 [P] [US1] Write the failing parity test in `tests/integration/test_author_identity_parity.py`. An existing mission fixture must produce the same claims, permissions and Gap Report outcome with the policy on (SC-008).
- [ ] T012 [P] [US1] Write failing unverifiable-source tests in `tests/unit/test_unverifiable_source.py`. Cover the observation being kept with `unverifiable_content`, its forced `CONTEXT_ONLY` qualification, and the SUPPORT binding refused by both claim triggers (SC-010).

### Implementation for User Story 1

- [ ] T013 [US1] In `src/ignis/domain/source_identity.py`, refuse the handle or profile URL fallback, add the `unverifiable_content` identity (`content:<sha256>`), and add the identity-free canonical link builder for YouTube and Reels. Extend `tests/unit/test_source_identity.py`.
- [ ] T014 [US1] Probe live public pages, without a signed-in session, for handle-free TikTok and Threads content links. Record the outcome in `specs/015-no-author-identity-at-rest/research.md` R5. Add a platform to the link builder only when the probe proves the form opens the content; otherwise keep "link unavailable".
- [ ] T015 [US1] In `src/ignis/application/use_cases/execute_mission.py` (`_execute_pass`), apply the policy before `save_clusters` and `save_signals`, and write `author_state`, `author_marker` and `declared_account_id` on `mission_evidence` in both repositories.
- [ ] T016 [US1] In `src/ignis/application/use_cases/host_browser_mission.py`, apply `partition_self_authored` before the policy. Keep validator acceptance of handle URLs in `src/ignis/infrastructure/connectors/host_browser/validator.py` and drop the handle at the policy. Extend `tests/unit/test_self_content_scope.py`.
- [ ] T017 [P] [US1] In `src/ignis/infrastructure/connectors/tiktok/tiktok_plugin.py`, remove the fixed-salt comment pseudonymisation and the handle-bearing log line. In `src/ignis/infrastructure/connectors/threads/threads_plugin.py`, remove the operator username from the log line.
- [ ] T018 [US1] Apply forced `CONTEXT_ONLY` for unverifiable content in `src/ignis/domain/research_workspace.py`. Add the SUPPORT refusal to the SQLite trigger in `sqlite_repository.py` and to the PostgreSQL trigger in `sql/031_author_identity_at_rest.sql`. T012 must pass.
- [ ] T019 [US1] Make citations identity-free in `src/ignis/infrastructure/harness/strategic_reasoner.py` and `src/ignis/domain/harness_models.py`, setting `author_or_channel` only for declared accounts. In `src/ignis/infrastructure/templates/html/mission_report.html`, render a declared name or nothing, and a link or "link unavailable".
- [ ] T020 [US1] Update the MCP response shapes in `src/ignis/interfaces/mcp/server.py` and `src/ignis/application/use_cases/get_mission_analysis.py`, `get_evidence_qualification_batch.py`, per `contracts/mcp-surface.md`. Remove `top_creators`, the comment `author`/`author_id`, `inquiries[].author` and handle-bearing URLs, and add `source_verifiable`.
- [ ] T021 [US1] Write a failing test, then implement the approved tool `set_mission_declared_accounts` (OG-1). The test is `tests/integration/test_declared_accounts.py`. The repository methods for `mission_declared_accounts` go in both repositories, and the tool in `src/ignis/interfaces/mcp/server.py`. Follow the contract's normalisation, duplicate refusal, mission-scope refusal and replace-set semantics, with declarations applying only to content collected after `declared_at` (SC-009).
- [ ] T022 [US1] Raise every governed tool-count surface by one. Regenerate the Hermes manifests with `scripts/sync_tool_manifests.py --write`. Update the contract, drift, distribution and doc-convention tests, `scripts/wheel_mcp_smoke.py` expectations, README.md, README.vi.md, CLAUDE.md, AGENTS.md, openclaw.json, BACKLOG.md and `.github/workflows/ci.yml`. `tests/unit/test_public_distribution_contract.py` and `tests/unit/test_tool_manifests_drift.py` must pass.
- [ ] T023 [US1] Run T010 and T011 to green on SQLite, plus PostgreSQL when `IGNIS_TEST_POSTGRES_DSN` is present. Record the commands, revision and skips in `.handoff/spec015/us1.handoff.md`.

**Checkpoint**: The MVP promise holds and is enforced.

---

## Phase 4: User Story 2 — Tell many voices from one voice (P2)

**Goal**: Distinct-author counts and concentration per mission and channel, unlinkable across missions.

**Independent Test**: Quickstart step 2, plus a two-mission integration fixture with a known author distribution.

- [ ] T024 [P] [US2] Write failing integration tests in `tests/integration/test_author_concentration.py`. Cover:
  - 10 observations from 2 authors counted as 2;
  - the same authors in two missions sharing no marker;
  - unknown authors never merged;
  - `UNAVAILABLE` with its visible limitation when the encryption key is absent.
- [ ] T025 [US2] Add `author_concentration` (`distinct_authors`, `unknown`, `unavailable`, `top_share`) per channel to `src/ignis/application/use_cases/get_mission_analysis.py` and its serializer in `src/ignis/interfaces/mcp/server.py`.
- [ ] T026 [US2] Add a per-response `author_concentration` with an ephemeral, never-stored key to `get_tiktok_video_comments` and `extract_customer_pain_points` in `src/ignis/interfaces/mcp/server.py`.
- [ ] T027 [US2] Call `destroy_mission_author_key` from `delete_mission_signals` in both repositories, but not from `prune_mission_evidence`. Test that markers of a deleted mission can no longer be recomputed in `tests/unit/test_mission_author_keys.py`.
- [ ] T028 [US2] Extend the `ignis-analyze` skill text in `.agents/skills/ignis-analyze/SKILL.md` and its distributed copies. Explain how to read concentration as a seeding signal without implying who the authors are.

**Checkpoint**: US1 and US2 work independently.

---

## Phase 5: User Story 3 — Handles inside the content itself (P3)

**Goal**: Undeclared `@mentions` and handles in stored text become `@[user]`; declared mentions are kept as tokens and render by name.

**Independent Test**: Quickstart step 3 mention cases with Vietnamese fixtures.

- [ ] T029 [P] [US3] Write failing tests in `tests/unit/test_mention_tokens.py`. Cover:
  - "@linh.nguyen mua ở đâu vậy" stored as "@[user] mua ở đâu vậy";
  - the declared `@brandx` kept as a token and rendered "@Brand X";
  - after withdrawal, the token rendered as "@[user]";
  - email and phone redaction unchanged.
- [ ] T030 [US3] Apply tokenisation to titles, captions, excerpts and comments at the policy. Add declared-token rendering to the report builder in `src/ignis/infrastructure/templates/html/` and to the MCP serializers in `src/ignis/interfaces/mcp/server.py`. Add the helper to `src/ignis/infrastructure/security/pii_sanitizer.py`. Extend the T010 conformance scan to the `@mention` sentinels from T002.

**Checkpoint**: US1–US3 work independently.

---

## Phase 6: User Story 4 — Know what older data already holds (P4)

**Goal**: A read-only count of author identity already stored, with no values shown and no writes.

**Independent Test**: Quickstart step 6 against a seeded fixture database.

- [ ] T031 [P] [US4] Write failing tests in `tests/unit/test_inventory_author_identity.py`. Use a seeded SQLite fixture and check counts per table and field, that no identity value appears in the output, and that the file is unchanged after the run.
- [ ] T032 [US4] Implement `scripts/inventory_author_identity.py`. SQLite opens with `mode=ro`. PostgreSQL uses `SET TRANSACTION READ ONLY` with the DSN read from the environment variable named by `--database-url-env`, and the value is never printed. Output is JSON counts only.
- [ ] T033 [US4] Run the inventory on the local caller SQLite. If the DSN is present, also run it on the dev Supabase project under the owner's 02/10/2026 dev preauthorisation. Record the counts and anything not run in `.handoff/spec015/inventory.handoff.md`.
- [ ] T034 [US4] OWNER GATE OG-3: present the inventory and the disposition options (keep, anonymise, delete), together with their effect on stored frame digests (research R10). Record the owner's decision in `specs/015-no-author-identity-at-rest/spec.md` Clarifications. Apply nothing in this feature without that decision and a pre-action manifest (FR-015).

---

## Phase 7: Polish & Cross-Cutting

- [ ] T035 [P] Document what is and is not removed, including that free-text names are not removed (FR-012), and how to declare accounts. Update README.md, README.vi.md, docs/USER_GUIDE.md and docs/USER_GUIDE.vi.md. The Vietnamese files go through the vietnamizer workflow.
- [ ] T036 [P] Draft a constitution amendment that adds a privacy principle ("no author identity at rest"), with its impact report and MINOR version bump, as `Proposed` for the owner in `.specify/memory/constitution.md`. Do not ratify it.
- [ ] T037 Run the quickstart steps, `.venv/bin/pytest tests/`, ruff, `git diff --check`, `uv lock --check`, the package build and `scripts/wheel_mcp_smoke.py`. Record the exact commands, revision, results and skips in `.handoff/spec015/regressions.handoff.md`.
- [ ] T038 Run a code and security review of the full diff, covering the auth, private-data and untrusted-input boundaries. Dispose of the findings with evidence before any PR. Opening, merging or pushing a PR needs the owner's explicit authority.

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
