# Research: consumer map at `b2b6f35` (2026-11-13)

Read-only scoping. Line numbers are at `b2b6f35`; re-check before editing.

## Retired units and consumers

**Reels** — `connectors/reels/reels_plugin.py` (742 lines). Not registered (`server.py:804-806` registers only
`ThreadsPlugin` and, with a key, `YouTubeDataPlugin`). Imports `InstagramAuthManager`, `InstagramBrowserAuthManager`,
`InsightsTTLCache`, and `build_cookie_header`, `caption_text`, `coerce_int`, `collect_json_payloads`,
`extract_records` from `meta_browser_ingress`; reads `settings.INSTAGRAM_USER_ID`, `INSTAGRAM_API_VERSION`.
- Whole test files: `tests/unit/test_reels_plugin.py`, `tests/unit/test_reels_graph_ingress.py`,
  `tests/integration/test_all_connectors.py`.
- Mixed: `test_meta_browser_ingress.py` (7 `test_reels_*` cases and `REELS_PAYLOAD`, imported by
  `test_registry.py:629`), `test_registry.py` (Reels parameter cases near 644, 683, 774; Threads cases stay),
  `test_social_search_integrity.py` (Reels cases at 160, 187), `test_cookie_scope.py:88` (instagram case),
  `test_insights_ttl_cache.py:145`, `test_pii_sanitization.py:152` (Reels half).
- `test_repo_conventions.py:44` allowlists `(reels_plugin.py, "BROWSER_API_MARKERS")`; the stale-entry test fails
  if it stays. `integration/test_author_identity_conformance.py:91` has a `"ReelsPlugin"` fixture (one-directional).
- Docs: `docs/PROJECT_REVIEW_CONTEXT.md:367`.

**Google Trends RSS** — `connectors/google_trends/` (`rss_plugin.py`, 277 lines). No src consumer.
- Whole test files: `test_google_trends_rss.py`, `test_google_suggestion_integrity.py`, `integration/test_all_connectors.py`.
- Mixed: `test_generalization.py:24,40`, `test_vocabulary_loader.py:73` (RSS half of
  `test_a_fresh_database_arms_both_engines`), `test_source_retirement.py:205` (`test_setup_diagnostics_never_probe_rss`
  imports the plugin; rewrite as a text check or delete).
- Coverage: `.coveragerc.sc004:3-5,20,39-42`; `tests/unit/test_t022_coverage_gate.py:33-45,83,99,184`;
  `.github/workflows/ci.yml:213-229` comment. Criterion text: `specs/001-core-storage-stable-ingress/spec.md:135`.
- CLI: `src/ignis/interfaces/cli/setup_bundle.py:400` prints `diag.get('google_rss')` (dead label).

**Creative Center** — `connectors/tiktok/creative_center_plugin.py` (293 lines).
- `connectors/tiktok/__init__.py:2,4` re-exports it (must edit).
- Whole test file: `test_tiktok_creative_center.py`. Mixed: `test_tiktok_health_probes.py`,
  `test_browser_launch_flag_policy.py:14,73,101`, `integration/test_follow_up_sqlite_admission.py:1005` ("creative"
  and "grid" parameters use retired plugin ids).
- `test_repo_conventions.py:38` allowlist entry. `integration/test_author_identity_conformance.py:79,106`.
- Keep the old-row read paths: `server.py:2619`, `scripts/generate_sample_case_studies.py:119`,
  `tests/fixtures/decision_grade_evidence.json`, `integration/test_source_retirement_storage.py:25`.

**TikTokPlugin retired members** (`connectors/tiktok/tiktok_plugin.py`, 943 lines): `EXPLORE_URL`,
`SEARCH_BASE_URL`, `VIDEO_URL_PATTERN`, `JSON_*`, UI-noise and suggest-template state, `register_suggest_templates`,
`_intent_probe_templates`, `register_ui_noise`, `is_healthy` (Explore probe), `_is_private_or_notification`,
`keyword_search_blocked_reason`, `fetch_signals`, `search_signals`, `fetch_suggestions`,
`_fetch_suggestions_http_fallback`, `_matches_search_query`, `_fetch_via_playwright`, `_parse_json_item`,
`_parse_dom_card`; imports `build_cookie_header` and `browser_support` used only by `is_healthy`.
- Live members: `__init__`, `set_auth_manager`, `platform`, `plugin_id`, `name`, `resolve_ingest_runtime`,
  `canonical_comment_video_url`, `fetch_video_comments`. Live consumers: `server.py:105,804,893,3235-3241`.
- `IConnectorPlugin` (`application/ports/connector_port.py:55-121`) declares `platform`, `name`, `is_healthy`,
  `fetch_signals` abstract: keep refusals as `ThreadsPlugin:59-79` does.
- Whole test files: `test_tiktok_plugin.py`, `test_tiktok_suggestions.py`. Mixed: `test_social_search_integrity.py`
  (36, 107, 121, tiktok case of 139), `test_host_metric_missingness.py:25,38`, `test_vocabulary_loader.py:127,147`,
  `integration/test_tiktok_ui_noise_retirement.py:124,157` (seed and migration tests stay), `test_cookie_scope.py:88`
  (tiktok case), `test_browser_launch_flag_policy.py` (`LAUNCHES` entries and sites "suggestions", "search",
  "creative", "meta_capture").
- Live tests to keep green: `test_tiktok_comments.py`, `test_identity_free_mcp_responses.py`,
  `test_source_retirement.py:107`, `test_caller_analysis_composition.py:32` (patches `server.TikTokPlugin`).

**`follow_up_provider_bridge.py:375`** — `HostBoundYouTubePlugin.search_signals`; touches no retired code.

## Orphaned by the removal

- `connectors/browser_support.py`: only consumers are Creative Center and `TikTokPlugin.is_healthy`; its tests are
  `test_tiktok_health_probes.py:119,126`.
- `meta_browser_ingress.py` (616 lines): the only live src consumer is `threads_plugin.py:14` (`caption_text`,
  `coerce_int`). Reels used `collect_json_payloads`, `extract_records`, `build_cookie_header`. Symbols with no src
  consumer but covered by Threads-era tests (`GraphQLDocIdCache`, `get_threads_*`, `extract_token_from_storage`,
  `fetch_graphql_direct`, `extract_trending_topics`, `extract_search_suggestions`, `walk_dicts`,
  `_parse_count_label`) belong to the Threads port and stay in this change (owner scope).
- `InstagramAuthManager` (`auth/meta_oauth.py:576-596`), `DEFAULT_INSTAGRAM_SCOPES` (`:25`), `auth/__init__.py:7,12`,
  `test_threads_oauth.py:322,330`, the note at `meta_oauth.py:365`.
- `TikTokAuthManager` (`auth/tiktok_auth.py`), `InstagramBrowserAuthManager` (`meta_browser_auth.py`): constructed only
  by retired plugins; `ThreadsBrowserAuthManager` is typed by `ThreadsPlugin` — check before removing anything.
  `test_caller_platform_sessions.py:17` asserts auth managers are absent from the server; keep it green.
- `registry.fetch_suggestions_across_all` (`registry.py:845-866`): no src caller; only `test_registry.py:247`.

## Settings and environment

- `config.py:94-98` `INSTAGRAM_USER_ID`, `INSTAGRAM_APP_ID`, `INSTAGRAM_APP_SECRET`, `INSTAGRAM_REDIRECT_URI`,
  `INSTAGRAM_API_VERSION`. Named also in `tests/conftest.py:19`, `test_settings_do_not_leak_secrets.py:22`,
  `integration/test_follow_up_settlement.py:201,250,689,743`, `tests/fixtures/meta_host_browser_baseline/capture.py:27`.
- `.env.example:34-44` Instagram block ("for Reels ingress"). `META_INSIGHTS_CACHE_TTL_SECONDS` stays (Threads uses
  `InsightsTTLCache`); it is pinned in `test_env_example_matches_settings.py:18`.

## Keep

`PlatformType.GOOGLE_TRENDS`, `PlatformType.REELS` (host-browser Instagram uses `platform="reels"`),
`RETIRED_CONNECTOR_SURFACES` (`domain/research_workspace.py:170-172`), `sqlite_repository.py:158`,
`watchlist_period.py`, `source_identity.py`, `self_identity.py`, every `sql/` file, the `_PLATFORM_CREDENTIAL_KEYS`
map and the `clear_platform_auth` / `get_platform_auth_status` tools (they read stored rows, not classes).
