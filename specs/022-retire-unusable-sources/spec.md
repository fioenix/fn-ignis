# Feature Specification: Retire Unusable Source Connectors

**Feature Branch**: `022-retire-unusable-sources`

**Created**: 2026-11-10

**Status**: Draft

**Input**: Owner request (10/11/2026): "Vậy các nguồn vô dụng không chạy thì bỏ đi hay sao", followed by "Mở spec" and the rule recorded in `docs/decisions/2026-11-10-source-connection-boundary.md`. (Remove the sources that do not work.)

## Outcome and why

Ignis exposes connectors and tools that return no evidence. They cost maintenance, appear in health
reports as if they worked, and mislead an agent choosing a source. The decision record above keeps a
built-in connection only where no official MCP exists and only while it returns evidence.

The observable proof: Ignis offers only sources that collected evidence in a probe, each removed tool
is gone from the catalog, and stored observations from removed sources stay readable.

## Evidence (probes on 2026-11-10)

| Source or tool | Result | Disposition |
|---|---|---|
| YouTube Data API | Main source; 364 stored observations | Keep |
| TikTok host-browser search | `ACCEPTED`/`HEALTHY` on 2026-11-09 | Keep |
| Threads host-browser search | Main Threads path; 227 stored observations overall | Keep |
| `get_tiktok_video_comments` | 5 public comments without a session, no author identity | Keep |
| Google Trends RSS connector | 0 stored observations; no keyword measurement | Remove |
| TikTok Creative Center connector and `get_tiktok_creative_center_trends` | 0 hashtags | Remove |
| `get_tiktok_search_suggestions` | Returns general trends unrelated to the keyword | Remove |
| TikTok headless keyword search (`tiktok_video_grid`) | TikTok serves an empty page to headless browsers | Remove |
| Reels headless collection | `REELS_PAGE_UNUSABLE` on a fresh session (mission `VN-SPEC-022-7D-0789`) | Remove |
| `get_threads_trending_topics`, `get_threads_search_suggestions` | Placeholders that always return `UNAVAILABLE` or empty | Remove |
| `authenticate_tiktok` | Stores a session only the removed headless search used | Remove |
| `authenticate_threads` | Stores credentials that, by its own description, enable no collection | Remove |
| `authenticate_instagram`, `clear_instagram_auth`, `get_instagram_auth_status` | Serve only the Instagram session that Reels used | Remove |
| `clear_threads_auth`, `get_threads_auth_status` | Serve only the Threads session that `authenticate_threads` stored | Remove |

## Clarifications

### Session 2026-11-10

- Q: Which broken or placeholder tools are removed? → A: `get_tiktok_creative_center_trends`, `get_tiktok_search_suggestions`, `get_threads_trending_topics` and `get_threads_search_suggestions` (owner decided).
- Q: Which login tools are removed? → A: `authenticate_tiktok` and `authenticate_threads` (owner decided).
- Q: Is Reels kept? → A: It was probed with the fresh Instagram session first, on the owner's decision that a failure removes it. It returned `REELS_PAGE_UNUSABLE`, so Reels headless collection is removed.
- Q: What happens to the session tools that lose their consumer? → A: `authenticate_instagram`, `clear_instagram_auth`, `get_instagram_auth_status`, `clear_threads_auth` and `get_threads_auth_status` are removed too (owner decided). Planning confirms that `clear_platform_auth`, `get_platform_auth_status` and the self-content guard do not depend on them.
- Q: Which rule decides what stays built in? → A: The decision record `2026-11-10-source-connection-boundary.md`, accepted by the owner: an official MCP means integrate with it, otherwise build in.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - An agent sees only sources that work (Priority: P1)

An agent planning a watchlist run or a mission lists Ignis's tools and channels and finds only sources
that can return evidence today.

**Why this priority**: Dead sources are the reason for this feature.

**Independent Test**: List the MCP tools and the connector registry, and attempt a mission naming a removed surface.

**Acceptance Scenarios**:

1. **Given** the updated server, **When** the tool catalog is listed, **Then** the eleven removed tools are absent and 42 tools remain.
2. **Given** a manifest that names `google`, `tiktok_creative_center`, `tiktok_video_grid` or `reels`, **When** a mission is created or run, **Then** it is refused with a typed reason naming the retired surface, before any collection.
3. **Given** health or channel status reports, **When** they are read, **Then** they list no retired connector.

---

### User Story 2 - Earlier evidence stays readable (Priority: P2)

A person reopens an old mission or a watchlist period that included a removed channel.

**Why this priority**: Removing a connector must not erase or hide evidence already collected.

**Independent Test**: Read stored missions, observations and a period view that include Reels, TikTok grid or Google rows.

**Acceptance Scenarios**:

1. **Given** stored observations from a removed source, **When** a mission's evidence or a period view is read, **Then** they appear as before and are labelled with their original platform.
2. **Given** a watchlist whose stored allowed resources include a removed surface, **When** the next run starts, **Then** the run proceeds with the remaining surfaces and reports the retired one as retired, never as zero.

---

### User Story 3 - Guidance matches the catalog (Priority: P3)

A contributor or agent reading the guides, skills and tool manifests finds no instruction to use a removed source.

**Independent Test**: Search the shipped guides, skills, manifests and public documents for the removed tools and surfaces.

**Acceptance Scenarios**:

1. **Given** the repository, **When** the guides, skills, tool manifests and public documents are read, **Then** they name 42 tools and no removed tool or surface, apart from history.

### Edge Cases

- A routine prompt stored in a host's scheduled task names a removed surface: the run still starts and reports the retired surface.
- A stored session row for TikTok, Threads or Instagram remains in a store: it is left in place and unused; this feature deletes no stored data.
- A host still calls a removed tool by name: the server reports an unknown tool, as for any absent tool.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Ignis MUST remove the eleven tools named in Clarifications and keep every other tool's name and parameters.
- **FR-002**: Ignis MUST stop registering the Google Trends RSS, TikTok Creative Center, TikTok headless keyword search and Reels headless connectors.
- **FR-003**: A mission or watchlist run that names a retired surface MUST be refused or reduced with a typed reason before collection, never reported as an empty result.
- **FR-004**: `get_tiktok_video_comments`, YouTube collection and host-browser search for TikTok and Threads MUST behave as before.
- **FR-005**: Stored observations, channel outcomes and sessions from retired sources MUST remain unchanged and readable.
- **FR-006**: Guides, skills, tool manifests, `AGENTS.md`, `CLAUDE.md` and public documents MUST match the new catalog.
- **FR-007**: No migration MAY transform persisted evidence.

### Key Entities

- **Retired surface**: A connector surface that Ignis no longer collects from; stored evidence from it stays.
- **Tool catalog**: The MCP tools the server exposes; its count is governed by the repository's contract tests.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: The catalog lists 42 tools, none of the eleven removed.
- **SC-002**: A mission naming any retired surface is refused before collection in 100% of attempts.
- **SC-003**: Every stored observation from a retired source is still returned by the reads that returned it before.
- **SC-004**: No shipped guide, skill, manifest or public document names a removed tool outside history.

## Assumptions

- There is no production environment; the stores are development stores.
- The Data-Driven Vocabulary for retired connectors (for example TikTok UI noise and suggest templates) may become unused; planning decides whether it stays as seed data or goes, without transforming evidence.
- Instagram and other sources may return later through host-browser search or an official MCP, each in its own spec.
