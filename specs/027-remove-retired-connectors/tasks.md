# Tasks: Remove Retired Connector Code

Check `research.md` for file:line references before each task; line numbers are at `b2b6f35`.

- [x] T001 Delete `connectors/reels/`, its whole-file tests, and the Reels cases in mixed test files (FR-001, FR-006).
  - Kept `REELS_PAYLOAD` in `test_meta_browser_ingress.py`: the kept Threads cases in `test_registry.py` still feed it.
  - Kept the `ReelsPlugin` fixture in `integration/test_author_identity_conformance.py`: it is a stored-row payload
    shape, and the conformance scan only requires a fixture per live class.
  - Dropped the Reels `KNOWN_VOCABULARY_CONSTANTS` entry here rather than in T008, so the stale-entry test stays green.
- [ ] T002 Delete `connectors/google_trends/`, its whole-file tests and RSS cases; rewrite or delete
  `test_source_retirement.py::test_setup_diagnostics_never_probe_rss`; drop the `google_rss` label in
  `setup_bundle.py` (FR-001, FR-006, FR-008).
- [ ] T003 Narrow SC-004: `.coveragerc.sc004`, `test_t022_coverage_gate.py`, the `ci.yml` comment, and a dated note
  on `specs/001-core-storage-stable-ingress/spec.md` SC-004 (FR-007).
- [ ] T004 Delete `creative_center_plugin.py`, fix `connectors/tiktok/__init__.py`, delete its tests and cases; keep
  the old-row read paths (FR-001, FR-005).
- [ ] T005 Cut `TikTokPlugin` to the live members; `is_healthy` and `fetch_signals` refuse as `ThreadsPlugin` does;
  delete the whole-file tests and retired cases (FR-002, FR-006).
- [ ] T006 Remove orphans: `browser_support.py`, the Reels/Explore-only `meta_browser_ingress` helpers,
  `InstagramAuthManager` and `DEFAULT_INSTAGRAM_SCOPES`, unused auth managers, `fetch_suggestions_across_all` if it has
  no caller left (FR-003).
- [ ] T007 Remove the `INSTAGRAM_*` settings and the `.env.example` Instagram block, with tests and fixtures that name
  them (FR-004).
- [ ] T008 Update `test_repo_conventions.py` allowlists and `docs/PROJECT_REVIEW_CONTEXT.md`; check README, USER_GUIDE
  and AGENTS.md for claims that the removed code exists (FR-006, FR-009).
- [ ] T009 Verify SC-001–SC-004 with the plan's targeted commands; record results here.
