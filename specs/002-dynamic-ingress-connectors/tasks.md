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

- [x] T018 [RELEASE BLOCKER] Add a versioned migration that enables RLS on every current table in
  the exposed `public` schema, including tables created after `006`, and define the intended policy
  for each table. Prove with `anon` and `authenticated` that source, observation, workspace,
  configuration, evidence, credential, and journal data cannot be read or mutated unless an
  explicit policy permits it; preserve owner/runtime access and plain TimescaleDB portability
  (depends-on: T017). `sql/021_public_schema_rls_coverage.sql` enables RLS on all 17 public tables
  the chain creates and declares two classes: `market_lexicons` and `industry_taxonomies` stay
  client read-only through the `006` policies, and the other 15 tables are owner only, with every
  `anon`/`authenticated` table and owned-sequence privilege revoked. The revoke is required, not
  decorative: RLS does not govern TRUNCATE, which both roles held on all 17 tables, and TimescaleDB
  chunks of `trend_signals` carry no RLS flag while inheriting the hypertable's grants. Verified on
  a fresh Supabase-like database, on one migrated through `020` before `021` (152 client statements
  succeeded before, none after), on plain TimescaleDB without the roles, by re-applying `021` and
  the whole chain, as a non-superuser table owner through the real repository, and by two fresh
  Compose inits running all 21 files. The catalog check fails when one post-`006` table loses RLS
  or gains a client grant. Tables are listed rather than discovered, so another application's
  tables in a shared database are left as they are; a database initialised before `021` must
  apply it once as the table owner.
- [x] T019 Run `tests/integration/test_compose_init.py` as a dedicated Docker CI job with
  `IGNIS_TEST_COMPOSE_INIT=1`, keeping the exact production image and full `sql/` mount. Require the
  stable job on protected branches so a later migration cannot break fresh initialization while
  the ordinary integration suite remains green (depends-on: T017). `.github/workflows/compose-init.yml`
  (workflow `Compose Init`, job `compose-fresh-init`, check name `Fresh Compose database init`)
  runs on every unfiltered pull request, on pushes to `main`, `release/*` and `hotfix/*`, and on
  manual dispatch, on `ubuntu-24.04` with read-only permissions, a 30-minute timeout and one run
  per ref. It installs `uv.lock` with `--locked`, sets the opt-in on the contract step only, and
  fails a run whose JUnit report shows no executed test or any skip, because pytest exits 0 when
  Docker is missing and the test skips itself. The workflow restates no image, mount, DSN or
  migration list. `tests/unit/test_t019_compose_init_workflow.py` pins all of this in 21 contracts;
  renaming the job, removing the opt-in, or removing the skip check each fails them. Verified
  locally by the real two-init contract and, in a clean worktree without `.env`, by the workflow's
  own install, contract and skip-check commands. Branch protection is not part of this commit:
  the check becomes required only once Codex applies the GitHub setting after the first remote
  run and reads it back.

## Phase 9: Convergence (2026-09-24)

- [x] T020 [RELEASE BLOCKER] Remove Ignis' runtime dependency on EXECUTE for
  `public.uuid_generate_v4()` without weakening the function posture established by `006`. First
  add a PostgreSQL RED contract proving that a non-superuser, non-`BYPASSRLS` runtime role which
  owns the Ignis tables cannot insert a row whose id is omitted after the current full migration
  chain unless the test grants function execution out of band. Then add an idempotent versioned
  migration that changes every Ignis UUID primary-key default still using `uuid_generate_v4()` to
  PostgreSQL's built-in `gen_random_uuid()`; do not grant EXECUTE on all functions, move or drop
  `uuid-ossp`, create roles, or alter SQLite behavior. Prove both a fresh `001`-through-newest
  install and an upgrade from `021`: all affected defaults are canonical, re-application is a
  no-op, the real repository can write every affected table class as that runtime owner with no
  fixture-only function grant, and `PUBLIC`, `anon`, and `authenticated` still cannot execute the
  protected public RPC probe or mutate owner-only tables. Extend the Compose/init and package
  contracts so the new migration cannot be skipped, but do not apply it to a dev or production
  database in this task. Record the measured RED/GREEN evidence and close the matching backlog
  item only after PostgreSQL and fresh-Compose gates pass (touches: `sql/`,
  `tests/integration/test_postgres_migration_contract.py`,
  `tests/integration/test_postgres_rls_coverage.py`, `tests/integration/test_compose_init.py`,
  migration packaging/convention tests, `BACKLOG.md`; depends-on: T018, T019; source:
  Constitution VI, the T018 runtime-owner fixture, and the open pre-release hardening item in
  `BACKLOG.md`). `sql/022_builtin_uuid_defaults.sql` sets the id default of the nine tables a `021`
  catalog shows calling `uuid_generate_v4()` -- `research_missions`, `topic_clusters`, `sources`,
  `observations`, `mission_evidence`, `research_workspaces`, `market_brief_revisions`,
  `mission_run_journals`, `source_identity_aliases` -- to `gen_random_uuid()` through explicit
  `ALTER TABLE` statements; it grants nothing and leaves `uuid-ossp` installed in `public`. The
  runtime-owner fixture no longer grants EXECUTE on public functions. RED, before `022`: as a
  non-superuser, non-`BYPASSRLS` owner, all nine defaulted inserts failed with `permission denied
  for function uuid_generate_v4`, and the real repository failed recording observations for the
  same reason. GREEN on PostgreSQL 16.14 (`timescale/timescaledb-ha:pg16`, TimescaleDB 2.29.2):
  a fresh `001`-`022` install defaults all 11 UUID keys to `gen_random_uuid()` with no default
  depending on `uuid-ossp`; a `021` install denies all nine inserts until `022` is applied as the
  table owner, then accepts them while the owner still cannot execute `uuid_generate_v4()`;
  re-applying `022` and the whole chain leaves defaults, `uuid-ossp` ACLs and the `006` state
  unchanged; `PUBLIC`, `anon` and `authenticated` still cannot execute the RPC probe or write
  owner-only tables. Omitting the `mission_run_journals` statement fails the catalog, fresh-insert
  and upgrade contracts. Full integration suite with PostgreSQL: 487 passed, 3 skipped (the Compose
  opt-in and two SQLite legs of Postgres-only tests); fresh Compose init ran all 22 files. Not
  applied to any dev or production database; an installation initialised before `022` applies it
  once as the table owner.

## Phase 10: CI Runtime Pinning (2026-09-25)

- [x] T021 Pin the GitHub-hosted runners used by CI and Docker Publish to `ubuntu-24.04`, and
  replace every remaining `astral-sh/setup-uv@v3` use with the reviewed immutable action SHA and uv
  binary version already used by Compose Init. Preserve workflow names, job names, triggers,
  permissions, Python matrix entries, PostgreSQL services, benchmark arguments, Docker image/tag
  semantics, and required-check identities. Add static workflow contracts that fail if the
  deprecated action tag or moving runner returns. Verify locally; remote execution remains
  unverified until Codex opens the PR (touches: `.github/workflows/ci.yml`,
  `.github/workflows/performance.yml`, `.github/workflows/docker-publish.yml`,
  `tests/unit/test_t021_ci_runtime_pinning.py`, `BACKLOG.md`; source: GitHub Actions warnings on
  the v0.5.0 release runs). `Secret scan`, the Python test matrix and Docker Publish moved from
  `ubuntu-latest` to `ubuntu-24.04`; CI and Performance moved from `astral-sh/setup-uv@v3` with
  `version: "latest"` to `astral-sh/setup-uv@c18668ad3cf93ea998bef934396af7bb5c839dc7 # v10.2.0`
  with uv `0.12.17`, the Compose Init pin, which is unchanged. The diff is those seven lines.
  `tests/unit/test_t021_ci_runtime_pinning.py` holds 13 contracts: 7 failed before the change and
  all 13 pass after it; restoring one `ubuntu-latest` runner, one `@v3` tag, or one `latest` uv
  version each fails the intended assertions. Unit suite 1071 passed, 2 skipped; actionlint 1.7.7
  reports only the pre-existing SC2012 info at `ci.yml:119`. Remote GitHub execution is not
  verified because this task does not push.

## Phase 11: SC-001 Gate on Plan-Level Pull Requests (2026-09-25)

- [x] T022 Run the Performance workflow on every `pull_request`, so the `SC-001 get_top_clusters
  P95` check reports on the plan-level pull request and can then be selected as a required status
  check. Pull requests are opened only at the end of a plan, not per task, so the benchmark's cost
  is paid once per plan integration and is accepted; no merge queue, manual-dispatch workaround or
  relaxed threshold. The trigger carries no `branches`, `branches-ignore`, `paths` or
  `paths-ignore` filter, because a required check that a filter skips never reports and the pull
  request waits forever. Keep the existing push triggers for `main`, `release/*` and `hotfix/*`,
  the weekly schedule and `workflow_dispatch`; keep job id `sc001-read-path-p95` and job name
  `SC-001 get_top_clusters P95`; keep the benchmark contract, both `--enforce` invocations, the
  PostgreSQL service and `IGNIS_TEST_POSTGRES_DSN`, `ubuntu-24.04`, the T021 setup-uv SHA and uv
  `0.12.17`, read-only permissions, concurrency and the 30-minute timeout. Replace the T024
  contract that forbade `pull_request` with contracts that require it unfiltered, and pin the rest
  (touches: `.github/workflows/performance.yml`, `tests/unit/test_t024_performance_workflow.py`,
  `BACKLOG.md`, `specs/001-core-storage-stable-ingress/tasks.md`, this file; depends-on: T021).
  Repository-side work can complete in one commit. Remote execution is not proven until the first
  plan-level pull request runs the check, and the check is not required until Codex changes branch
  protection and reads the setting back; this commit claims neither.
  Repository side complete: `performance.yml` gains a bare `pull_request:` trigger and two comment
  updates; nothing else in the file changes. `test_the_gate_is_not_attached_to_every_pull_request`
  is replaced, and the file now holds 31 contracts, up from 19: `pull_request` present, no branch
  filter, no path filter, default activity types, no `pull_request_target`, exact push/schedule/
  dispatch triggers, job id, literal T021 runner/setup-uv SHA/uv version, a single DSN reachable
  only through `IGNIS_TEST_POSTGRES_DSN`, no job-level permissions override, exact concurrency and a
  30-minute timeout. RED before the workflow edit: 5 failed, 26 passed, all 5 on the missing
  `pull_request`. GREEN after: 31 passed. Negative controls, each restored to a matching SHA-256:
  removing `pull_request` fails 5; adding `paths`, `paths-ignore`, `branches`, `branches-ignore` or
  `types` fails the matching contract; renaming the job fails the T024 name contract and the T021
  identity contract. Unit suite 1083 passed, 2 skipped; workflow contracts 82 passed; Ruff clean;
  `uv lock --check` clean. actionlint 1.7.7 exits 1 on all four workflows because of the
  pre-existing SC2012 info at `ci.yml:119`, with output byte-identical to `bfa6004`. GitHub Actions
  has not run this workflow on a pull request, and branch protection is unchanged.

## Phase 12: Upload Artifact Node.js 24 Runtime (2026-09-25)

- [x] T023 Replace the Performance workflow's only `actions/upload-artifact@v4` consumer, which
  GitHub runs under a deprecated Node.js 20 compatibility path, with the immutable commit for
  `actions/upload-artifact` v7.0.1 (`043fb46d1a93c77aae656e7c1c64a875d1fc6a0a`), whose action
  runtime is Node.js 24. Preserve the artifact name, path, retention, missing-file policy,
  conditions, job identity, triggers and benchmark contract. Add source-level contracts that pin
  both the full commit and its release comment; prove they fail on `@v4` and the moving `@v7` tag.
  Complete the task only after a GitHub-hosted pull-request run succeeds, uploads the benchmark
  artifact, and contains no Node.js 20 warning attributed to `actions/upload-artifact` (touches:
  `.github/workflows/performance.yml`, `tests/unit/test_t021_ci_runtime_pinning.py`, `BACKLOG.md`,
  this file; depends-on: T021, T022). The pull-request Performance run `36086256496` succeeded on
  GitHub-hosted `ubuntu-24.04`, downloaded the exact pinned commit, and completed the upload step.
  Artifact `sc001-benchmark-36086256496` (ID `10844150733`, 886 bytes) contained passing SQLite
  and PostgreSQL records at P95 25.550 ms and 18.526 ms against the unchanged 50 ms threshold.
  The check emitted no annotations, and its complete log contained no Node.js 20 deprecation or
  compatibility warning. Local RED on `@v4`: 2 failed and 13 passed; GREEN on the pin: 16 passed;
  moving-tag negative control on `@v7`: 2 failed and 13 passed. Unit suite: 1086 passed and 2
  skipped with the shell's `YOUTUBE_API_KEY` removed from the test process; Ruff, `uv lock
  --check`, and `git diff --check` passed. actionlint 1.7.7 still reports only the pre-existing
  SC2012 info at `ci.yml:119`.
