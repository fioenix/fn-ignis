# Tasks: Dynamic Ingress Connectors

## Phase 1: TikTok Plugin
- [x] T001 [P] Viết unit tests cho `TikTokPlugin` trong `tests/unit/test_tiktok_plugin.py`
- [x] T002 Cài đặt `TikTokPlugin` trong `src/ignis/infrastructure/connectors/tiktok/tiktok_plugin.py`

## Phase 2: Threads Plugin
- [x] T003 [P] Viết unit tests cho `ThreadsPlugin` trong `tests/unit/test_threads_plugin.py`
- [x] T004 Cài đặt `ThreadsPlugin` trong `src/ignis/infrastructure/connectors/threads/threads_plugin.py`

## Phase 3: Instagram Reels Plugin
- [x] T005 [P] Viết unit tests cho `ReelsPlugin` trong `tests/unit/test_reels_plugin.py`
- [x] T006 Cài đặt `ReelsPlugin` trong `src/ignis/infrastructure/connectors/reels/reels_plugin.py`

## Phase 4: Integration & Registry Update
- [x] T007 Cập nhật integration tests và đăng ký 3 plugins vào `tests/integration/test_all_connectors.py`

## Phase 5: As-Built Identity Contract (2026-09-13)

- [x] T008 Route connector sightings through the shared platform-object identity resolver
- [x] T009 Converge TikTok tag/video and Google keyword identities across metadata and URL routes
- [x] T010 Reconcile Threads/Reels numeric primary keys with permalink shortcodes through a
  persisted alias ledger. Every Threads and Reels emission path already carries both values on one
  record, so `resolve_identity_alias` registers the relationship that record witnesses, and a later
  permalink-only sighting resolves through `source_identity_aliases` (sql/018) instead of filing a
  second row. String equality between the two namespaces still proves nothing, a conflicting claim
  on one shortcode is logged rather than merged, and `observations.identity_source` is unchanged.
  Verified on SQLite; the PostgreSQL half of the dual-backend contract is implemented but was not
  executed -- `IGNIS_TEST_POSTGRES_DSN` was unset, so those 12 cases skipped.

## Phase 6: Credential Lifecycle Contract (2026-09-14)

- [x] T011 Make `delete_platform_credentials` erase the stored row on both backends. PostgreSQL had
  been running `UPDATE ... SET is_active = FALSE` while SQLite deleted, so the same method name
  meant two different things and the encrypted payload survived a clear on one of them.
- [x] T012 Add dual-backend erasure contracts that query `platform_credentials` directly, rather
  than trusting a reader that filters on the active flag
- [x] T013 Remove the upstream-revocation claim from both clear handlers, both FastMCP tool
  descriptions, the repository port docstring, and the public documentation; direct operators to
  the provider's security settings instead
- [x] T014 Gate the wording with contracts that permit a denial and an instruction to revoke at the
  provider, and fail only an affirmative claim that Ignis revoked something
- [ ] T015 [FUTURE — OUT OF CURRENT SPEC SCOPE] Implement an actual provider-side revocation
  request, behaviourally tested, before any surface is allowed to claim revocation. FR-010
  currently defines local deletion plus provider instructions as the supported contract.

## Phase 7: Corpus Correctness Follow-up (2026-09-24)

- [x] T016 Remove the ambiguous `live`, `thông báo`, and `tin nhắn` rows from the
  `tiktok_ui_noise` runtime vocabulary through an idempotent versioned SQL migration so both fresh
  and existing SQLite/PostgreSQL installations preserve public TikTok posts containing those
  ordinary words; keep `đang phát trực tiếp` and the remaining notification/inbox phrases, prove
  the three removed rows do not return after restart or migration re-apply, and keep vocabulary in
  SQL rather than Python (touches: `sql/`, SQLite schema/seed registration, PostgreSQL migration
  registration, `tests/unit/test_vocabulary_loader.py`, repository migration-contract tests;
  depends-on: T014). Verified through the SQLite bootstrap and a fresh portable PostgreSQL
  migration contract; the documented full-directory Docker init path remains T017.
- [x] T017 Make a fresh `docker-compose.prod.yml` database execute the complete mounted `sql/`
  sequence through `020` on `timescale/timescaledb-ha:pg16`: preserve the Supabase RLS policies
  when roles `authenticated` and `anon` exist, avoid failing on plain TimescaleDB when they do not,
  prove the actual container init exits cleanly with the final schema and retired vocabulary, and
  keep the public Docker instructions aligned with that verified path (touches:
  `sql/006_supabase_security_hardening.sql`, Docker init contract tests, `README.md`,
  `README.vi.md`, `docs/USER_GUIDE.md`, `docs/USER_GUIDE.vi.md`; depends-on: T016). Verified with
  two fresh Compose initializations, the complete filename-ordered `001`-`020` sequence, and
  separate plain-TimescaleDB and Supabase-role contracts.

## Phase 8: PostgreSQL Security and Init Regression Gates (2026-09-24)

- [ ] T018 [RELEASE BLOCKER] Add a versioned migration that enables RLS on every current table in
  the exposed `public` schema, including tables created after `006`, and define the intended policy
  for each table. Prove with `anon` and `authenticated` that source, observation, workspace,
  configuration, evidence, credential, and journal data cannot be read or mutated unless an
  explicit policy permits it; preserve owner/runtime access and plain TimescaleDB portability
  (depends-on: T017).
- [ ] T019 Run `tests/integration/test_compose_init.py` as a dedicated Docker CI job with
  `IGNIS_TEST_COMPOSE_INIT=1`, keeping the exact production image and full `sql/` mount. Require the
  stable job on protected branches so a later migration cannot break fresh initialization while
  the ordinary integration suite remains green (depends-on: T017).
