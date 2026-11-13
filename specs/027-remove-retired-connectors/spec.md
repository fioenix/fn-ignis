# Feature Specification: Remove Retired Connector Code

**Feature Branch**: `027-remove-retired-connectors`

**Created**: 2026-11-13

**Status**: Clarified 2026-11-13. Plan and tasks accepted.

**Input**: BACKLOG ENG-2, "Gỡ code connector đã nghỉ": Reels, Google Trends RSS, the Explore branch and the
headless search of `TikTokPlugin`; delete their tests and narrow the SC-004 coverage scope. Owner request in chat
2026-11-13 ("Cài wheel rồi ENG-2").

## Outcome and audience

Specs 020–022 retired these sources: no tool reaches them and no registration loads them, but about 3,000 lines of
their code and their tests still ship in `src/`. Reviewers and agents misread them as live (a reviewer had to check
whether `get_tiktok_video_comments` belonged to the retired headless branch). After this change, `src/` holds only
code a live path can reach, stored rows from retired sources still read as before, and the MCP surface is unchanged.

## Clarifications

### Session 2026-11-13

- Q: Remove `InstagramAuthManager` (Reels OAuth in `meta_oauth.py`) and the five `INSTAGRAM_*` settings and their
  `.env.example` block? → A: Yes. Only the Playwright Reels plugin used them; Instagram through the host browser does
  not. `ThreadsAuthManager` stays (owner decided, chat 2026-11-13; the AGENTS.md §8 connector-tier gate).
- Q: How far does the removal go? → A: The ENG-2 list plus code that becomes orphaned by it: `browser_support.py`,
  the `meta_browser_ingress.py` helpers only Reels or the TikTok Explore probe used, and auth managers no live code
  constructs. `ThreadsPlugin` (the registered host-required compatibility port) and its `ThreadsAuthManager` stay, as
  do the existing `sql/` seed files (owner decided, chat 2026-11-13).
- Q: Who implements? → A: Antigravity (`gemini-3.8-flash-high`) after a fresh quota check: Codex is out until
  2026-11-17 10:16, the Argon pool is empty and the Claude/GPT pool is at 11%. Claude reviews (owner asked to check
  quota and assign accordingly, chat 2026-11-13).
- Q: Spec 001 SC-004 names the RSS Plugin in its coverage scope. → A: Narrow the scope to Repository, YouTube Plugin
  and Registry; BACKLOG ENG-2 already calls for it (agent decided; basis: BACKLOG ENG-2).
- Q: Seed rows in `sql/012` and `sql/013` that only retired plugins read? → A: Keep. Editing applied migrations is
  out of scope; the vocabulary loader may still group them (agent decided; basis: Spec 022 assumptions, AGENTS.md §8
  "migrations that transform persisted evidence").

## Functional requirements

- **FR-001**: Delete `connectors/reels/`, `connectors/google_trends/` and `connectors/tiktok/creative_center_plugin.py`.
- **FR-002**: `TikTokPlugin` keeps only what `get_tiktok_video_comments` and the component wiring use: `__init__`,
  `set_auth_manager`, `platform`, `plugin_id`, `name`, `resolve_ingest_runtime`, `canonical_comment_video_url`,
  `fetch_video_comments`. The abstract `is_healthy` and `fetch_signals` become refusals in the style of
  `ThreadsPlugin`. Explore, headless search, suggestions, UI-noise and suggest-template members and the parsers go.
- **FR-003**: Delete code orphaned by FR-001–FR-002: `connectors/browser_support.py`; the `meta_browser_ingress.py`
  functions with no remaining live consumer, keeping `caption_text` and `coerce_int` (used by `ThreadsPlugin`) and
  anything else a live path or kept test still needs; `InstagramAuthManager`, `DEFAULT_INSTAGRAM_SCOPES`; auth
  managers (`TikTokAuthManager`, `InstagramBrowserAuthManager`) only when no live code constructs or types them.
- **FR-004**: Remove the `INSTAGRAM_*` settings from `config.py` and the Instagram block from `.env.example`, with
  every test or fixture that names them.
- **FR-005**: Keep `PlatformType` values, `RETIRED_CONNECTOR_SURFACES`, the read paths for old rows (for example
  `metadata.source == "tiktok_creative_center"`), `ThreadsPlugin`, `ThreadsAuthManager`, `sql/` files, and every MCP
  tool: the catalog stays at 41 with unchanged signatures.
- **FR-006**: Delete tests that only exercise removed code; in mixed test files remove only the retired cases. Update
  the repository allowlists (`test_repo_conventions.py`) that name removed files.
- **FR-007**: Narrow SC-004: `.coveragerc.sc004`, `tests/unit/test_t022_coverage_gate.py` and the CI comment drop the
  RSS Plugin; Spec 001's SC-004 line records the narrowing with a dated note.
- **FR-008**: `setup_bundle.py` stops printing the dead `google_rss` diagnostic label.
- **FR-009**: Documentation that describes the removed code as present is updated; history stays.

## Success criteria

- **SC-001**: No file under `src/` imports or defines a removed unit; `rg` for `ReelsPlugin`, `GoogleTrendsRssPlugin`,
  `TikTokCreativeCenterPlugin`, `InstagramAuthManager`, `browser_support` and `INSTAGRAM_` in `src/` finds nothing.
- **SC-002**: The MCP catalog lists 41 tools with signatures equal to `main` before the change.
- **SC-003**: `get_tiktok_video_comments`, host-browser search and the reads of stored retired-source rows behave as
  before: their existing tests pass unchanged.
- **SC-004**: The targeted tests of every touched module pass, and the SC-004 coverage gate passes on its narrowed scope.
