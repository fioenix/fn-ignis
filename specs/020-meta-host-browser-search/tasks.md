---

description: "Task list for Spec 020: Threads Through the Host Browser, Without Evasion Flags"
---

# Tasks: Threads Through the Host Browser, Without Evasion Flags

**Input**: Design documents from `/specs/020-meta-host-browser-search/`

**Prerequisites**: plan.md (especially **Owner decision (27/10/2026)**), spec.md, research.md,
data-model.md, contracts/mcp-surface.md, contracts/threads-search.md, quickstart.md, g2-surfaces.md;
constitution 2.3.0. The accepted plan selects tasks then implementation under the Spec Kit depth gate.

**Authority and precedence**: The owner's decision overrides the older proposals and API passages
in the remaining artifacts. OG-1/3/4/5 are approved; OG-2 retains only TikTok/Threads host-ticket
composition with a spike first. This ledger creates work; it does not execute it or authorize live
accounts, live-store migration, release, version bump, commit, routine or agent-context changes.

**Tests**: Included as requested. Author each new/changed behavior test and observe its failure
against the pre-change implementation before changing the corresponding production code. Record
RED command/output and later GREEN in `.handoff/spec020-verification.md`; a missing test runner,
fixture or dependency is not behavioral RED. Existing passing characterization checks establish
parity, not a new RED. Every task starts unchecked; no prior planning check completes these tasks.

**Organization**: Setup → blocking spike/foundation → US1 (including cross-cutting FR-006) → US2 →
final verification and approval-blocked live checks. Removal starts only after the US1 automated
host-path checkpoint; real-account readiness remains separately gated at the end.

## Format: `[ID] [P?] [Story] Description`

- **[P]** means independent files within the stated test batch after its prerequisites; no implicit
  delegation, simultaneous writers to shared files or permission to skip the spike/checkpoints.
- **[US1]**, **[US2]** map to spec stories. Setup/foundation/final tasks have no story label.
- Exact paths are relative to this checkout. New test basenames must be unique across unit/integration.

## Rules every task follows

- Work only in this checkout on `claude/meta-host-browser-spec`; preserve unrelated changes and
  accepted spec Clarifications. No rebasing, new worktree or commit is part of this ledger.
- Keep default TikTok behavior, submit/cancel signatures and **53 tools**. Only prepare gains optional
  `source` (`tiktok` default). No tool-count bump or count-only catalog edits.
- No author identity in receipts, stored metadata, responses, reports, journals or logs. Use Spec 015
  content references/identity-free links; vocabulary in SQL, not Python. Synthetic author fixtures
  only; free-text personal-name limitation remains documented.
- SQLite/PostgreSQL parity is required; migration 036 seeds vocabulary only, never schema/evidence
  transformation. Use disposable fixtures with approved injected DSN, never read `.env`/credentials.
- No fallback collector, replacement evasion, model-generated records, cookie export, CDP, private
  UI, Instagram extractor, unbounded scrolling or scheduler. No G3 routine change (FR-009).
- Use `PYTHONPATH="$PWD/src" /Users/fioenix/Projects/fn-ignis/.venv/bin/pytest -q -p no:cacheprovider <files>`
  for source checks; select changed code and traced consumers only. No full-suite run. For wheel
  checks isolate the installed wheel from checkout imports; do not change the shared venv.
- Skip updates under `.agents/`, `AGENTS.md`, `CLAUDE.md` and equivalent context/mirror files. Record
  any resulting mirror-check limitation instead of modifying excluded files or weakening tests.

---

## Phase 1: Setup

**Purpose**: Establish the exact checkout, accepted scope and pre-change parity without using accounts.

- [X] T001 Verify branch, working tree, accepted owner decision and migration endpoint 035 against
  `specs/020-meta-host-browser-search/plan.md` and `sql/`; record scope/baseline in
  `.handoff/spec020-verification.md` using `tests/unit/test_host_browser_search.py`,
  `tests/unit/test_host_browser_relay.py`, `tests/unit/test_watchlist_period.py`,
  `tests/unit/test_watchlist_seen_axis.py`, `tests/integration/test_host_browser_mission.py` and
  `tests/integration/test_host_browser_search_mcp.py` with mocked sources, no live requests; disclose
  failures/skips before dependent work.
- [X] T002 Capture synthetic pre-feature TikTok prepare/receipt defaults, public submit/cancel schemas
  and equal-path seen/created day/week/month outputs using `tests/unit/test_host_browser_search.py`,
  `tests/unit/test_watchlist_period.py` and `tests/unit/test_watchlist_seen_axis.py`; place sanitized
  expected JSON under `tests/fixtures/meta_host_browser_baseline/` before source changes, preserving
  existing `tests/fixtures/watchlist_period_created_baseline/` unchanged.

---

## Phase 2: Foundational (spike and shared typed/vocabulary prerequisites)

**Purpose**: Settle the composition feasibility boundary before building the dependent feature.

- [X] T003 SPIKE the single-run composition through the seams in
  `src/ignis/application/use_cases/host_browser_search.py`,
  `src/ignis/application/use_cases/host_browser_mission.py` and `src/ignis/interfaces/mcp/server.py`;
  put only a disposable mock-backed executable probe and its result in
  `.handoff/spec020-composition-spike.py` and `.handoff/spec020-composition-spike.md`. Model the
  approved optional prepare `source`, two separately prepared/staged source tickets, unchanged
  submit/cancel parameters, one mission/caller/frame binding and one writer/run. Demonstrate submit of
  either member consumes both exactly once, every required source/query and remaining-channel outcome is
  retained, caller/frame changes and duplicate/missing siblings refuse before writes,
  cancellation/expiry/replay cannot leave a collectible sibling or trigger fallback, and no record
  transcription/new public parameter/tool is required. Exit **GO** only with executable evidence that
  these tools can express the full lifecycle safely; otherwise record **STOP / needs owner review**, the
  failing boundary and minimal alternatives. If STOP or inconclusive, **all T004 onward remain
  blocked**; do not implement a new tool/parameter or narrow acceptance to continue. No real
  browser/account/API or production-code edits in this spike.
  **Result (27/10/2026): STOP.** A mock-backed probe over the unchanged submit/cancel handlers showed
  that today's seams do not coordinate siblings: each submit runs its own writer with no shared
  receipt, a Threads ticket is still mapped to TikTok and sent to the registry, a caller change and a
  missing or duplicate sibling are not refused before the write, and a cancelled or expired sibling
  can still be submitted. No new public parameter or tool was shown to be necessary. The candidate
  is an internal group coordinator (admission keyed by mission, caller storage and frame; atomic
  claim; one canonical writer; shared receipt; group-wide cancel, expiry and drain), to be prototyped
  in a follow-up spike before any GO. Baseline outside the sandbox: 170 passed, 2 skipped with a
  disposable PostgreSQL; the sandbox-only run failed 55 relay cases on loopback binding.
  **Follow-up spike (28/10/2026): GO.** A disposable in-probe group coordinator (mocked relay and
  browser; real canonical executor, journal and SQLite) passed 33/33 boundaries: either submit order
  runs one canonical executor with one shared receipt; Threads and TikTok outcomes stay separate and
  both host surfaces are skipped in the registry; caller, frame or plan changes and missing,
  duplicate or stale siblings are refused before any write; cancel, expiry, rejection and replay end
  the whole group; in-flight cancellation drains the writer and reads back without retry. Public MCP
  stays at the approved change (optional prepare `source`, 53 tools). Production changes for
  T017–T020: `host_browser_search.py` (group admission, atomic claim, shared cache, cancel/drain,
  expiry), `host_browser_mission.py` (group guards, per-source mapping, one executor call),
  `server.py` (optional `source`, original-caller checks), `execute_mission.py`
  (`_record_probe_outcomes` provenance per T020). Risk is high in caller isolation,
  cancellation/drain and retention; PostgreSQL and live transport are unproven. T004 onward
  unblocked.
- [X] T004 [P] Write and run failing source/counter model tests in new
  `tests/unit/test_threads_host_answer_validation.py`: default TikTok compatibility, immutable Threads
  source/version, limits and exact publication clock, structured raw-display/unit/precision counters,
  unknown versus zero, no Share-to-quotes alias and rejection of unsupported source/version; preserve
  legacy TikTok answer shape on TikTok tickets only.
- [X] T005 [P] Write and run failing Threads vocabulary/seed tests in
  `tests/unit/test_vocabulary_loader.py`, `tests/unit/test_sql_packaging.py` and new
  `tests/integration/test_meta_host_evidence_backend_parity.py`: observed English template available to
  packaged tactical and repository mission paths, source-specific missing vocabulary fails closed,
  repeated seed application is idempotent and changes no evidence/schema; use both-backend fixtures from
  `tests/integration/conftest.py`.
- [X] T006 Add seed-only `sql/036_threads_attribution.sql` with domain `threads_attribution`, category
  `ui_attribution`, observed `Photo by {author} on` template and system ownership; add SQLite seed
  replay in `src/ignis/infrastructure/persistence/sqlite_repository.py` and the PostgreSQL fixture chain
  entry in `tests/integration/conftest.py`; recheck numbering first, stop on a conflicting 036 rather
  than overwriting it. No historical data rewrite.
- [X] T007 Extend `src/ignis/infrastructure/config/vocabulary_loader.py` with Threads attribution
  domain/model/loading and source-specific registration, packaged tactical seed and mission-repository
  refresh before ticket freeze; do not retain a stale other-source template or add unobserved locales
  (satisfies vocabulary portion of T005).
- [X] T008 Extend typed request/record/answer models in `src/ignis/domain/host_browser_search.py` for
  TikTok/Threads browser sources, frozen versions and counter components/precision; retain strict
  allowlists and legacy TikTok payload compatibility, with no additional public parameter or API variant
  (makes T004 pass).

**Checkpoint**: T003 has an evidenced GO; T004 model and T005 seed/vocabulary cases pass on available
backends. PostgreSQL skips remain explicit obligations for T047. Foundation does not claim host readiness.

---

## Phase 3: User Story 1 - Threads host-browser collection and path-aware periods (Priority: P1)

**Goal**: Threads uses the authorized host relay, preserves privacy and measurement semantics, and
feeds the existing channel in a single composed mission run. FR-006 applies to both period axes.

**Independent Test**: A deterministic two-source host batch returns sanitized Threads/TikTok results
in one canonical mission run with per-query outcomes; unavailable host has no fallback. Changed,
mixed or unknown path pairs are not comparable on seen or created. Real-account proof is T051.

### Tests first (after the foundation; observe RED before covered implementation)

- [X] T009 [US1] Extend failing validation/lifecycle cases in
  `tests/unit/test_threads_host_answer_validation.py` and `tests/unit/test_host_browser_search.py`:
  exact www.threads.com Top query/page, allowed permalink/media canonicalization, wrong
  route/filter/origin, missing/extra/duplicate queries, oversize/stale/future data, unsupported locale,
  absent vocabulary, all-content-dropped degradation, rejected healthy-empty, expiry/replay/caller
  binding and no receipt identity.
- [X] T010 [P] [US1] Add synthetic G2-shaped DOM fixtures under `tests/fixtures/threads_host_search/`
  and failing tests in new `tests/integration/test_threads_host_dom_contract.py`: timestamp/action-row
  card isolation, multiline body, text/image/carousel/quote/media dedup, virtualized removals,
  sidebar/header/avatar/alt attribution exclusion, exact datetime and rounded `1.4K`, blank counters,
  loading/shell/challenge/wrong page; no invented Recent/video/empty-state selectors.
- [X] T011 [P] [US1] Write failing source-specific relay/handoff tests in
  `tests/unit/test_host_browser_relay.py`: exact Threads/TikTok origin and opened-window/query/request
  binding, no cross-source acceptance, hostile-query escaping/nonce CSP, exact Host/Origin, body limits,
  opener loss and terminal shutdown; browser returns only status/counts, never record content.
- [X] T012 [P] [US1] Convert T003's accepted lifecycle into failing integration/contract tests in
  `tests/integration/test_host_browser_mission.py` and
  `tests/integration/test_host_browser_search_mcp.py`: one run/writer for both host sources, unchanged
  submit/cancel signatures, prepare source default, complete falsifier query union and
  authority/budget/caller guards, missing/duplicate/stale sibling rejection, concurrent
  submit/replay/cancel/expiry and uncertain-persistence drain/readback, unrelated outcomes preserved
  with zero internal Threads collection calls.
- [X] T013 [P] [US1] Extend failing privacy/storage cases in
  `tests/integration/test_meta_host_evidence_backend_parity.py` and
  `tests/integration/test_author_identity_conformance.py` using synthetic sentinels in
  `tests/fixtures/author_identity_sentinels.py`: identity-free links before receipts/writes, attribution
  from a different synthetic identity, handles/metadata/log/report/journal cleanup,
  source-not-verifiable context exclusion, pre-strip self-content exclusion, observation
  query/path/precision and empty-probe attestation round-trip on SQLite/PostgreSQL.

### Implementation (after the corresponding RED)

- [X] T014 [US1] Implement source-specific `validate_answer` and outward receipt cleanup in
  `src/ignis/infrastructure/connectors/host_browser/validator.py` and
  `src/ignis/application/use_cases/host_browser_search.py`; reuse attribution/PII/mention policy in
  `src/ignis/infrastructure/security/pii_sanitizer.py` and identity-free content URLs in
  `src/ignis/domain/source_identity.py`. Apply self-exclusion using transient author-bearing input
  before destroying it, never retain raw identity in staged/outward receipts; preserve cleaned body,
  clocks, counter precision and query lineage, degrade all-dropped content and reject unproven Threads
  empty (T009/T013).
- [X] T015 [US1] Add packaged `src/ignis/infrastructure/connectors/host_browser/threads_search.js`
  version `threads-search-top-v1` from `specs/020-meta-host-browser-search/g2-surfaces.md`: exact Top
  page, smallest timestamp/action-row ancestor, isolated visible body, shortcode dedup, ISO datetime and
  SVG-title counter components; bounded visible sample, no page
  clicks/typing/storage/fetch/whole-card/alt-only fallback (makes T010 pass).
- [X] T016 [US1] Add `src/ignis/infrastructure/connectors/host_browser/threads_handoff.js` and
  source-specific composition/origin-window validation in
  `src/ignis/infrastructure/connectors/host_browser/relay.py` and
  `src/ignis/infrastructure/templates/html/host_browser_relay.html`; preserve
  `src/ignis/infrastructure/connectors/host_browser/tiktok_handoff.js` behavior and all existing
  transport security/termination bounds (makes T011 pass).
- [X] T017 [US1] Implement source-bound preparation and source-specific vocabulary snapshots in
  `src/ignis/application/use_cases/host_browser_search.py`: exact URLs/extractor/handoff resources,
  immutable source, task bounds, packaged tactical versus fresh mission vocabulary, fail before relay
  creation on missing vocabulary and no new collection fallback (T009).
- [X] T018 [US1] Add only optional `source` defaulting to `tiktok` to prepare handler/public tool in
  `src/ignis/interfaces/mcp/server.py`; retain submit/cancel signatures, caller-storage binding, derived
  mission queries/limit and TikTok defaults; return source-specific descriptors without API-adapter
  fields (T012).
- [X] T019 [US1] Implement the GO composition design in
  `src/ignis/application/use_cases/host_browser_search.py` and
  `src/ignis/application/use_cases/host_browser_mission.py`: sibling source tickets bound to same
  mission/caller/frame, complete staged group, one writer/run, shared receipt cache,
  duplicate/incomplete/stale refusal and coordinated cancellation/expiry/drain. Stage/degraded outcomes
  must retain all required surfaces; execute remaining non-host surfaces only once (T012).
- [X] T020 [US1] Map validated Threads/TikTok results into canonical `SearchPassResult` in
  `src/ignis/application/use_cases/host_browser_mission.py` and persist normalized
  method/revision/sampling in observation metadata and probe `scope_attestation` via
  `src/ignis/application/use_cases/execute_mission.py`, including zero-record outcomes; preserve scope
  keys, ingestion clocks, complete outcome set and qualification, with no schema/backfill (T013).
- [X] T021 [US1] Complete author-identity conformance and query/content-reference parity in
  `tests/integration/test_author_identity_pipeline.py`,
  `tests/integration/test_author_identity_parity.py`, `tests/unit/test_identity_free_mcp_responses.py`
  and `tests/unit/test_source_identity.py`; prove unknown author markers, link-unavailable/context
  behavior, duplicate media/query dedup once per topic and zero identity leakage without collecting
  authors merely for voice counts. Any needed source correction returns to T014 with new RED evidence.
- [X] T022 [US1] Run the host receipt/mission subset of
  `tests/integration/test_meta_host_evidence_backend_parity.py` on SQLite and PostgreSQL: immutable
  observation/association/probe JSON, clocks, counters, path, caller/writer guards and complete
  sibling-source outcomes agree; record actual passed/skipped results in
  `.handoff/spec020-verification.md`. Fix only traced adapter serialization in
  `src/ignis/infrastructure/persistence/sqlite_repository.py`,
  `src/ignis/infrastructure/persistence/postgres_repository.py` or
  `src/ignis/infrastructure/persistence/workspace_repository.py` after a failing parity case, with no
  schema migration.
**T009–T022 local verification (28/10/2026):** 227 passed, 71 PostgreSQL skips with only the
listener mocked; caller/manifest/convention/DOM checks 113 passed. T022 dedicated file: 7 SQLite
passed, 7 PostgreSQL skipped (no injected DSN; coordinator verification pending). Native listener
subset: 46 passed, 50 skipped, 55 sandbox socket-bind failures. These ticks record scoped
implementation and the requested local runs, not PostgreSQL or real-transport acceptance. Exact
commands, RED/GREEN evidence and limitations: `.handoff/spec020-verification.md`. Subsequent period work is recorded below.

- [X] T023 [P] [US1] Write and run failing pure path/precision tests in new
  `tests/unit/test_collection_path_comparability.py` and existing `tests/unit/test_watchlist_period.py`,
  `tests/unit/test_watchlist_seen_axis.py`: changed/mixed/unknown/conflicting method, revision/sampling
  change, equal paths, all-empty probes, same post on several paths before merge, created counter-window
  paths, rounded/incomplete aggregates and unchanged coverage/cadence/judgment/other-channel behavior.
- [X] T024 [P] [US1] Write and run failing use-case/storage response tests in
  `tests/integration/test_watchlist_period_storage.py`, `tests/integration/test_watchlist_mcp.py` and
  the period subset of `tests/integration/test_meta_host_evidence_backend_parity.py`: both axes
  propagate observation/probe paths and reasons, explicitly proved legacy metadata versus unknown
  history, exact clocks, no historical writes, once-per-topic query lineage and unchanged snapshot tool
  parameters on both backends.
- [X] T025 [US1] Extend path-bearing internal period inputs and both-axis comparisons in
  `src/ignis/domain/watchlist_period.py`; gate before source merge, require one proven identical method
  on each side, append changed/mixed/unknown reasons without comparison delta, preserve existing
  coverage/cadence/unjudged rules and raw/rounded counter semantics (makes T023 pass).
- [X] T026 [US1] Propagate immutable observation/probe path/revision/sampling and classification basis
  in `src/ignis/application/use_cases/watchlist_period.py`; read legacy proof conservatively, handle
  empty probes, never infer from dates/cookies or backfill history, and retain ingestion/publication
  placement (makes T024 pass).
- [X] T027 [US1] Add failing exact-publication/self-exclusion regression cases to
  `tests/unit/test_social_search_integrity.py` and `tests/integration/test_host_browser_mission.py`,
  then adjust `src/ignis/infrastructure/harness/quality_evaluator.py` and affected
  `src/ignis/domain/self_content.py` / `src/ignis/infrastructure/auth/self_identity.py` consumers only
  as needed so Threads datetime is known, capture is not publication and pre-strip self-content
  exclusion survives host ingestion; rerun both-source default parity.
- [X] T028 [US1] Prove the automated host-path checkpoint with
  `tests/unit/test_threads_host_answer_validation.py`, `tests/unit/test_host_browser_search.py`,
  `tests/unit/test_host_browser_relay.py`, `tests/integration/test_threads_host_dom_contract.py`,
  `tests/integration/test_host_browser_search_mcp.py`, `tests/integration/test_host_browser_mission.py`,
  `tests/integration/test_author_identity_conformance.py`,
  `tests/unit/test_collection_path_comparability.py` and the backend cases in T022/T024; compare
  unaffected outputs to `tests/fixtures/meta_host_browser_baseline/` and record evidence in
  `.handoff/spec020-verification.md` before starting T029. Missing local prerequisites are a checkpoint
  blocker, not a pass; PostgreSQL proof still must complete in T047.

**T028 coordinator run (28/10/2026), outside the sandbox with a disposable PostgreSQL:** the
listed checkpoint files plus `test_meta_host_evidence_backend_parity.py` and
`test_watchlist_period_storage.py`: 338 passed, 6 skipped (all six are SQLite-only lifecycle and
fault-injection cases by design); native relay listener included. Baselines: 9 MATCH. Broader
period, host and contract consumers: 715 passed, 7 skipped.

**T023–T028 local result (28/10/2026):** T023–T027 implemented. Final period/consumer run:
225 passed, 48 PostgreSQL skipped. Equal-path baselines: 3 created snapshots pass, 9 synthetic JSON
MATCH (frozen JSON unchanged). Host checkpoint with listener mocked: 206 passed, 84 PostgreSQL
skipped, 1 native-page test deselected; native checkpoint: 187 passed, 84 skipped, 56 sandbox
socket-bind failures. The final classification-label guard adds one passing period test afterward.
T028 remains unchecked: these missing prerequisites block checkpoint acceptance, per its rule;
coordinator must run new PostgreSQL cases and native relay outside this sandbox. No live proof or
US2 development authorized by this local result; T029 is not started. Exact commands and RED/GREEN:
`.handoff/spec020-verification.md`.

**Coordinator policy correction (28/10/2026):** Wholly unknown paths on both sides retain
legacy comparison and response shape; only known/unknown across sides or internally mixed paths
refuse. Synthetic default provenance and legacy-baseline path stripping removed. Corrected period
and consumer verification: 192 passed, 48 PostgreSQL skipped; T002 9 MATCH and frozen created baseline
unchanged. This supersedes the earlier blanket unknown refusal. T028 remains unchecked; T029 has
not started. See the correction receipt in `.handoff/spec020-verification.md`.

**Checkpoint**: Source preparation → packaged DOM extraction → relay staging → unchanged submit →
one canonical mission writer/run is proved by deterministic tests. Threads channel and both period
axes preserve provenance/privacy. This permits development of US2, not a claim of live channel repair.

---

## Phase 4: User Story 2 - Retire Threads Playwright; remove eight flags; retain Reels (Priority: P1)

**Goal**: No internal Threads collection or automation-hiding flag remains; shared Reels collection
works flag-free and blocked/unusable pages are visibly unavailable rather than measured empty.

**Independent Test**: Mock host absence with stored Threads cookies/OAuth and prove no internal
collector runs. Source scan is clean. Mock Reels healthy/login/checkpoint/challenge/unusable pages
and verify observations or unavailable-with-reason; real Reels acceptance remains T052.

### Tests first (only after T028; fail before retirement/flag changes)

- [X] T029 [P] [US2] Write failing retirement/no-fallback assertions in
  `tests/unit/test_threads_plugin.py`, `tests/unit/test_threads_relay_search.py`,
  `tests/unit/test_threads_direct_graphql.py`, `tests/unit/test_threads_graph_ingress.py`,
  `tests/unit/test_threads_keyword_search_access.py`,
  `tests/unit/test_threads_keyword_search_authority.py`, `tests/unit/test_threads_mcp_tools.py` and
  `tests/unit/test_bug03_threads_empty_status.py`: existing cookies/OAuth never collect
  search/OWN_PROFILE/trending/suggestions through Playwright, cookie HTTP, internal OAuth or legacy
  fallback; unavailable has reason, auth/status/clear and public signatures remain compatible.
- [X] T030 [P] [US2] Write failing static and mocked-launch tests in new
  `tests/unit/test_browser_launch_flag_policy.py` plus affected `tests/unit/test_tiktok_auth.py`,
  `tests/unit/test_tiktok_suggestions.py`, `tests/unit/test_tiktok_comments.py`,
  `tests/unit/test_tiktok_plugin.py`, `tests/unit/test_tiktok_creative_center.py`,
  `tests/unit/test_tiktok_health_probes.py`: eight original sites accounted for, all retained launches
  flag-free, retired Threads helper has no executable caller and no replacement evasion flag/tool.
- [X] T031 [P] [US2] Write failing blocked/unusable-versus-empty and shared-helper parity cases in
  `tests/unit/test_meta_browser_ingress.py`, `tests/unit/test_meta_browser_auth.py`,
  `tests/unit/test_instagram_mcp_tools.py`, `tests/unit/test_cookie_scope.py`,
  `tests/unit/test_docid_sniffer_dedupe.py` and `tests/unit/test_runtime_config.py`: Reels still
  collects healthy pages without flag; login wall/checkpoint/challenge/unusable page produces
  unavailable reason, never healthy empty from zero parsed cards; retain shared config/cache and 30-day
  session behavior.

### Implementation

- [X] T032 [US2] Remove Threads Playwright collection/callers in
  `src/ignis/infrastructure/connectors/threads/threads_plugin.py` and Threads-only helper
  `collect_threads_search_suggestions_via_browser` in
  `src/ignis/infrastructure/connectors/meta_browser_ingress.py`; disable cookie GraphQL/internal
  OAuth/legacy collection fallback in search, OWN_PROFILE, trending and suggestions. Preserve
  port-compatible explicit unavailable and shared Reels ingress, without deleting stored sessions or
  changing auth tool signatures (T029).
- [X] T033 [US2] Write failing admission/health/retry assertions in `tests/unit/test_registry.py`,
  `tests/unit/test_round3_regressions.py`, `tests/unit/test_insights_ttl_cache.py`,
  `tests/unit/test_source_map_matches_connectors.py` and `tests/unit/test_connector_daily_ceiling.py`,
  then update `src/ignis/infrastructure/connectors/registry.py` and
  `src/ignis/infrastructure/harness/refinement_orchestrator.py`: cookies or Ignis OAuth do not imply
  usable Threads search, host absence is unavailable, host-injected surfaces skip internal dispatch,
  ceilings and unrelated connector isolation remain.
- [X] T034 [US2] Preserve authenticate/status/clear/trending/suggestions MCP signatures while fixing
  unavailable response descriptions, retired-login remedies and credential-readiness diagnostics in
  `src/ignis/interfaces/mcp/server.py`; retain needed compatibility exports in
  `src/ignis/infrastructure/auth/__init__.py`; run targeted `tests/unit/test_threads_mcp_tools.py`,
  `tests/unit/test_credential_clear_wording.py`, `tests/unit/test_caller_platform_sessions.py`,
  `tests/unit/test_caller_analysis_composition.py` and
  `tests/unit/test_caller_relay_read_composition.py` (T029).
- [X] T035 [US2] Remove flags from `MetaBrowserAuthManager.authenticate_interactive` in
  `src/ignis/infrastructure/auth/meta_browser_auth.py` and `collect_json_payloads` in
  `src/ignis/infrastructure/connectors/meta_browser_ingress.py`; count the retired suggestions-helper
  launch as removed by T032. Keep Reels shared helper and auth behavior; these account for three of the
  original eight sites (T030/T031).
- [X] T036 [US2] Remove flags from `TikTokAuthManager.authenticate_interactive` in
  `src/ignis/infrastructure/auth/tiktok_auth.py`, `fetch_suggestions`, `fetch_video_comments`,
  `_fetch_via_playwright` in `src/ignis/infrastructure/connectors/tiktok/tiktok_plugin.py`, and
  `fetch_macro_trends` in `src/ignis/infrastructure/connectors/tiktok/creative_center_plugin.py`;
  preserve remaining arguments, authority and TikTok host defaults. These are the other five original
  sites (T030).
- [X] T037 [US2] Implement precise blocked/unusable classification and reason propagation through
  `src/ignis/infrastructure/connectors/meta_browser_ingress.py`,
  `src/ignis/infrastructure/connectors/reels/reels_plugin.py` and affected registry mapping in
  `src/ignis/infrastructure/connectors/registry.py`; retain flag-free Reels healthy collection, never
  infer absence from parser-zero or mask blocking with fallback (makes T031 pass).
- [X] T038 [US2] Add failing affected follow-up/composition cases in
  `tests/unit/test_follow_up_root_composition.py`, `tests/unit/test_follow_up_caller_activation.py`,
  `tests/integration/test_t022_operational_surface_parity.py` and
  `tests/integration/test_ingest_orchestration.py`, then reconcile required path/revision/availability
  guards in `src/ignis/application/use_cases/execute_mission_follow_up.py`,
  `src/ignis/infrastructure/follow_up_root_composition.py`,
  `src/ignis/infrastructure/follow_up_caller_activation.py` and
  `src/ignis/application/use_cases/watchlists.py` only where traced; no historical mission restart, new
  routine or automatic browser collection.
- [X] T039 [US2] Run the T029–T038 targeted consumer cases plus T028's host-path regressions and `rg -n
  -- 'AutomationControlled' src` (expect no matches, exit 1); record all eight sites, mock launch
  arguments, stored-cookie no-fallback proof and Reels unavailable reasons in
  `.handoff/spec020-verification.md`. No real-account run or live-repair claim at this checkpoint.

---

**Phase 4 local result (28/10/2026):** T029–T039 implemented and targeted checks recorded.
563 passed, 33 PostgreSQL skips in the Phase 4 consumer run; 240 passed, 84 PostgreSQL skips,
1 native-page deselection with only the host listener mocked. Native host regression run:
204 passed, 84 skipped, 56 sandbox socket-bind failures. Guard and all seven retained mock launches:
14 passed; `rg -n -- 'AutomationControlled' src` has no matches (exit 1). Ruff, conventions,
53-tool contract and generated-manifest drift pass; TikTok/period baselines 9 MATCH. No real-account
run, live repair, routine change, commit or Phase 5/6 work. Exact evidence and limitations:
`.handoff/spec020-verification.md`. New PostgreSQL cases remain coordinator verification work.

## Phase 5: User Story 3 - Deferred by owner decision (Priority: P1 target; no tasks)

**Deferred note**: US3 / FR-008, including `threads-mcp-keyword-v1`, API submission, grant probing,
structured MCP-result transport and API precedence activation, is deferred until App Review approval
and a spec amendment. Create no API implementation, API-model, transport-spike, provider-call or
live-API tasks now. Older API clauses in the design artifacts are not current execution authority.
The generic path-comparison rules above do not require an API adapter to test method discontinuity.

---

## Phase 6: Polish, distribution and acceptance

**Purpose**: Verify the accepted browser-only increment, package its resources and leave separate
live-account authority visible. No tool-count change, release, version bump or routine activation.

- [X] T040 Write and run failing seed endpoint/resource packaging assertions for
  `sql/036_threads_attribution.sql` and the new Threads JS/handoff in
  `tests/unit/test_sql_packaging.py`, `tests/unit/test_public_distribution_contract.py` and
  `tests/integration/test_compose_init.py`; verify fresh PostgreSQL migration chain and no
  evidence/schema transformation on repeated vocabulary seed, reusing the fixture chain from T006.
- [X] T041 Update the migration endpoint 035 → 036 in `tests/integration/test_compose_init.py`,
  `tests/unit/test_sql_packaging.py` and migration-specific expectations in
  `tests/unit/test_public_distribution_contract.py`, consistent with `tests/integration/conftest.py`;
  preserve relation counts/RLS expectations because the migration adds no table. Documentation endpoint
  updates are T046 (T040).
- [X] T042 Verify and, only where needed, extend existing resource inclusion in `pyproject.toml` so
  built wheel/sdist ship `sql/036_threads_attribution.sql`,
  `src/ignis/infrastructure/connectors/host_browser/threads_search.js`,
  `src/ignis/infrastructure/connectors/host_browser/threads_handoff.js` and the relay template; use
  packaged resource reads, not source-path fallback (makes resource cases in T040 pass; no
  dependency/version/lock churn).
- [X] T043 Write and run failing optional-source schema/description drift cases in
  `tests/unit/test_tool_manifests_drift.py`, `tests/unit/test_public_mcp_contract.py` and affected
  `tests/integration/test_host_browser_search_mcp.py`: source defaults to TikTok, invalid source
  refuses, submit/cancel parameter sets unchanged, browser-only Threads descriptors, exact tool set
  still 53 and retained Threads descriptions no longer promise cookie collection; do not add count-bump
  tasks.
- [X] T044 Regenerate `hermes_manifest.json` and `.hermes/tools.json` with the prescribed
  `scripts/sync_tool_manifests.py --write` using checkout source and an isolated synthetic
  configuration; inspect schema/description-only differences and rerun T043, then generator check mode.
  Do not modify count-only consumers such as `openclaw.json` or `AGENTS.md`/`CLAUDE.md`; no new tools.
- [X] T045 Write and run failing regional/public documentation and period-guide behavior assertions in
  `tests/unit/test_public_doc_conventions.py`, migration-related cases in
  `tests/unit/test_public_distribution_contract.py` and `tests/unit/test_ignis_listen_guidance.py`:
  optional source/default, host-only Threads, flag-free/unavailable Reels, counter precision, both-axis
  path-change reasons and upgrade endpoint 036; preserve FR-009 routine boundary and avoid requiring
  excluded agent-context edits.
- [X] T046 Update `README.md`, `README.vi.md`, `docs/USER_GUIDE.md`, `docs/USER_GUIDE.vi.md`,
  `src/ignis/interfaces/mcp/guides/ignis_listen.md` and validated command/outcome guidance in
  `specs/020-meta-host-browser-search/quickstart.md` to match accepted owner scope, signature and
  migration endpoint; document source/privacy/precision/path limitations and unchanged count 53, no API
  activation or repaired-channel claim. Use applicable Vietnamese editing review for localized copy;
  skip `.agents/` mirrors and all routine/context changes, disclose existing mirror check consequences
  (T045).
- [X] T047 Complete PostgreSQL parity and SQLite regression proof in
  `tests/integration/test_meta_host_evidence_backend_parity.py`,
  `tests/integration/test_watchlist_period_storage.py`,
  `tests/integration/test_author_identity_parity.py` and changed migration-chain cases in
  `tests/integration/test_compose_init.py`, with disposable approved fixtures: seed idempotence/no
  evidence rewrite, sanitized observation/association and empty-probe path round-trip, exact
  clocks/precision, sibling-source single writer/caller isolation and both-axis
  changed/mixed/unknown/equal responses. Record actual DSN availability and outcomes in
  `.handoff/spec020-verification.md`; missing injected test DSN leaves parity pending, never read
  credentials or substitute a live store.
- [X] T048 Build wheel/sdist with existing locked tooling into `.handoff/spec020-dist/`, install the
  wheel without changing the shared venv into disposable `.handoff/spec020-wheel-venv/` using existing
  approved local dependencies, and run `scripts/wheel_mcp_smoke.py` with that environment's interpreter
  and no checkout PYTHONPATH. Use only newly generated synthetic configuration, no existing
  env/credential file or network install; prove resource reads for the new JS/SQL/handoff and actual
  prepare source schema/default, exact 53-tool discovery, unchanged submit/cancel schemas and clean
  server shutdown. Record wheel hash/environment/command/output in `.handoff/spec020-verification.md`;
  missing cache/tooling is an explicit blocker, not a reason to use editable source or install over the
  shared wheel.
- [X] T049 Obtain required independent code/security review of the exact implementation diff covering
  source-origin relay trust, untrusted staged input, identity-free receipts/storage, caller/group
  concurrency, unavailable classification, unchanged public boundaries and canonical evidence parity;
  record revision-bound findings/disposition in `.handoff/spec020-review.md`. Resolve blocking findings
  with targeted RED/GREEN and invalidate only affected evidence; review does not grant merge/release
  authority.

  **Review findings and fixes (28/10/2026)**: coordinator verified Antigravity's read-only review
  of `origin/main...26ed2a8`; fixes start from `bc99fd7`. Added RED/GREEN for terminal/stale group
  replacement, transient canonical author policy with declared mentions, caller-local vocabulary
  (including synchronizer isolation), default Playwright UA, per-member failure IDs, malformed
  anchors and failed sibling preparation cleanup. Mission lifecycle stays unchanged: COMPLETED is
  refused; accepted-group replay survives the supported fresh-mission flow. Removed the test that
  rewound retention. Local evidence and residual T051 risks are in `.handoff/spec020-verification.md`.
  PostgreSQL/socket proof and revision-bound coordinator/reviewer acceptance remain separate;
  this note does not complete T049/T050 or authorize live runs.

- [X] T050 Run final targeted verification of every changed behavioral test and traced affected consumer
  from T004–T049, plus `tests/unit/test_repo_conventions.py`, `tests/unit/test_public_mcp_contract.py`,
  `tests/unit/test_public_distribution_contract.py`, `tests/unit/test_public_doc_conventions.py`,
  `tests/unit/test_tool_manifests_drift.py` and `tests/unit/test_sql_packaging.py` with the source-check
  command above; check changed Python with repository Ruff configuration, `git diff --check` over the
  actual change range, unique new test module basenames across `tests/unit/` and `tests/integration/`,
  zero evasion flags and unchanged context/routine/version files. Record exact results,
  backend/wheel/review limits, immutable evidence baseline and no implementation of deferred scope in
  `.handoff/spec020-verification.md`; do not run the full suite, weaken a mirror gate, commit or claim
  live repair.
**Coordinator closure of T047, T049 and T050 (28/10/2026)**, outside the sandbox with a disposable
PostgreSQL (`timescale/timescaledb-ha:pg16`, trust auth, no credentials):
- T047: backend parity, period storage, author-identity parity and host mission cases run on both
  backends inside the T050 run below; the compose migration-chain case needs Docker Compose and
  stays with CI.
- T049: Antigravity (`gemini-4-argon-high`, read-only) reviewed `origin/main...26ed2a8` and found
  six confirmed defects plus three suspicions; all six and suspicion 2.2 were fixed in `1ee1419`.
  Its re-review of `1ee1419` marked every finding resolved, traced the transient author records on
  all success, error, cancellation and shutdown paths with no leak, and found one new defect (a
  failed preparation could cancel an in-flight submit), fixed in the next commit. Residual risks for
  T051: the Threads header-exclusion layout assumption, and a pre-existing INFO log of the
  operator's own connected identities.
- T050: every changed test and traced consumer, plus the convention, MCP contract, distribution,
  doc, manifest and SQL packaging gates: 4627 passed, 11 skipped (backend-specific by design),
  3 deselected (two `.env`-writing bootstrap cases and the pooler case that needs a worktree
  `.venv`; both pass in CI). Host consumers after the last fix: 376 passed, 6 skipped. Ruff and
  `git diff --check` clean; no `AutomationControlled` or user-agent override under `src/`; unique
  test basenames; wheel built from the branch and smoke-tested in an isolated venv (53 tools,
  optional prepare `source`, submit/cancel unchanged).

- [ ] T051 **Needs separate owner approval**: after T050 and explicit bounded real-session/G3-run
  authority, execute the implemented Ignis prepare → Threads/TikTok host extraction → relay → submit →
  single G3 mission run and canonical readback per `specs/020-meta-host-browser-search/quickstart.md`;
  record sanitized request/run IDs, versions, per-query/channel outcomes, at least one Threads
  observation where the page has results, exact clocks/rounded units/path, zero author leakage and
  path-discontinuity period evidence in `.handoff/spec020-live-host.md` (FR-011, SC-001, SC-002,
  SC-005). Preserve owner browser/tabs, stop on login/challenge/denial, no fallback, credentials or G3
  routine change. Leave unchecked without approval or actual live proof; manual G2/fixtures/wheel smoke
  are insufficient.
- [X] T052 **Needs separate owner approval**: after T050 and explicit bounded real Reels session/run
  authority, execute flag-free Reels and read back either observations or unavailable with the actual
  login/checkpoint/challenge/unusable reason, never measured zero from a blocked page; record sanitized
  run/status/readback evidence in `.handoff/spec020-live-reels.md` per
  `specs/020-meta-host-browser-search/quickstart.md` (FR-007, SC-006). No reauthentication, account
  action, routine update or evasion; leave unchecked without approval and observed outcome.
  Owner-approved live run 28/10/2026: flag-free Reels with the stored Tier-1 session returned
  `REELS_PAGE_UNUSABLE` (unavailable, no measured zero); evidence `.handoff/spec020-live-reels.md`.

---

## Owner-approved follow-up: host-browser skill guidance (28/10/2026)

- [X] T053 Update host-neutral TikTok/Threads search guidance in
  `.agents/skills/ignis-collect/SKILL.md` and correct only the source-readiness bullet in
  `.agents/skills/ignis-routine/SKILL.md` and its packaged source
  `src/ignis/interfaces/mcp/guides/ignis_routine.md` (kept byte-identical), owner-approved 28/10/2026. This lifts the earlier
  agent-context skip for exactly those two files. Deliver full replacements under
  `.handoff/spec020-skill/` for coordinator copy; add test-first guidance assertions and verify
  the targeted skill/convention/packaging consumers. Preserve frontmatter, unrelated sections,
  routine prompts and schedules (FR-009); no runtime or live-session work. Ticked after
  coordinator integration and verification (63 passed).

- [X] T054 Fix the two live-run defects, owner-approved 28/10/2026; evidence:
  `.handoff/spec020-live-run-20261028.md`. Test-first, accept only Threads `locale=unsupported`
  with `DEGRADED`, unverified search and no records; record the English-only locale reason and
  zero observations. Keep invalid locale/measurement claims rejected, English and TikTok parity;
  trace tactical submit, mission ingestion, channel outcome and both period axes. Correct the
  ignis-collect manual Stage-answer guidance to require the full source-bound envelope, all
  approved queries in prepare order, unchanged extractor output and a new ticket after rejection.
  Deliver the full skill replacement in `.handoff/spec020-skill/ignis-collect/SKILL.md` and add
  assertions in `tests/unit/test_ignis_skills.py`; installed-skill RED remains until coordinator copy.
  Preserve handoff transport, relay origin checks and `tab_script`; Threads opener is owner-pending.
  Run targeted tests, changed-Python ruff and `git diff --check`; no commit or live session.
  Coordinator copied the skill and verified 374 passed, 6 SQLite-only skips, PostgreSQL parity included.

- [X] T055 Implement Threads-only encrypted same-tab handoff, owner-approved 28/10/2026.
  Amend `plan.md`, `research.md` and `contracts/threads-search.md` with the live facts and decision.
  Test first: per-ticket AES-GCM key and fresh IV, bounded encrypted fragment, exact GET receiver,
  immediate hash clearing, BroadcastChannel decryption/bindings/limits/first-answer/submission
  guards; no key in URLs, receiver or other prepare fields. Cover one/two queries, tampering,
  wrong request/query, oversize refusal, TikTok absence/parity and T054 locales. Reuse lifecycle
  and full-envelope form. Deliver the full skill replacement under `.handoff/spec020-skill/`,
  about 50 host-browser lines, with matching `test_ignis_skills.py` assertion; coordinator copies
  the installed skill and runs live Chrome. Run targeted consumers, changed-Python ruff and
  `git diff --check`. No commit, credentials, live session or routine work.
  Offline delivery: 152 focused passes; targeted consumers 242 passed, 56 socket-bind failures,
  87 PostgreSQL-DSN skips. Ruff/diff checks passed. Keep unchecked pending coordinator integration
  and environment/browser proof; exact blocked names and evidence: `.handoff/spec020-t055-20261028.md`.
  Coordinator integration 28/10/2026: 384 passed, 6 SQLite-only skips with real loopback and
  PostgreSQL. Live Chrome (Fioenix profile, Vietnamese UI): two Threads queries handed off through
  the encrypted receiver without opener, relay STAGED, submit ACCEPTED with two DEGRADED
  unsupported-locale outcomes and zero observations. English card parsing remains live-unverified.

- [X] T056 Implement language-independent deterministic Threads extraction, owner-approved
  28/10/2026. Evidence: `.handoff/spec020-vi-dom-capture-20261028.md` and the live-run note.
  Test first: nearest timestamp-anchor ancestor with at least four SVG buttons; preserve header,
  nav/aside, single timestamp, blocked-parent, identity and aware/nonfuture clock exclusions.
  Seed en/vi action labels in 037 through market_lexicons; prepare freezes database label data and
  injects it into tab_script, never label constants or positional kind guesses. Strip matched label
  only for parsing; support comma/dot K/M rounded counts, exact digits and unknown empty displays.
  Emit primary page locale; allow structural records in unseeded locales with unknown/null counters
  and an explicit unmeasured note. Preserve T054 unsupported/no-records and all measurement/empty
  rejections. Verify locale-independent attribution without changing it. Bump threads-search-top-v2
  in request/answer/mission paths; prove v1/v2 periods stay apart; regenerate baseline/manifests via
  prescribed scripts. Add seven-button Vietnamese fixture and en/vi/unknown/empty/prefix/TikTok/T055
  coverage. Update contract, research R12, data model and plan; skill replacement only if English-only
  wording exists. Run changed tests and traced consumers including migrations/packaging/conventions,
  ruff and diff checks. No commit, credentials, live browser or T055 transport changes. Keep unticked
  for coordinator acceptance; deterministic offline proof is not live readiness.
  Coordinator integration 28/10/2026: named migration 037 in the four public guides and their
  contract tests; 584 targeted passed with PostgreSQL and loopback, 184 doc/distribution passed.
  Live Chrome (Vietnamese UI): two queries, 20 HEALTHY observations via the T055 receiver, vi
  counters parsed (`Thích1,4K` rounded, plain digits exact, blank unknown), 20/20 identity-free
  links, zero stored `threads.com/@` rows. Repost-banner display-name risk remains live-unverified.

- [X] T057 Fix independent review findings on T053–T056, owner-approved release preparation
  28/10/2026. Test first: case-insensitive action-title and prefix matching in extractor/validator
  with lowercased operator-registered labels and verbatim raw display; shared market-vocabulary
  predicate for startup and registration, excluding action-label/attribution/template machinery;
  receiver base64url/39–1,000,000-character bounds and relay decoded length >28 before decrypt.
  Remove the unreachable Threads disjunct from the TikTok-only message branch; prove TikTok parity.
  Stage the full ignis-collect replacement from current `.agents` in
  `.handoff/spec020-skill/ignis-collect/SKILL.md`: close task-created tabs only after relay STAGED
  or submit, never immediately after posted:true; assert the rule and keep the section <=50 lines.
  Record review finding 2 as an accepted v0.9.0 structural-card/quoted-post limitation and follow-up
  in research.md and contracts/threads-search.md. Run changed tests and traced consumers, ruff and
  git diff --check; report RED then GREEN and unverified gates. No commit, credentials, live browser,
  repository lowercasing changes or other T055 transport changes. Leave unticked for coordinator acceptance.
  Coordinator integration 28/10/2026: skill copied (plus "a few seconds apart"), 645 passed and
  7 SQLite-only skips with PostgreSQL and real loopback; ruff and diff checks clean.

## Dependencies and execution order

```text
T001 → T002 → T003 SPIKE
                 ├─ STOP/inconclusive → owner review; T004–T052 blocked
                 └─ GO → T004–T008 foundation
                           → US1 tests/implementation T009–T027
                           → T028 automated host-path checkpoint
                           → US2 tests/retirement/flags T029–T039
                           → T040–T050 distribution/parity/review/final source verification
                           → T051 and T052 only with separate live authority
US3: deferred note only; no executable dependency or task
```

- Each test task precedes its corresponding implementation; new assertions must fail first. Retain
  test evidence rather than retrospectively claiming RED from a passing suite.
- Within Phase 2, T004/T005 can run together after spike GO; T006 precedes T007, T008 satisfies T004.
- Within US1, T009–T013 form a test-first batch on distinct file groups. T014–T020 are sequenced:
  service, validator, server and mission files overlap. T021/T022 validate those changes; T023/T024
  can then run together. T025/T026 follow their failing tests; T027/T028 close integration.
- T029/T030/T031 are independent test groups after T028; T032–T038 share dispatch/server/ingress
  consumers and run serially. T035 counts removal of the second ingress launch already done by T032.
- T040–T050 depend on T039; serialize migration tests, manifest tests and docs tasks when they edit
  the same files. T047 is required before claiming backend parity; a skip is not a pass.
- T051/T052 are independent live checks after offline readiness and their own separate approvals.
  Neither is prerequisite to drafting/reviewing the implementation; both remain required evidence
  before full acceptance. Approval of a manual run never approves a recurring G3 routine.

## Parallel examples

- Foundation: T004 model tests alongside T005 vocabulary/backend seed tests after T003 GO.
- US1: T010 DOM fixtures, T011 relay tests, T012 mission contracts and T013 privacy/backend tests
  can be authored together after T009; T023 pure period tests alongside T024 storage period tests.
- US2: T029 retirement, T030 launch-policy and T031 Reels classification test groups can run together
  after the host checkpoint; do not parallelize their shared-file implementations.
- US3: no parallel work; deferred.
- These are scheduling opportunities only, not authorization to spawn agents or alter other sessions.

## Implementation strategy

1. Establish local baseline and settle T003 first. If unchanged submit/cancel plus the approved
   source parameter cannot safely express composition, stop for owner review with concrete evidence.
2. MVP: Phases 1–3, a test-proven Threads host path, shared-run composition, privacy and FR-006
   periods. Validate independently at T028; do not call this a live-repaired or released channel.
3. Complete US2 only after that checkpoint: remove Threads internal collection and eight flags,
   preserve Reels and explicit unavailable reasons. Prove retained TikTok/Reels consumer parity.
4. Finish migration/resource packaging, schema/description regeneration, backend parity, review and
   targeted checks. Live acceptance remains two separately approved final tasks; no release/routine.

## Requirement coverage and task counts

| Requirement | Task coverage |
|---|---|
| FR-001/002; bounded relay/extractor | T003, T009–T012, T015–T019, T028 |
| FR-003; identity/vocabulary | T005–T007, T009–T010, T013–T014, T021–T022, T047, T051 |
| FR-004; clocks/counters/query/path | T004, T008–T010, T014–T015, T020, T023–T027 |
| FR-005; one signature change | T008, T012, T018, T043–T044, T048–T050 |
| FR-006/SC-005; channel and comparability | T019–T026, T047, T051; no API adapter required |
| FR-007/SC-003/004/006; retirement/flags/Reels | T029–T039, T050, T052; negative host cases T009–T012 |
| FR-008 / US3 | Deferred owner note in Phase 5; no task |
| FR-009; routine boundary | Rules, T046, T050–T052; no routine-change task |
| FR-010; both backends/seed only | T005–T007, T013, T022, T024, T040–T042, T047 |
| FR-011/SC-001/002; live host proof | T051, separately approved; fixture tests do not complete it |

| Phase | Tasks | Count |
|---|---|---|
| 1. Setup | T001–T002 | 2 |
| 2. Foundational | T003–T008 | 6 |
| 3. US1 | T009–T028 | 20 |
| 4. US2 | T029–T039 | 11 |
| 5. US3 deferred | None | 0 |
| 6. Polish/distribution/acceptance | T040–T052 | 13 |
| Total | T001–T052 | 52 |

Story-labelled tasks: US1 20, US2 11, US3 0. The 21 setup/foundation/final tasks are cross-cutting;
T051/T052 retain the story's separate live acceptance obligations without adding API work.

## Generation receipt and exclusions

Generated with `.agents/skills/speckit-tasks/SKILL.md` and `setup-tasks.sh --json`, which selected
this feature directory and the repository task template. Canonical workflow is the coordinator's
approved Obsidian-read copy at
`/private/tmp/claude-502/-Users-fioenix-Projects-fn-ignis/f0aadc59-078a-4b4a-b30e-d975708cce0e/scratchpad/coding-workflow.md`.
The explicitly selected phase and accepted depth gate settle routing; no evaluator call is needed
for activity selection. No supported session-title operation is exposed; no session renamed.
The source workflow's review-by date is 2026-10-21; this task explicitly designates that copy as
canonical, so the overdue metadata is disclosed without substituting another workflow.

No `.specify/extensions.yml` exists: before_tasks and after_tasks hooks are skipped. Agent-context
updates are explicitly skipped. Only this `tasks.md` is written; no tasks, implementation, tests,
migration, package installation, browser/account access, routine operation, release or commit run
as part of generation. Validation of this ledger establishes task format/scope, not feature readiness.
