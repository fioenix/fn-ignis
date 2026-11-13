# Tasks: Remove Retired Connector Code

Check `research.md` for file:line references before each task; line numbers are at `b2b6f35`.

- [x] T001 Delete `connectors/reels/`, its whole-file tests, and the Reels cases in mixed test files (FR-001, FR-006).
  - Kept `REELS_PAYLOAD` in `test_meta_browser_ingress.py`: the kept Threads cases in `test_registry.py` still feed it.
  - Kept the `ReelsPlugin` fixture in `integration/test_author_identity_conformance.py`: it is a stored-row payload
    shape, and the conformance scan only requires a fixture per live class.
  - Dropped the Reels `KNOWN_VOCABULARY_CONSTANTS` entry here rather than in T008, so the stale-entry test stays green.
- [x] T002 Delete `connectors/google_trends/`, its whole-file tests and RSS cases; rewrite or delete
  `test_source_retirement.py::test_setup_diagnostics_never_probe_rss`; drop the `google_rss` label in
  `setup_bundle.py` (FR-001, FR-006, FR-008).
  - Rewrote `test_setup_diagnostics_never_probe_rss` without the plugin import: it now asserts the diagnostics
    result and `setup_bundle.py` carry no `google_rss` key.
  - `test_t022_coverage_gate.py` goes red at this commit alone (its RSS witness file is gone) and green again with
    T003; the two commits stay separate to keep one task per commit.
  - Kept the `google_rss` surface name in `test_data_provenance.py`, `test_surface_boundaries.py` and
    `test_public_distribution_contract.py`: those are stored-row or fake-diagnostic data, not plugin code.
- [x] T003 Narrow SC-004: `.coveragerc.sc004`, `test_t022_coverage_gate.py`, the `ci.yml` comment, and a dated note
  on `specs/001-core-storage-stable-ingress/spec.md` SC-004 (FR-007).
- [x] T004 Delete `creative_center_plugin.py`, fix `connectors/tiktok/__init__.py`, delete its tests and cases; keep
  the old-row read paths (FR-001, FR-005).
  - Dropped the Creative Center `SRC_NON_ASCII_ALLOWLIST` entry here so the stale-entry test stays green.
  - Kept the `TikTokCreativeCenterPlugin` and `GoogleTrendsRssPlugin` fixtures and `AUTHOR_FREE_CONNECTORS` in
    `integration/test_author_identity_conformance.py`: stored-row payload shapes, harmless to the class scan.
- [x] T005 Cut `TikTokPlugin` to the live members; `is_healthy` and `fetch_signals` refuse as `ThreadsPlugin` does;
  delete the whole-file tests and retired cases (FR-002, FR-006).
  - Kept `name` ("TikTok Trending & Search Ingress") unchanged: it is an output label, and renaming it is not in scope.
  - Added `test_retired_tiktok_collection_refuses_like_threads` for the new refusals.
  - Kept the loader assertion of `test_the_retired_live_term_does_not_come_back_through_the_database`; only its plugin
    half went.
- [x] T006 Remove orphans: `browser_support.py`, the Reels/Explore-only `meta_browser_ingress` helpers,
  `InstagramAuthManager` and `DEFAULT_INSTAGRAM_SCOPES`, unused auth managers, `fetch_suggestions_across_all` if it has
  no caller left (FR-003).
  - Removed `browser_support.py`, `InstagramAuthManager`, `DEFAULT_INSTAGRAM_SCOPES`, `InstagramBrowserAuthManager` (no
    live code constructs or types it) and `registry.fetch_suggestions_across_all`, with their tests. Base-class tests
    in `test_meta_browser_auth.py` and the `meta_auth` launch site now use `ThreadsBrowserAuthManager`.
  - Kept `meta_browser_ingress.py` unchanged: `collect_json_payloads` (Threads refusal, `test_threads_relay_search.py`),
    `extract_records` (kept helper test) and `build_cookie_header` (used by `extract_token_from_storage`) all still
    have a kept test or live path.
  - Kept `TikTokAuthManager`: the live `TikTokPlugin` types it.
  - Kept the `instagram`/`instagram_browser` keys in `server.py` `_PLATFORM_CREDENTIAL_KEYS`: they read stored rows.
- [ ] T007 Remove the `INSTAGRAM_*` settings and the `.env.example` Instagram block, with tests and fixtures that name
  them (FR-004).
- [ ] T008 Update `test_repo_conventions.py` allowlists and `docs/PROJECT_REVIEW_CONTEXT.md`; check README, USER_GUIDE
  and AGENTS.md for claims that the removed code exists (FR-006, FR-009).
- [ ] T009 Verify SC-001–SC-004 with the plan's targeted commands; record results here.
