# Research: Threads Host Search and Path Integrity

Read-only trace of this checkout and provided G2, 2026-10-27. Spec 018 and Spec 012 plans were read
first. Decisions are design proposals under [Owner Gates](plan.md#owner-gates), not new approvals.

## R1. Reuse the submission lifecycle

- Decision: add prepare's source parameter and typed Threads staging; retain submit/cancel and 53
  tools. `HostBrowserSearchService`, validator, relay and `ingest_scope` already own task binding,
  expiry, replay, writer/frame guards and ingestion.
- Rationale: current domain enum, URLs, outward sanitizer, mission surface, relay origin/template
  and handoff resource are TikTok-specific. Changing the URL builder alone cannot safely add Threads.
- Alternatives considered: provider-specific tool (duplicates lifecycle and requires FR-005 amendment),
  Ignis OAuth (contradicts external-MCP ownership), generic import/relaxed CORS (widens trust), model
  transcription (violates deterministic ETL).
- Runtime prerequisite: prove actual supported tool-value transfer from the external MCP to the
  same-origin form and sibling-ticket composition before API activation. Do not assume browser
  tooling can receive arbitrary tool values; keep API activation pending if it cannot.

## R2. Extractor from G2

- Decision: `threads-search-top-v1`, exact `www.threads.com/search?q=...`, no filter variants.
  Anchor timestamp/post links and the smallest matching action-row ancestor; deduplicate post
  shortcode and `/media` links; read body separately, ISO `time[datetime]`, SVG-title action counters.
- Rationale: opaque classes and no stable test IDs/article were observed. Results virtualize;
  initial shell, loading and unchanged counts do not prove emptiness or exhaustion.
- Alternatives: TikTok selectors, whole-card text/alt-only captions, relative-date parsing, Recent/
  Profiles/video assumptions or unlimited scrolling lack G2 support. Initial scope is a bounded
  visible sample. Unsupported structure/locale is degraded; never improvise model extraction.

## R3. Identity and vocabulary

- Decision: reuse `resolve_source_identity` / `identity_free_source_url`; Threads shortcode link is
  `https://www.threads.com/t/<post-id>`, not an invented `/post/` URL. API numeric IDs and permalink
  shortcodes stay separate namespaces; only co-witnessed records may use the existing alias ledger.
- Rationale: G2 permalinks embed author handles. Spec 015 FR-005/006 already defines rebuilt links,
  `link unavailable` and separately counted context when no verifiable reference exists.
- Decision: seed `threads_attribution` with observed English `Photo by {author} on`; reuse generic
  attribution stripping before PII/mention cleanup, receipts and storage. Exclude header/avatar/
  profile and all media alt/accessibility content from extraction. Attribution can name a person
  other than the header; no raw copy may survive in metadata/errors. Missing/unsupported vocabulary
  fails closed; all-cleaned-empty becomes degraded.
- Alternatives: Python vocabulary constant, retain raw text for later sanitation, collect authors
  merely for voice counts: rejected. Use unknown author markers. Free-text personal-name removal
  remains Spec 015 FR-012's limitation, not an excuse for header/attribution leakage.

## R4. Counter precision and semantics

- Decision: retain kind/unit, raw display, nullable number and exact/rounded/unknown precision per
  counter. `1.4K` may normalize to 1400 only as rounded; absent text is unknown. Views were unobserved.
- Rationale: browser Like/Reply/Repost/Share does not establish quotes. Existing `channel_values`
  sums legacy likes/replies/reposts/quotes and has missing-insights zero heuristics; do not feed it
  invented views, Share-as-quotes or exact-looking rounded fields.
- Alternatives: fabricated exact total or hiding missing components rejected. Preserve components;
  incompatible/incomplete exact aggregate stays unknown. Both axis readers carry precision and
  sample limits, preserving old-path behavior except the new comparability gate.

## R5. Path identity: existing data and missing propagation

- Evidence: host validator already emits `collection_path=host_browser:tiktok-public-grid-v1`;
  mission mapper copies it into signal metadata and both stores persist observation metadata.
  Registry `SurfaceProbeResult` and collection plans have connector path/revision/tier.
  `execute_mission._persist_probe_outcomes` does not automatically copy these into persisted probe
  entities: `MissionProbeOutcome` has `scope_attestation` and plan digest, not path columns.
  Period use case drops provenance when creating `PeriodCoverage`/`SeenSnapshot`; source merging
  occurs before any path-comparability gate exists.
- Decision: normalized observation metadata plus existing probe attestation JSON (also on empty
  probes), propagated before merging. A plan digest alone is not a normalized path. No schema change.
- Legacy: `source=threads_browser_session`, `tier=TIER_1_BROWSER_SESSION` can prove a legacy path
  where actually stored; not every historical observation has normalized provenance. Read-time
  classification may use explicit metadata/matching persisted plan and record its basis. Otherwise
  unknown. Never infer from session presence/date or mutate old evidence.
- Alternatives: source-level latest metadata, assumed historical Playwright or a new migration
  column/backfill would erase lineage or violate FR-010.

## R6. Comparability

- Decision: per topic/channel/axis require one known identical path identity on each side, including
  revision/sampling semantics. Detect paths before dedup/merge, including created-view counter
  observations used after the period. Empty probes supply path even without an observation.
- Rationale: identical multi-path sets still hide changes within a period. Different, mixed,
  conflicting or unknown paths refuse with `collection_path_changed`, `collection_path_mixed`,
  `collection_path_unknown`; retain coverage/cadence/unjudged reasons. Failure is not a measured zero.
- Alternatives: majority/latest path, channel name alone, or seen-only gate would conceal changes.
  Do not refuse unaffected channels or alter ingestion/publication placement.

## R7. Eight launch sites and Threads consumers

Paths in this table are under `src/ignis/infrastructure/`.

| File | Launch symbol | Scope |
|---|---|---|
| `auth/meta_browser_auth.py` | `MetaBrowserAuthManager.authenticate_interactive` | Shared auth; remove flag, retain compatibility. |
| `auth/tiktok_auth.py` | `TikTokAuthManager.authenticate_interactive` | Keep login without flag. |
| `connectors/meta_browser_ingress.py` | `collect_json_payloads` | Keep Reels; remove Threads dispatch/callers and flag. |
| same | `collect_threads_search_suggestions_via_browser` | Retire Threads-only collection helper. |
| `connectors/tiktok/tiktok_plugin.py` | `fetch_suggestions` | Keep without flag. |
| same | `fetch_video_comments` | Keep without flag. |
| same | `_fetch_via_playwright` | Keep without flag. |
| `connectors/tiktok/creative_center_plugin.py` | `fetch_macro_trends` | Keep without flag. |

Runtime consumer trace:

- `connectors/threads/threads_plugin.py`: `resolve_auth_tier`, `resolve_ingest_runtime`, `is_healthy`,
  `_browser_storage_state`, `fetch_signals` including OWN_PROFILE, `search_signals`,
  `_search_via_browser_session`, `_fetch_via_browser_session`, `fetch_trending_topics`,
  `fetch_search_suggestions`, `_fetch_legacy_public`. Retire Playwright plus disable cookie GraphQL,
  internal OAuth and legacy collection fallback. Stored cookies must not admit public collection.
- `interfaces/mcp/server.py`: `_init_components`, Threads authenticate/status/clear, trending and
  suggestions handlers/tools, `_probe_threads_keyword_search`, credential diagnostics. Keep public
  signatures; unsupported collection returns explicit unavailable, not empty lists as measured zero.
  Stop recommending retired browser login as a public-search remedy.
- `connectors/registry.py`: health, admission/runtime requirements, search, retries, provenance.
  Submitted Threads replaces its surface only within the authorized run; no cookie/API fallback.
- `harness/refinement_orchestrator.py`: credential mapping must not imply public-search grant.
  `auth/self_identity.py`, `auth/__init__.py`: preserve self-exclusion, export/auth-clear compatibility.
- `connectors/meta_browser_ingress.py`, `config/runtime_config_manager.py`: shared GraphQL config/
  cache helpers; preserve Reels and blocked-page classification rather than deleting shared code.
- `application/use_cases/host_browser_mission.py`, `execute_mission.py`, `execute_mission_follow_up.py`,
  `infrastructure/follow_up_root_composition.py`, `follow_up_caller_activation.py`: requirements,
  writer, frame/path/revision guards; no resumed historical mission or recurring work.
- `application/use_cases/watchlists.py`, `watchlist_period.py`, `domain/watchlist_period.py`:
  run composition, topic query matching, both axes and legacy trending exclusion.
- `infrastructure/harness/quality_evaluator.py`: host-path publication checks must respect actual
  Threads datetime, never replace it with capture or assume publication unmeasured.

## R8. Existing and new tests

Files below are under `tests/unit/` unless prefixed `integration/` (then under `tests/`). These are
implementation change/targeted-parity candidates; only cases affected by traced edits should change.

| Area | Existing consumer files |
|---|---|
| Threads retirement | `test_threads_relay_search.py`, `test_threads_direct_graphql.py`, `test_threads_plugin.py`, `test_threads_graph_ingress.py`, `test_threads_keyword_search_access.py`, `test_threads_keyword_search_authority.py`, `test_threads_mcp_tools.py`, `test_bug03_threads_empty_status.py` |
| Meta/Reels shared paths | `test_meta_browser_ingress.py`, `test_meta_browser_auth.py`, `test_cookie_scope.py`, `test_docid_sniffer_dedupe.py`, `test_runtime_config.py`, `test_instagram_mcp_tools.py` |
| Registry/health | `test_social_search_integrity.py`, `test_registry.py`, `test_round3_regressions.py`, `test_insights_ttl_cache.py`, `test_source_map_matches_connectors.py`, `test_connector_daily_ceiling.py` |
| Caller/auth | `test_caller_platform_sessions.py`, `test_caller_analysis_composition.py`, `test_caller_relay_read_composition.py`, `test_credential_clear_wording.py` |
| TikTok launch consumers | `test_tiktok_auth.py`, `test_tiktok_suggestions.py`, `test_tiktok_comments.py`, `test_tiktok_plugin.py`, `test_tiktok_creative_center.py`, `test_tiktok_health_probes.py` |
| Host lifecycle | `test_host_browser_search.py`, `test_host_browser_relay.py`, `integration/test_host_browser_extractor.py`, `integration/test_host_browser_mission.py`, `integration/test_host_browser_search_mcp.py` |
| Identity/vocabulary | `test_pii_sanitization.py`, `test_identity_free_mcp_responses.py`, `test_source_identity.py`, `test_vocabulary_loader.py`, `test_market_lexicons.py`, `integration/test_author_identity_conformance.py`, `integration/test_author_identity_pipeline.py`, `integration/test_author_identity_parity.py`, `integration/test_source_identity_alias_ledger.py`; fixture `tests/fixtures/author_identity_sentinels.py` |
| Periods | `test_watchlist_period.py`, `test_watchlist_seen_axis.py`, `integration/test_watchlist_period_storage.py`, `integration/test_watchlist_mcp.py` |
| Composition | `integration/test_all_connectors.py`, `integration/test_t022_operational_surface_parity.py`, `integration/test_clean_user_journey.py`, `integration/test_ingest_orchestration.py` (affected mocked-network cases) |

New planned files, unique basenames across unit/integration:

- `tests/unit/test_threads_host_answer_validation.py`: URL/source/version/time/limits, attribution,
  missing locale, all-cleaned-empty, API grant/SELF_ONLY, stale/replay/identity rejection.
- `tests/unit/test_collection_path_comparability.py`: both axes, different/mixed/unknown/conflicting/
  equal paths, zero probes and created counter-window path changes.
- `tests/unit/test_browser_launch_flag_policy.py`: static no-evasion check plus mocked launch args
  at each retained site; removed helper has no executable caller. Current tests do not cover all args.
- `tests/integration/test_threads_host_dom_contract.py`: G2 synthetic DOM, action/time/body structure,
  quote/carousel/media dedup, virtualized sample, sidebars/author exclusion and malformed/blocked page.
- `tests/integration/test_meta_host_evidence_backend_parity.py`: both-backend receipts, metadata/
  attestation round-trip, no identity, alias co-witness, precision/path periods, stale guards,
  sibling-source single-writer composition and missing-sibling rejection.

PostgreSQL parity: use existing `tests/integration/conftest.py` fixtures and approved injected
`IGNIS_TEST_POSTGRES_DSN`, never read/print its value. Cover seed-only idempotence, zero evidence
updates, clocks, sanitized observation/association round-trip, empty-probe path, both-axis refusal,
caller/writer/frame boundaries and query dedup once/topic. A skipped backend is pending, not parity.
FR-011/SC-001 require actual Ignis-to-host live G3 run/readback, SC-002 identity scan and SC-006 real
flag-free Reels result; fixtures/manual G2 do not satisfy these. See quickstart for separate authority.

## R9. Inventories and packaging

- Schema consumers: `hermes_manifest.json`, `.hermes/tools.json`; prescribed generator
  `scripts/sync_tool_manifests.py`; source `src/ignis/interfaces/mcp/server.py`.
- Count/name/schema contracts: `openclaw.json` (53), `scripts/wheel_mcp_smoke.py`, unit
  `test_tool_manifests_drift.py`, `test_public_mcp_contract.py`, `test_public_distribution_contract.py`,
  `test_public_doc_conventions.py`; integration `test_host_browser_search_mcp.py`,
  `test_clean_user_journey.py`, `test_concurrent_stdio_clients.py`. Count stays 53; optional source
  still requires schema regeneration. No version bump.
- Catalog/guidance consumers: README variants, user-guide variants, `BACKLOG.md`, packaged collection
  guide, `.agents/skills/ignis-collect/SKILL.md`; `AGENTS.md`/`CLAUDE.md` carry count claims. None edited
  during planning; future context-file sync requires separately scoped authority.
- Migration 036: SQLite `_ensure_schema` seed replay; vocabulary loader domain/model/sync and
  packaged tactical seed; PostgreSQL SQL chain; integration `conftest.py`, `test_compose_init.py`;
  unit `test_sql_packaging.py`, `test_public_distribution_contract.py`; README/user-guide migration
  endpoint lines. JS/SQL package resources via `pyproject.toml`; verify actual installed wheel.

## R10. Workflow, research limits and open implementation gates

Canonical source: coordinator copy
`/private/tmp/claude-502/-Users-fioenix-Projects-fn-ignis/f0aadc59-078a-4b4a-b30e-d975708cce0e/scratchpad/coding-workflow.md`.
Route: installed `.agents/skills/speckit-plan/SKILL.md`, Phase 0/1 only. One read-only research child,
inherited configuration; no implementation delegation. No context telemetry/title operation exposed.
`setup-plan.sh --json` resolves correct directory but returns feature-key branch
`020-meta-host-browser-search`; actual Git branch is `claude/meta-host-browser-spec`. No rename.
No extensions file exists, so pre/post hooks are skipped. Agent-context update explicitly skipped.
No relevant Spec 020 memory result was used as design evidence.

TypeSafe skill loaded for potential claim alignment. Live citation-check cookbook was inaccessible;
no callable Jev evaluator/budget established, no validated response and no Jev claim. Exact local
source/schema tracing and policy-settled routing proceed; optional semantic assurance is unvalidated.
No external MCP code/API schema/grant was inspected, so the API adapter contract is proposed and
requires actual capability/transport proof, not invented operation fields or approval.
No browsers, credential files, live databases, migration, routine or wheel execution during planning.
Research resolves design choices as proposals; external grant and transport/multi-source proof are
explicit runtime gates, not unanswered product Clarifications or claims that the feature is repaired.

## Planning verification (2026-10-27)

- `PYTHONPATH="$PWD/src" /Users/fioenix/Projects/fn-ignis/.venv/bin/pytest -q -p no:cacheprovider tests/unit/test_repo_conventions.py`: **11 passed in 2.73s**. Existing static conventions only, not feature behavior.
- Six generated artifacts: local Markdown targets resolve, template placeholders absent, whitespace
  clean; five proposed new test basenames do not collide with current unit/integration files.
- Git branch verified as `claude/meta-host-browser-spec`; only the six new feature documents are
  present as changes. Original spec/G2, source, tests, configuration and context files are unchanged.
- No feature tests, PostgreSQL, installed wheel, actual relay transport, API grant or live-run proof.
  No full suite, tasks generation, implementation, commit, routine update or agent-context update.


## R11. Threads same-tab encrypted fragment (owner decision, 28/10/2026)

- Live facts supplied by the owner/coordinator (not repeated in this implementation): signed-in
  Chrome `threads.com/search` sends `Cross-Origin-Opener-Policy: same-origin-allow-popups` and a
  relay-opened Threads tab has `window.opener === null`. Scripted `window.open` returns null
  without a user gesture. Scripted `location.replace` to a loopback URL with a 20,000-character
  fragment preserves that fragment; BroadcastChannel exists on the receiver origin. TikTok's
  opener handoff staged and accepted 10 records and remains unchanged.
- Decision: amend the opener-loss prohibition for Threads only. Encrypt `{kind, request_id, answer}`
  with AES-GCM using a random 256-bit ticket key and fresh 96-bit IV, base64url encode
  `iv||ciphertext`, then navigate the same tab to the exact relay receiver. A 1,000,000-character
  fragment bound is checked before navigation; the 100 ms timer allows status/counts to return.
  The live probe established 20,000 characters only; the larger configured ceiling needs browser
  acceptance testing and is not a claim that all browsers accept a URL of that size.
- Privacy: transient Threads source URLs contain author handles before server validation. Plaintext
  history fragments would violate the intended at-rest boundary. URLs/history therefore carry
  ciphertext only; key material lives in `tab_script` and main relay data, never in the receiver,
  URL, log or another MCP response field. Task-end tab cleanup remains mandatory; browser memory
  and supported host tool-value retention are outside server erasure guarantees.
- Receiver: Threads-only exact GET `<token path>receive`, static nonce-CSP, no external resources,
  no-store/no-referrer. Read and immediately clear the hash before broadcasting the raw fragment
  on `ignis-host-answer:<request_id>`; no decryption or record rendering. The main relay decrypts,
  validates the binding/limits and first answer, and stages the unchanged complete envelope once.
  Tampered, malformed, wrong-binding, duplicate and late messages cannot change accepted state.
- Rejected alternatives: popup (observed blocked); manual Stage-answer as the default (requires
  full-envelope value transfer, brittle and not automatic); CORS/fetch to loopback (widens the
  network trust boundary); window.name (persists plaintext across navigation and browser behavior
  is not an established transport). Plaintext fragments are rejected for history privacy.
- Impact: no dependencies, signatures, database changes or collection/extractor behavior changes.
  Validator, staging/rejection/lifetime/shutdown and TikTok opener transport remain authoritative.
  Deterministic tests are offline evidence; live Chrome, actual navigation limits and end-to-end
  staging remain coordinator checks. This decision does not complete T051 or T052.


## R12. Language-independent Threads extraction (T056, owner-approved 28/10/2026)

Evidence: `.handoff/spec020-vi-dom-capture-20261028.md`, supplied live statistics from 11 visible
posts, `lang=vi`, exact UTC timestamp anchors. The nearest ancestor with at least four SVG-bearing
buttons held seven controls: two follow controls, more, then the four actions. Vietnamese SVG titles
were `Thích`, `Trả lời`, `Đăng lại`, `Chia sẻ`; non-SVG text included label-prefixed integers,
comma-decimal K and label-only unknowns. Avatar alt starts `Ảnh đại diện`. Post-image alt remains
English `Photo by <name> on <date>` under vi; the 036 template matched all 11 observed images.
These are supplied capture facts, not a new live check by this implementer.

This decision supersedes R2's locale limitation and R4's original numeric grammar.

Decision: detect cards structurally from timestamp anchors and the nearest ancestor holding at
least four visible SVG buttons; preserve header/nav/aside/single-timestamp/blocked-parent and clock
exclusions. Keep excerpt extraction unchanged. No agent-read measured extraction: deterministic
packaged ETL preserves comparability, identity control and cost. No positional action mapping.

Use existing `market_lexicons`, domain `threads_action_labels_<locale>`, category `<kind>`, term
as the exact SVG title, seeded en/vi in 037. This fits vocabulary rows and existing registration/
repository/bootstrap paths better than an opaque runtime-config JSON document. Exclude this
machinery domain prefix from relevance terms. The locale domain suffix preserves the existing
unique(domain, term) key when two languages share an identical title. Mission prepare reads its
caller database; tactical retains
Spec 012's no-caller-store/no-auth initialization boundary by executing the packaged seed in an
isolated SQLite memory table and reading its rows. Each ticket freezes the map for both extractor
injection and validation. An operator-added locale is available to mission prepare; tactical gains
locales through shipped seed rows. No Python or JavaScript label constants, dependencies or transport
changes. Missing labels leave counters unknown without discarding structurally verified records.

Use the page primary language subtag as answer.locale; unusable lang preserves T054 unsupported /
DEGRADED / unverified / no-records behavior. Unknown-but-valid locales retain records with explicit
unmeasured-counter notes. Strip only the matching leading label before numeric parsing; preserve
raw display; K/M with comma/dot decimal stays rounded, digits exact, empty unknown. Validator checks
the same grammar/value/precision and rejects every incompatible measurement or Threads empty claim.

Attribution trace: service source-specific templates → validate_answer → strip_platform_attribution
→ PII/mention cleanup → sanitized receipt / mission author policy / storage. Selection is by source,
never UI locale. Extractor excludes img/svg/header and accessible media content. Leave 036 and the
sanitizer unchanged. Existing free-text-person-name limits remain.

Bump to threads-search-top-v2 in envelopes and mission path descriptors so v1/v2 periods refuse
comparison. Preserve historical v1 fixtures; add explicit two-axis v1/v2 rejection. Regenerate
baseline/manifest artifacts only with their prescribed scripts; unchanged output is expected because
those fixtures cover legacy TikTok/public input schemas, not the Threads extractor revision.
Live language/card/counter/receiver acceptance remains coordinator-owned; no live session is used.
