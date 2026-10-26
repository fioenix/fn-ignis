# Feature Specification: Task-Bound Host Browser Search

**Feature Branch**: `release/v0.8.0` (existing worktree; no release operation authorized)

**Created**: 2026-10-02

**Status**: Specification, plan and bounded localhost relay approved — implementation in progress

**Input**: Owner approved using the live Chrome session through a host-provided integration,
without cookie export, a new debugging port, or silent fallback to isolated contexts, and
requested implementation followed by a live retry.

## User Scenarios & Testing

### User Story 1 - Collect from the authorized working browser (Priority: P1)

As a researcher whose TikTok search works in their browser but fails in recreated sessions,
I want Ignis to collect public search results through that authorized session so that I can
verify the evidence rather than see a misleading empty channel.

**Why this priority**: The existing isolated-session path cannot reliably obtain search answers.
The owner needs source access, not another launch flag or retry policy.

**Independent Test**: Execute one explicitly requested public search through the host session;
show attributable observations and a channel outcome, without a Market recommendation.

**Acceptance Scenarios**:

1. **Given** an authorized host browser and a bounded query, **When** the host reads its public
   TikTok result grid, **Then** Ignis returns only result observations with public source URLs,
   the executed query, capture time, collection-path identity, and known measurement limits.
2. **Given** a host without a usable browser capability, **When** that path is explicitly chosen,
   **Then** Ignis reports the capability gap and does not recreate a browser or collect elsewhere.
3. **Given** a search error or a suggestions-only page, **When** the answer is read, **Then** the
   result is degraded, not an attested empty video search.

### User Story 2 - Reuse a session without taking ownership of it (Priority: P1)

As the browser owner, I want multiple approved searches to use one task-bound session without
closing my browser, changing unrelated tabs, or leaving continuing collection behind.

**Why this priority**: Session lifecycle is the failure boundary being changed; user ownership
and termination are part of the functionality, not cleanup details.

**Independent Test**: Run a two-query batch and exercise completion, cancellation, and failure;
confirm that only task-created resources are released and no additional query is executed.

**Acceptance Scenarios**:

1. **Given** two approved queries, **When** the batch runs, **Then** both use the same authorized
   browser session and each receives its own measured outcome.
2. **Given** completion, cancellation, or failure, **When** collection terminates, **Then** the
   task stops and leaves owner-owned tabs, browser state, and credentials intact.
3. **Given** results from another query, an earlier task, or a different page, **When** they are
   supplied to the current task, **Then** they are rejected rather than treated as fresh evidence.

### User Story 3 - Keep observations separate from Market support (Priority: P2)

As a researcher, I want host-collected results to pass through the same evidence boundaries as
other Ignis collection so that a working browser does not bypass qualification or falsification.

**Why this priority**: Access restores an observation source; it does not prove commercial demand.

**Independent Test**: Collect a tactical batch without creating a mission; separately verify that
mission use requires its confirmed source, query budget, authority, and evidence frame.

**Acceptance Scenarios**:

1. **Given** tactical collection, **When** observations are returned, **Then** no Market claim,
   mission, or continuing collection is implicitly created.
2. **Given** a confirmed mission, **When** host collection is requested, **Then** only its approved
   sources and queries execute, and observations enter the existing qualification boundaries.
3. **Given** unknown publication dates, metric kinds, or search-window filtering, **When** results
   are normalized, **Then** those facts remain unknown rather than inferred from capture time or
   ambiguous card counters.

### Edge Cases

- Authentication expires, Chrome is unavailable, the host disconnects, or the owner takes control.
- Results contain live streams, photo posts, suggestions, hidden feed links, or private UI chrome.
- Duplicate cards appear across queries; provenance must retain the queries that found the source.
- A card exposes a partial date or an ambiguous counter; neither becomes a fabricated exact fact.
- A nominally successful answer is malformed or contains no verified search envelope.
- Concurrent tasks must not share a mutable query attestation or claim each other's result batch.

## Requirements

### Functional Requirements

- **FR-001**: Host-browser collection MUST require an explicit bounded request and authorized
  browser session; it MUST NOT become an unattended or default fallback collector.
- **FR-002**: Ignis MUST use the existing host-authorized session without exporting credentials,
  creating a debugging port, or expanding permission to unrelated account surfaces.
- **FR-003**: One batch MUST reuse its task-bound session and isolate each query's attestation.
- **FR-004**: Collection MUST inspect only approved public search pages and their result records;
  unrelated tabs, private messages, notifications, profile storage, and account controls are excluded.
- **FR-005**: Returned observations MUST retain source URL, exact query, capture time, host path
  identity, content excerpt, and separately known publication and metric facts.
- **FR-006**: An empty result MUST be measured empty only after the correct search answer is
  verified; unsupported capability, wrong-page data, failures, and stale results MUST fail closed.
- **FR-007**: Cleanup MUST release task-owned resources only; all terminal states MUST stop work.
- **FR-008**: Mission collection MUST honor the confirmed manifest and existing persistence,
  qualification, and Claim Ledger boundaries; historical observations MUST remain unchanged.
- **FR-009**: Existing MCP signatures, isolated collector defaults, and source runtime tiers MUST
  remain unchanged unless a separate owner approval explicitly covers a required public change.
- **FR-010**: A live retry MUST exercise the implemented Ignis-to-host path. A successful manual
  browser lookup or a fake-session unit test alone MUST NOT be reported as a repaired connector.
- **FR-011**: The approved localhost relay MUST bind only to `127.0.0.1`, use an unpredictable
  task-specific path, enforce exact Host/Origin and finite payload bounds, exclude third-party CORS,
  and stop on completion, cancellation or expiry. It MUST NOT expose cookies or persistent access.
- **FR-012**: No excerpt MAY carry the platform's author attribution. TikTok's image label ends
  with a sentence naming the poster ("do <author> tạo với bản nhạc …"); Ignis MUST remove it before
  a receipt is returned or an observation is stored, using attribution templates held as seeded
  vocabulary per locale. Without that vocabulary, preparation MUST fail closed. A record left with
  no content is dropped, and an answer left with no record is degraded, not healthy.
- **FR-013**: The relay page MUST offer one control per approved query that opens its exact search
  URL from a real click, and MUST accept a search answer only by `postMessage` from
  `https://www.tiktok.com` sent by a window that control opened, for that window's query, within
  the approved record limit. Once every query has an answer it stages them through the same
  same-origin form. The script the host runs in the search tab returns only status and counts, so
  records never pass through the agent. Preparation also returns that script as `tab_script`, because
  browser tooling may refuse to read it back from the page.

### Key Entities

- **Task-bound browser session**: Authorized session reference, ownership boundary, supported
  capabilities, and terminal lifecycle; never a credential dump.
- **Search request**: Task/frame identity, approved public query, source, and result limit.
- **Search answer**: Matching request identity, actual page, capture time, verified outcome,
  public records, and measurement limitations.
- **Observation**: Existing Ignis source/observation representation; not a new evidence store.

## Success Criteria

### Measurable Outcomes

- **SC-001**: A live requested TikTok query returns at least one attributable search observation
  through the implemented Ignis-to-host path when the authorized browser shows results.
- **SC-002**: A two-query batch reuses the session; no owner-owned tab or browser is closed in
  success, failure, or cancellation acceptance scenarios.
- **SC-003**: Every wrong-query, stale, unrelated-page, unavailable-capability, and malformed-answer
  acceptance case is rejected or visibly degraded; none is reported as measured zero.
- **SC-004**: No authentication material is exported, logged, or included in resulting artifacts.
- **SC-005**: Tactical results contain no commercial recommendation; mission use cannot bypass
  its existing authority, budget, or qualification checks.

## Assumptions

- Initial live validation targets the owner's already-authorized Chrome/TikTok public search.
- A working Chrome page proves source access, not automatic availability to the Ignis process.
  Host transport feasibility is a planning gate, not an assumed capability.
- Hosts without the required capability remain explicitly unsupported; support for every agent
  environment is not part of this feature's first implementation.
- No new cookie/profile persistence, database migration, release, or account interaction is included.
  Amended 2026-10-26: migration 034 seeds vocabulary rows only; it transforms no evidence.
- The separate bounded Google correction retains RSS macro observations and moves Autocomplete
  to keyword expansion. Genuine keyword Trends time-series ingestion is outside this feature.

## Clarifications

### Session 2026-10-26

- Q: When TikTok blocks automated Playwright sessions, should Ignis adopt anti-detection browsers (patchright, Camoufox) or this host browser path? → A: This host browser path through Claude in Chrome, with no additional browser plugin. Anti-detection tooling is out of scope; the agent only opens the prepared search URL, runs the `tiktok-public-grid-v1` extractor and submits, and a missing host capability stays an unavailable channel (owner decided 2026-10-26; basis: on 2026-10-25 a logged-in stored session returned 0 cards in headless, headed and fixed-profile Playwright while the owner's Chrome returned 16 cards, and the Claude Code auto-mode classifier blocked a patchright probe as bot-check circumvention).
- Q: Does the image label keep TikTok's attribution sentence? → A: No. The owner approved the fix
  on 2026-10-26 ("Cho session TikTok sửa lỗi lọt tên tác giả trong excerpt và thêm nút mở tìm kiếm
  cùng listener postMessage cho relay, mở PR riêng, chưa đổi routine"). This supersedes the
  2026-10-03 answer that retained the label "including attribution", which predates Constitution
  VII and Spec 015. A live tactical trial on 2026-10-26 returned twelve excerpts, each ending in
  the poster's display name. Templates such as `do {author} tạo với` are seeded in
  `market_lexicons` domain `tiktok_attribution` (migration 034), one row per locale; the server
  strips the rightmost matching attribution and everything after it. Only the Vietnamese wording
  observed live is seeded; another locale needs its own observed row (owner decision; basis:
  Constitution V and VII, FR-012, repository vocabulary rule).
- Q: How does the extractor answer reach the relay without the host improvising a transport or the
  agent transcribing records? → A: The relay page opens each search tab itself from a real click
  and listens for `postMessage`. It accepts a message only from `https://www.tiktok.com`, only
  from a window it opened, and only for that window's query. The packaged tab script posts the
  extractor result to `window.opener` and returns counts only. The relay page script is bound by a
  per-page CSP nonce; the manual paste path remains. Preparation returns the same script as
  `tab_script`: in the live check, Claude in Chrome refused to return it from the page ("Cookie/query
  string data") (owner decision of 2026-10-26, same quote;
  basis: FR-011, FR-013 and the 2026-10-26 trial, where reading the answer back through browser
  tooling was blocked and a host-improvised transport was needed).
- Q: When does a MISSION ticket read attribution wording added in the database? → A: Before the
  ticket is created, from the mission's repository, because the ticket freezes its templates and
  ingestion does not clean the validated receipt again. TACTICAL keeps the database-free path
  (agent decided; basis: PR #79 code review P1, FR-012).
- Q: May one batch repeat a query? → A: No. The tab script binds a tab to its query by text, so a
  repeated query could never stage; preparation rejects it. Mission query unions are already
  deduplicated (agent decided; basis: PR #79 code review P2, FR-013).
- Q: Does this amendment skip `speckit-tasks`? → A: No. It touches the author-identity privacy
  boundary and the relay's script and origin checks, so the depth gate requires tasks; Phase 7 in
  tasks.md lists them (agent decided; basis: owner depth-gate rule).

### Session 2026-10-04

- Q: Should preparation documentation describe client-supplied capabilities or a host-surface argument? → A: No. List the actual current MCP parameters; MISSION scope derives from the confirmed manifest and requires tiktok_video/browser-session authority. Correct contract prose only, without changing the API or acceptance gates (agent decided; basis: inspected prepare handler and prepare_scope, exact lookup rather than semantic inference, decision check found no recorded contradiction).

- Q: Can current passing characterization tests prove the original test-first order? → A: No. Retain unresolved historical RED/before-writer-extraction tasks, record current behavioral/runtime evidence separately and ask the owner for explicit process-deviation disposition. Do not reconstruct history or waive visual/integration acceptance (agent decided; basis: original task wording, retained blocker-correction note and decision check found no recorded contradiction; owner gate requires explicit approval).

### Session 2026-10-03

- Q: Where does a counter-only public video tile supply attributable content? → A: In the
  observed DOM, the visible image inside the exact canonical video link carries the public
  content in its alt label. Retain that label verbatim, including attribution [superseded on
  2026-10-26: the attribution is removed, see FR-012]; reject hidden,
  missing or counter-only labels. Do not infer metrics or publication time from it (agent
  decided; basis: owner's bounded Chrome approval, observed three-card DOM, FR-005 and
  fresh canonical mission relay acceptance; decision check found no contradiction).
- Q: Can phone masking consume the country-code-shaped suffix of a numeric evidence ID? → A:
  No. Require a numeric start boundary for Vietnamese phone matching rather than exempting
  URLs from redaction. Keep complete phones, emails and secrets masked (agent decided;
  basis: reproduced real analysis readback defect, citation integrity and privacy contract;
  decision check found no contradiction).
- Q: May engagement counters alone be retained as host content excerpts? → A: No. Reject
  numeric-only counter tiles and report degraded content availability rather than a measured
  empty search. Do not invent a caption from the query or URL; actual caption extraction must
  be grounded in an observed public DOM and a fresh bounded browser round-trip (agent decided;
  basis: reproduced numeric-only live excerpts, FR-005, owner-approved blocker correction;
  decision check found no contradiction).
- Q: What happens when a mission submission is cancelled during SQLite persistence? → A:
  Drain the already-started synchronous mutation before propagating cancellation or releasing
  writer ownership; record the interrupted mission and journal as FAILED. Cleanup may outlast
  the collection deadline, but cannot authorize further probes or automatic retries. Guard writer
  acquisition cleanup as well. Repeated cancellation must also drain terminal mission/journal
  updates and writer release on either backend (agent decided; basis: reproduced cancellation defects, FR-007/FR-008,
  owner-approved review fixes; decision check found no contradiction).
- Q: What does the approved masking correction cover? → A: Apply the existing deterministic
  pattern-based sanitizer to host public excerpts before receipts and mission persistence; do not
  retain a redundant raw staged payload. Preserve canonical source URLs and exact approved query
  identity; do not rewrite historical evidence or promise complete PII detection (agent decided;
  basis: owner's "Làm luôn đi", existing ingress privacy policy and evidence provenance contract).

### Session 2026-10-02

- Q: How are collection expiry and receipt retention separated? → A: Recheck the original expiry
  across awaited mission preparation, collection and persistence boundaries, and bound ingestion
  by that deadline. Never evict an active SUBMITTING ticket. Retain terminal receipts for the
  original request duration measured from completion; this does not renew collection authority
  (agent decided; basis: FR-007/FR-008, bounded replay/readback, no additional configuration).
- Q: Do empty required-source and per-surface quota declarations imply defaults? → A: No.
  Explicitly empty declarations remain empty; optional sources cannot become required, and
  host collection cannot inherit another surface's API cost (agent decided; basis: FR-008).
- Q: Can unknown video metrics determine reach or maturity? → A: No. Report unknown total reach,
  a separate measured subtotal and unmeasured count; with no measured videos, maturity is unknown
  (agent decided; basis: FR-005 and User Story 3's measurement boundaries).
- Q: Has the owner approved the implementation plan and execution? → A: Yes: "tao duyệt,
  triển khai đi". This includes the additive operations; it does not authorize an unplanned listener.
- Q: Can current host tooling relay extraction output directly to Ignis without model reconstruction?
  → A: Not established. The documented CUA surface exposes read-only DOM evaluation, but no MCP
  invocation or arbitrary JSON file export. Stop at the plan's first transport gate; do not substitute
  transcript copying, cookie export or shell browser control (agent decided; basis: FR-010,
  Constitution I and the approved plan's explicit stop condition).
- Q: Should a task-bound local relay listener be added? → A: Yes. The owner replied "Đồng ý" to the
  proposal for a localhost-only task-bound relay, single-use access, no cookies and terminal shutdown.
- Q: How should that bounded relay be implemented? → A: Standard-library HTTP server on an ephemeral
  loopback port with a random path, exact Host/Origin checks and capped form payload. The host fills
  the local form directly from retained extraction JSON; no transcript reconstruction (agent decided;
  basis: owner-approved boundary, no new dependency). The earlier pending decision is superseded.
- Q: Has the owner approved the written specification? → A: Yes: "Tao duyệt". Approval of
  the resulting implementation plan remains a separate gate.
- Q: Which transport should the plan propose? → A: Additive prepare/submit/cancel MCP operations
  mediated by the host agent, not direct Python-to-Codex browser calls (agent decided; basis:
  no existing host transport; preserve signatures/defaults; decision check found no contradiction).
  Public additions remain proposed until plan approval.
- Q: Is durable pending-task storage required? → A: No; process-local tickets fail closed on restart
  and uncertain writes cannot be retried automatically (agent decided; basis: bounded scope,
  no migration or new persistence; no exactly-once crash guarantee).
- Q: Which TikTok session direction should be used? → A: The owner approved the proposed host-browser
  direction and requested implementation followed by a retry: "OK tao duyệt triển khai đi, xong rồi thử lại".
- Q: Should existing defaults, historical data, or authentication-storage boundaries change? → A:
  Keep them unchanged, as stated in the approved proposal; no separate change was authorized.
- Q: Where should the new integration's agreement live? → A: A separate Spec Kit feature rather than
  completed Spec 011 (agent decided; basis: new interface, preserve completed scope and owner edits).

## Review Boundary

The owner approved the specification, plan, inline execution and bounded localhost relay. Its live
transport gate remains required before mission integration or any repaired/activated claim.
