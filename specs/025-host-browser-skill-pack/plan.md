# Implementation Plan: Host-Browser Skill Pack and Instagram Reels Through the Host Browser

**Branch**: `025-host-browser-skill-pack` | **Date**: 2026-11-12 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/025-host-browser-skill-pack/spec.md` (clarified 2026-11-12)

## Summary

Three increments, each shippable on its own:

1. **Skill pack (Story 1, 3)**: three agent skills, `ignis-tiktok-browser`, `ignis-threads-browser` and
   `ignis-instagram-browser`, each short and source-specific, all pointing at one shared reference with
   the relay procedure and failure table proven in `research.md`. The same text ships as packaged MCP
   prompts and resources so Claude Desktop and other non-repository hosts receive it.
2. **Instagram host-browser source (Story 2)**: a third `source` value, `instagram`, for
   `prepare_host_browser_search`, with a packaged extractor `instagram-keyword-grid-v1` that reads the
   signed-in keyword grid (`/explore/search/keyword/?q=`), the same relay and validator path, author
   identity removal, and a connector surface distinct from the retired `reels` surface. Observations
   carry platform `reels`, so period views and qualification treat them like any source (OQ-3).
3. **TikTok publication date (FR-007, OQ-4)**: a recorded check of decoded video-id dates against rendered
   dates on real videos, then deterministic derivation of `published_at` at submit time.

The source switch in the host-browser code is binary today (`threads` or else `tiktok`) on 38 lines
of four modules. Adding a third source first replaces those branches with one per-source descriptor; behaviour for
TikTok and Threads stays byte-identical, proven by the existing host-browser tests before any Instagram code.

## Technical Context

**Language/Version**: Python 3.11+ (server), browser JavaScript for packaged extractors

**Primary Dependencies**: FastMCP, existing host-browser relay (`infrastructure/connectors/host_browser/`);
no new dependency

**Storage**: SQLite default and PostgreSQL; no migration. Instagram observations use existing source,
observation and mission-evidence rows; platform `reels` already exists in `PlatformType`

**Testing**: pytest unit tests for descriptor parity, extractor-shaped fixtures, validator and author
identity; the existing author-identity conformance integration test gains an Instagram fixture; one live
TACTICAL run per source as acceptance (owner-permitted sessions on the Finos profile)

**Target Platform**: The user's own Chrome through Claude in Chrome; macOS dev machine

**Project Type**: MCP server library plus agent skills

**Performance Goals**: SC-003, median prepare-to-accepted at or under 60 s per source (TikTok baseline 40 s)

**Constraints**: no clicks, typing or scrolling on platform pages; no bot-evasion tooling; one extractor run
per tab; tool count stays 41 and tool names stay unchanged

**Scale/Scope**: up to 100 results per query (existing limit), one query batch per request

## Constitution Check

*GATE: passed before Phase 0; re-checked after Phase 1 design below.*

| Principle | How the plan complies |
|---|---|
| I. Mission-bound, zero-token collection | Skills only describe explicit, user-requested TACTICAL or MISSION runs; extractors are deterministic JavaScript, no model in collection; no scheduler |
| II. Pluggable connectors | Instagram is a host-browser source behind the same relay contract; the retired Playwright `reels` path stays refused (FR-005) |
| III. Evidence-first | Instagram observations go through normal qualification (OQ-3); TikTok dates are derived only after a recorded check; unknown counters stay unknown |
| IV. Deterministic report builders | No change |
| V. Simplicity, surgical changes | One descriptor replaces duplicated branches only because a third source needs it; no new abstraction beyond that table |
| VI. Evidence-gated migration and release | No migration; no persisted evidence transformed. TikTok date derivation applies to new submissions only |
| VII. No author identity at rest | Instagram extractor drops account handles, profile links and author attribution from captions; `@mentions` masked as today; conformance test gains an Instagram sentinel. Hashtags are kept as documented free-text names (owner decision OQ-2), which the principle's own free-text clause allows when documented |

AGENTS.md section 8 owner gates: adding a `source` value to `prepare_host_browser_search` is a tool
contract change the owner approved with the Reels reopening (2026-11-11); moving Reels from the retired
Playwright tier to the host-browser tier is the tier move the same answer approved. No version bump in
this feature.

**Post-design re-check**: passed; see Complexity Tracking for the one structural change.

## Project Structure

### Documentation (this feature)

```text
specs/025-host-browser-skill-pack/
├── spec.md
├── plan.md              # this file
├── research.md          # live run log, findings, repeat-run overlap
├── data-model.md        # source descriptor, Instagram record, date derivation
├── quickstart.md        # acceptance run per source
├── contracts/
│   └── host-browser-sources.md
└── skill-draft.md       # superseded by the skill files at implementation
```

### Source Code (repository root)

```text
src/ignis/domain/host_browser_search.py                 # HostSearchSource gains "instagram"; descriptor table
src/ignis/infrastructure/connectors/host_browser/
├── sources.py              # NEW: one descriptor per source (origin, search path, URL builder, transport, record pattern, extractor)
├── relay.py                # binary source branches read the descriptor
├── validator.py            # same; Instagram record pattern /p/<id>/
├── instagram_search.js     # NEW: instagram-keyword-grid-v1
└── instagram_handoff.js    # NEW only if Instagram needs the fragment transport (decided in T-phase spike)
src/ignis/application/use_cases/host_browser_search.py  # descriptor; TikTok published_at derivation hook
src/ignis/domain/tiktok_video_id.py                      # NEW: decode publish second from a video id
src/ignis/interfaces/mcp/guides/
├── ignis_browser_relay.md      # NEW shared reference
├── ignis_tiktok_browser.md     # NEW
├── ignis_threads_browser.md    # NEW
└── ignis_instagram_browser.md  # NEW
src/ignis/interfaces/mcp/server.py   # prompt + resource registration for the four guides; prepare description names instagram
.agents/skills/ignis-tiktok-browser/SKILL.md      # NEW, points to the packaged reference
.agents/skills/ignis-threads-browser/SKILL.md     # NEW
.agents/skills/ignis-instagram-browser/SKILL.md   # NEW
hermes_manifest.json, .hermes/tools.json           # regenerated description of prepare_host_browser_search
tests/unit/test_host_browser_sources.py           # NEW: descriptor parity for tiktok/threads, instagram rules
tests/unit/test_tiktok_video_id.py                # NEW
tests/unit/test_host_browser_search.py            # extended: instagram prepare/submit
tests/integration/test_author_identity_conformance.py  # Instagram fixture with sentinel
```

**Structure Decision**: keep the existing host-browser package; add one descriptor module rather than a
class hierarchy. Skills in `.agents/skills/` stay thin and point at the packaged guides, so the procedure
has one source of truth.

## Delivery order and owner checkpoints

1. Descriptor refactor with no behaviour change (TikTok and Threads tests unchanged and green).
2. Skill pack and packaged guides for TikTok and Threads; acceptance: a fresh agent completes SC-001.
3. TikTok date check (live, three or more videos, decoded vs rendered date) recorded in `research.md`;
   then derivation with tests. Stops if any decoded date disagrees by more than one day.
4. Instagram extractor, validator rules, conformance fixture, guide and skill; live TACTICAL acceptance (SC-002).
5. Regenerate tool catalogs; one PR per increment, each with posted code and security reviews.

## Complexity Tracking

| Change | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| Per-source descriptor table | A third source would add a third arm to the `threads`-or-`tiktok` conditionals on 38 lines across relay, validator and use case | Adding `elif source == "instagram"` everywhere repeats the origin, path and pattern in many places and invites a missed branch that silently treats Instagram as TikTok |
