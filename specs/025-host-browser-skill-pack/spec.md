# Feature Specification: Host-Browser Skill Pack and Instagram Reels Through the Host Browser

**Feature Branch**: `025-host-browser-skill-pack`

**Created**: 2026-11-11

**Status**: Clarified 2026-11-12. Ready for `/speckit-plan`.

**Input**: Owner request of 2026-11-11: "Ignis sẽ cần một bộ skill chuyên về scrape TikTok, Reels,
Threads... bằng browser đó. Mày nên nghiên cứu thực hiện một lần, ghi nhận lại các thao tác thành
skills để tối ưu cho những lần thao tác sau này của users." (Ignis needs a skill set specialised in
collecting TikTok, Reels and Threads through the browser; do it once, record the operations as skills
so users' later runs are faster.) Asked whether Reels is in scope although Spec 020 dropped Instagram
and Spec 022 retired the `reels` channel, the owner answered the same day: "Mở lại Reels luôn"
(reopen Reels now).

## Outcome and audience

A founder or seller researching a product in Vietnam asks their own agent to look up a keyword on
TikTok, Threads or Instagram through their own signed-in Chrome. Today the agent rediscovers the relay
procedure every time and trips on the same failures (see `research.md`). The observable outcome is
that a host agent with no prior context completes one TACTICAL search per source from a single skill,
in the order the live run proved, and recovers from each known failure without asking the user.

## Clarifications

### Session 2026-11-11

- Q: Is Instagram (Reels) in scope? → A: Yes; reopen it through the host browser (owner decided, chat
  2026-11-11). This reverses the Spec 022 retirement for the host-browser tier only; the retired
  Playwright `reels` path stays retired.
- Q: Does the skill drive the platform page (scroll, click, type)? → A: No. The 2026-10-26 decision
  stands: the agent only opens the relay's approved search URL and runs the packaged extractor once;
  the only clicks are on the local relay page (agent decided; basis: research note step logs and
  `BACKLOG.md` "Trình duyệt cho đường browser").

- Q: OQ-1 How is the skill pack packaged? → A: One skill per platform (TikTok, Threads, Instagram); the shared
  relay procedure and failure table live once as a reference file that each skill points to, following the
  skills standard (owner decided, 2026-11-12).
- Q: OQ-2 TikTok hashtags that equal a creator's handle? → A: Keep hashtags in the excerpt and record them as
  free-text names outside Principle VII, under the principle's own clause that free-text personal names are
  outside it and must be documented (owner decided, 2026-11-12). Recorded risk: a hashtag can equal a handle,
  so stored excerpts may name a creator; `@handles` and profile links stay removed as today.
- Q: OQ-3 How are Instagram observations qualified? → A: Like any other source, through normal evidence
  qualification; no default to `CONTEXT_ONLY` (owner decided, 2026-11-12).
- Q: OQ-4 TikTok publication date from the video id? → A: Yes, after checking decoded dates against the
  rendered dates of a few real videos; then `published_at` is derived at submit time (owner decided,
  2026-11-12). Until the check passes, TikTok keeps the Spec 016 first-collection anchor.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - One skill runs a TikTok or Threads search end to end (Priority: P1)

A host agent with no prior context is asked "find what people say about <keyword> on TikTok and
Threads through my browser". It loads the skill, checks the browser profile, runs one TACTICAL search
per source and returns the accepted observations.

**Why this priority**: Both sources work today (`research.md`); only the operating knowledge is
missing, so this delivers value without new code.

**Independent Test**: In a fresh session, give only the request and the skill. The run reaches
`ACCEPTED` for both sources with no step the skill does not name.

**Acceptance Scenarios**:

1. **Given** a connected Chrome on the user's chosen profile, **When** the agent follows the skill,
   **Then** it calls `prepare_host_browser_search`, opens the relay, opens the search tab from the
   relay, runs the tab script once, reads `STAGED` on the relay and calls `submit_host_browser_search`.
2. **Given** the Threads tab script is asynchronous, **When** the evaluator returns `{}`, **Then** the
   skill reads success from the relay page or the tab's navigation to `/receive`, not from the return value.
3. **Given** a sign-in wall, challenge or empty grid, **When** the extractor reports `DEGRADED`,
   **Then** the agent reports the channel unavailable and does not retry with another browser.

### User Story 2 - Instagram keyword search through the host browser (Priority: P2)

The same agent can add Instagram to the request and receive caption observations from the keyword grid.

**Why this priority**: Reopened by the owner; it needs a new packaged extractor, relay source and
conformance coverage, so it costs more than Story 1.

**Independent Test**: A TACTICAL Instagram search on one keyword returns `ACCEPTED` observations whose
excerpts carry no author identity.

**Acceptance Scenarios**:

1. **Given** a signed-in Instagram keyword grid, **When** the packaged extractor runs, **Then** each
   record is a `/p/<id>/` link with the tile's caption text, `published_at` null and counters unknown.
2. **Given** a caption with an `@mention`, **When** it is stored, **Then** the mention is masked as for
   other sources.
3. **Given** the `reels` Playwright path, **When** anything requests it, **Then** it stays refused as retired.

### User Story 3 - Recoverable failures are named in the skill (Priority: P3)

Each failure the live run met has a named check and remedy in the skill: an editable reinstall that
removed packaged extractor files from the running server's `site-packages`, tab ids that left the
agent's tab group, the wrong Chrome profile, a non-supported page language.

**Independent Test**: For each named failure, the skill text names its symptom, the check and the
remedy; a review against `research.md` finds none missing.

### Edge Cases

- The user's Chrome has no Claude extension connected: the channel is unavailable; no other browser.
- The relay lifetime expires before the tab script runs: cancel and prepare again, never reuse a request.
- The page UI language is not one the extractor's labels cover: counters stay unknown; records may still pass.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The repository MUST ship one host-browser collection skill per platform under `.agents/skills/`,
  sharing one reference for the relay procedure and failure table, and the same guidance as packaged MCP
  prompts and resources, so non-repository hosts receive it too.
- **FR-002**: The skill MUST state the step order proven in `research.md` and MUST NOT instruct any
  click, typing or scrolling on a platform page.
- **FR-003**: The skill MUST name each failure in `research.md` with its check and remedy.
- **FR-004**: Instagram keyword search MUST be available as a host-browser source with a packaged,
  versioned extractor, accepted only through the existing relay, validator and author-identity
  conformance check (Principle VII).
- **FR-005**: The retired Playwright `reels` path MUST stay refused.
- **FR-006**: No MCP tool may be added or removed; extending the `source` values that
  `prepare_host_browser_search` accepts is a contract change the owner approved with the Reels reopening,
  and its description and manifests MUST be regenerated.
- **FR-007**: TikTok `published_at` MUST be derived from the video id only after a recorded check against
  rendered dates; the derivation MUST be deterministic and leave the date null when the id does not parse.
- **FR-008**: Stored TikTok excerpts keep hashtags; the author-identity conformance documentation MUST list
  hashtags as free-text names outside Principle VII.

### Key Entities

- **Host-browser source**: `tiktok`, `threads`, and new `instagram`; each has one packaged extractor version.
- **Skill pack**: the operating procedure, per-source notes and failure table.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A fresh agent given only the skill completes TikTok and Threads TACTICAL searches to
  `ACCEPTED` with zero steps outside the skill, in one attempt each.
- **SC-002**: An Instagram TACTICAL search on the G3 keyword returns at least 10 accepted observations
  with zero author identifiers in stored excerpts.
- **SC-003**: Median wall time from prepare to accepted stays at or under 60 seconds per source
  (live baseline: about 40 seconds for TikTok).

## Assumptions

- The owner's permission for real TikTok and Threads sessions (2026-11-11) extends to Instagram on the
  same Finos profile.
- Meta's terms for reading a signed-in page in the owner's own browser were accepted for Threads in
  Spec 020 G1; Instagram falls under the same acceptance unless the owner says otherwise.
