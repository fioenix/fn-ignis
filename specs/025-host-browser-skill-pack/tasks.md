# Tasks: Host-Browser Skill Pack and Instagram Reels Through the Host Browser

**Input**: `specs/025-host-browser-skill-pack/` (spec.md, plan.md, research.md, data-model.md, contracts/, quickstart.md)

**Tests**: included. The repository works test-first (`fnl-coding-router`: a behaviour change starts from a
failing test), and SC-001..SC-003 need live acceptance runs.

**Format**: `- [ ] [ID] [P?] [Story] Description with file path`. `[P]` = can run in parallel (different
files, no dependency on an unfinished task).

## Phase 1: Setup

- [ ] T001 Confirm the running MCP server is a wheel install with packaged `host_browser/*.js` (memory: plain `uv sync`/`uv run` breaks it); record the check command in `specs/025-host-browser-skill-pack/quickstart.md`

## Phase 2: Foundational (blocks every story)

**Goal**: one per-source descriptor replaces the binary `threads`/`tiktok` branches (38 lines, 4 modules) with no behaviour change.

- [ ] T002 Write descriptor parity tests that pin today's TikTok and Threads values (origin, search path, search URL, transport, record pattern, canonical URL, extractor version, sampling ordering) in `tests/unit/test_host_browser_sources.py`
- [ ] T003 Add `src/ignis/infrastructure/connectors/host_browser/sources.py` with one frozen descriptor per source and a lookup that refuses unknown sources (data-model.md)
- [ ] T004 Route `src/ignis/infrastructure/connectors/host_browser/relay.py` source branches through the descriptor
- [ ] T005 Route `src/ignis/infrastructure/connectors/host_browser/validator.py` source branches through the descriptor
- [ ] T006 Route `src/ignis/application/use_cases/host_browser_search.py` and `src/ignis/domain/host_browser_search.py` source branches through the descriptor
- [ ] T007 Run `tests/unit/test_host_browser_sources.py`, `tests/unit/test_host_browser_search.py`, `tests/unit/test_host_browser_relay.py` and the host-browser cases of `tests/integration/test_author_identity_conformance.py` unchanged: all green, no edited assertion

**Checkpoint**: TikTok and Threads behave byte-identically; one PR with both reviews.

## Phase 3: User Story 1 — one skill per source runs TikTok and Threads end to end (P1) 🎯 MVP

**Goal**: a fresh agent completes TikTok and Threads TACTICAL searches using only the skills (SC-001).
**Independent test**: quickstart steps 1–3 for TikTok and Threads.

- [x] T008 [P] [US1] Write the shared relay reference (step order, `STAGED` check, async `{}` handling, tab-group re-read, close tabs) from `research.md` in `src/ignis/interfaces/mcp/guides/ignis_browser_relay.md`
- [x] T009 [P] [US1] Write TikTok specifics (opener transport, `window.opener` refusal, unknown counters, null dates until FR-007) in `src/ignis/interfaces/mcp/guides/ignis_tiktok_browser.md`
- [x] T010 [P] [US1] Write Threads specifics (fragment transport, `/receive`, rounded counters, UI label locales) in `src/ignis/interfaces/mcp/guides/ignis_threads_browser.md`
- [x] T011 [US1] Write failing tests that the four guide prompts and resources are registered and packaged in the wheel in `tests/unit/test_host_browser_guides.py`
- [x] T012 [US1] Register `ignis_browser_relay`, `ignis_tiktok_browser`, `ignis_threads_browser` prompts and `fn-ignis://guide/...` resources in `src/ignis/interfaces/mcp/server.py`
- [x] T013 [P] [US1] Add thin skills pointing at the packaged guides in `.agents/skills/ignis-tiktok-browser/SKILL.md` and `.agents/skills/ignis-threads-browser/SKILL.md`. Deviation (2026-11-12): the host-browser section of `.agents/skills/ignis-collect/SKILL.md` stays, because `tests/unit/test_ignis_skills.py` pins it; `tests/unit/test_host_browser_guides.py` instead checks that the packaged relay guide keeps the same safety rules
- [ ] T014 [US1] Live acceptance: fresh session, TikTok and Threads per quickstart steps 1–3; record wall time and any step outside the skill in `specs/025-host-browser-skill-pack/research.md`

**Checkpoint**: Story 1 PR (guides, skills, registration) with both reviews.

## Phase 4: User Story 3 — failures named with check and remedy (P3, delivered with US1 text)

- [ ] T015 [US3] Review `ignis_browser_relay.md` against every finding in `research.md` (wheel/editable trap, tab-group drift, async `{}`, opener refusal, expiry, wrong profile, unsupported UI language) and add any missing row; record the mapping in `specs/025-host-browser-skill-pack/research.md`

## Phase 5: TikTok publication date (FR-007, OQ-4)

- [ ] T016 [US1] Live check: open three or more accepted TikTok videos on the Finos profile, compare the rendered date with `UTC(video_id >> 32)`, record each pair in `specs/025-host-browser-skill-pack/research.md`; stop this phase if any pair differs by more than one day
- [ ] T017 [P] [US1] Write failing tests for decoding (valid id, non-numeric, before 2016-09-01, future beyond one day) in `tests/unit/test_tiktok_video_id.py`
- [ ] T018 [US1] Add `src/ignis/domain/tiktok_video_id.py` and apply it at submit time to new TikTok observations whose `published_at` is null in `src/ignis/application/use_cases/host_browser_search.py`
- [ ] T019 [US1] Update the TikTok guide's date note in `src/ignis/interfaces/mcp/guides/ignis_tiktok_browser.md`

## Phase 6: User Story 2 — Instagram keyword search through the host browser (P2)

**Goal**: an Instagram TACTICAL search returns ≥10 accepted caption observations with no author identity (SC-002).
**Independent test**: quickstart step 4.

- [ ] T020 [US2] Spike (read-only, live): on the Finos profile, open the keyword grid from a relay-opened tab and confirm whether `window.opener` survives Instagram's navigation; choose the transport (opener or fragment) and record it in `specs/025-host-browser-skill-pack/research.md`
- [ ] T021 [P] [US2] Write failing descriptor tests for `instagram` (origin, keyword path, `/p/<id>/` and `/reel/<id>/` patterns, canonical URL, platform `reels`, surface `instagram_host_browser`) in `tests/unit/test_host_browser_sources.py`
- [ ] T022 [P] [US2] Write failing validator and submit tests from an Instagram-shaped fixture (caption kept, account path rejected, cross-source URL rejected, empty grid DEGRADED) in `tests/unit/test_host_browser_search.py`
- [ ] T023 [US2] Add the Instagram descriptor and extend `HostSearchSource` in `src/ignis/infrastructure/connectors/host_browser/sources.py` and `src/ignis/domain/host_browser_search.py`
- [ ] T024 [US2] Write the packaged extractor `instagram-keyword-grid-v1` (tile `img[alt]` caption, NFC, attribution removed, `kind_hint`, login/challenge → DEGRADED) in `src/ignis/infrastructure/connectors/host_browser/instagram_search.js`, plus `instagram_handoff.js` only if T020 chose the fragment transport
- [ ] T025 [US2] Add an Instagram fixture with an author sentinel to `tests/integration/test_author_identity_conformance.py`; document hashtags as free-text names outside Principle VII next to the TikTok rule (FR-008)
- [ ] T026 [US2] Confirm a request naming the retired `reels` surface still returns `SURFACE_RETIRED` with a test in `tests/unit/test_host_browser_search.py`
- [ ] T027 [US2] Name `instagram` in the `prepare_host_browser_search` description in `src/ignis/interfaces/mcp/server.py`; regenerate `hermes_manifest.json` and `.hermes/tools.json`; run `tests/unit/test_tool_manifests_drift.py`
- [ ] T028 [P] [US2] Write `src/ignis/interfaces/mcp/guides/ignis_instagram_browser.md`, register its prompt/resource, add `.agents/skills/ignis-instagram-browser/SKILL.md`
- [ ] T029 [US2] Live acceptance: quickstart step 4 on the G3 keyword; record count and identity check in `specs/025-host-browser-skill-pack/research.md`

**Checkpoint**: Story 2 PR with both reviews; security review covers the new untrusted-input path and Principle VII.

## Phase 7: Polish

- [ ] T030 [P] Update `docs/USER_GUIDE.md` and `docs/USER_GUIDE.vi.md` host-browser sections to name the three sources and the skills
- [ ] T031 [P] Record Spec 025 status in `BACKLOG.md` (SPEC-025, MEA-1)
- [ ] T032 Run quickstart steps 1–6 once more on the final wheel; record SC-001..SC-003 results in `specs/025-host-browser-skill-pack/research.md`

## Dependencies

- Phase 2 blocks every story.
- US1 (Phase 3) and US3 (Phase 4) ship together; Phase 5 needs Phase 2 and T016 passing.
- US2 (Phase 6) needs Phase 2 and the relay reference from T008; T020 gates T024.
- Polish needs the stories it documents.

## Parallel examples

- After T007: T008, T009, T010 in parallel (different guide files); T017 in parallel with them.
- In Phase 6: T021 and T022 in parallel; T028 in parallel with T024 once T023 lands.

## Implementation strategy

MVP = Phase 2 + Phase 3 (skills for the two working sources). Then Phase 5 (small, high value for period
views), then Phase 6 (Instagram). Each checkpoint is one pull request with a posted code review and a
posted security review; nothing merges on a single review.
