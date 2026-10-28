# Feature Specification: Threads Through the Host Browser, Without Evasion Flags

**Feature Branch**: `claude/meta-host-browser-spec`

**Created**: 2026-10-27

**Status**: Clarified 27/10/2026. G1 passed and G2 observed; Instagram host-browser collection
removed from scope after G2; `reels` keeps its Playwright path without the evasion flag.
Ready for `/speckit-plan`.

**Input**: Owner decision of 27/10/2026, after declining bot-detection evasion: "OK chốt vậy đi"
(settled), approving a spec that moves Threads and Instagram collection to the host browser of
Spec 012, moves Threads to the official API once Meta approves keyword search, and retires the
current Playwright session path with its evasion flags. After G2 the same day the owner narrowed it:
"Bỏ Instagram khỏi Spec 020: chỉ làm Threads qua host browser và gỡ 8 cờ; kênh reels báo không khả
dụng sau khi gỡ đường Playwright." (Drop Instagram: Threads through the host browser and removal of
the eight flags only; the `reels` channel reports unavailable once the Playwright path is removed.)
The owner then revised it: "Giữ đường Playwright cho reels nhưng gỡ cả 8 cờ; threads chuyển sang
host browser. Bị chặn thì kênh báo không khả dụng." (Keep the Playwright path for `reels` but remove
all eight flags; Threads moves to the host browser; a blocked channel reports unavailable.)

## Outcome and audience

A person following a watchlist (Spec 016) needs Threads in each run, collected the same way the
owner would look it up by hand, so the channel keeps working without hiding automation from the
platform. The observable proof is a G3 watchlist run whose Threads outcome comes from the owner's
own Chrome through the host-browser relay, with no author identity at rest, whose period view says
when the collection path changed, and whose `reels` outcome comes from Playwright without any flag
that hides automation, or is reported unavailable when the platform blocks it.

## Clarifications

### Session 2026-10-27

- Q: G1 — may a packaged extractor read Threads and Instagram search pages opened in the owner's own
  Chrome without Meta's written permission? → A: Yes, the owner accepts this (G1 passed).
- Q: Which Instagram surface? → A: Keyword search results, which follow watchlist keywords
  directly; no hashtag mapping. (Superseded by the last answer of this session.)
- Q: Does this feature remove the evasion flag from the TikTok Playwright plugin, TikTok login and
  Creative Center too? → A: Yes, all eight launch sites; TikTok already has the host-browser path and
  the 26/10/2026 decision covers every platform.
- Q: How does Threads obtain an approved keyword-search credential? → A: Through the owner's Threads
  MCP: the host agent calls its keyword search and submits the results to Ignis, so one Meta app and
  one App Review serve both projects. Ignis's own Threads OAuth tier is not used for collection.
- Q: After G2 showed that Instagram's keyword-search grid carries no counters, publication time or
  caption, does Instagram stay in this feature? → A: No host-browser collection for Instagram. The
  `reels` channel keeps its Playwright path, with all eight flags removed; if the platform blocks it,
  the channel reports unavailable with the reason and nothing hides automation or switches path.
  Threads moves to the host browser and its Playwright collection is removed.
- Q: Which Threads path comes first? → A: The owner's Threads MCP whenever it can search public
  posts; the host browser serves Threads only until then. Owner direction (27/10/2026): "Threads nếu
  dùng được MCP thì nên ưu tiên MCP. Nói chung là Ignis sẽ tập trung vào phân tích và cố gắng dùng
  các mcp & plugin có sẵn" (prefer the Threads MCP when usable; Ignis focuses on analysis and uses
  existing MCP servers and plugins where it can).

### Session 2026-10-28

- Q: Does missing historical path provenance make two unchanged periods incomparable? → A: No.
  Both sides wholly unknown retain legacy comparison and response shape; identical proven paths
  compare; different proven paths or proven-versus-unknown across sides refuse with a path reason.
  A side mixing multiple proven identities, or proven and unknown inputs, refuses as mixed.
  (Coordinator decided under the owner's overnight delegation; basis: FR-006 concerns a possible
  path change and unchanged Spec 016/018 channels must retain their existing comparisons. This
  supersedes research R6's earlier blanket unknown refusal.)

## Context: current state (observed 27/10/2026 on `main` at `8a816fb`)

- The `threads` and `reels` channels collect through Playwright with session cookies captured by
  `authenticate_threads` and `authenticate_instagram` (tier 1). Ignis gives each capture a fixed
  30-day lifetime; both current sessions expire on 22/11/2026. G3 snapshots of 25 and 26/10 hold
  data from both channels.
- Eight Chromium launch sites pass `--disable-blink-features=AutomationControlled`, a flag that
  hides automation from the page: `meta_browser_auth.py`, `tiktok_auth.py`,
  `meta_browser_ingress.py` (two), `tiktok_plugin.py` (three) and `creative_center_plugin.py`.
  The owner's decision of 26/10/2026 in `BACKLOG.md` rules out tools that evade bot detection;
  on 27/10/2026 the owner chose the non-evading path.
- Host-browser search (Spec 012) serves TikTok only: `prepare_host_browser_search` has no source
  choice and runs the packaged extractor `tiktok-public-grid-v1`. The G3 routine collects TikTok
  this way on the Finos Chrome profile from the run of 28/10/2026.
- The Threads API tier exists in code (`authenticate_threads(auth_code=...)`). Without Meta's
  approval of `threads_keyword_search`, keyword search returns only the account's own posts and
  Ignis marks it `SELF_ONLY`. The owner's Threads MCP project (`fioenix/threads-mcp`, installed in
  Codex) wraps the same official API and holds an unsubmitted App Review draft dated 14/10/2026,
  which records that Advanced Access needs a verified business.
- Instagram Graph API Hashtag Search takes hashtags only, allows 30 distinct hashtags per 7 days,
  returns recent media for 24 hours, and needs a Business or Creator account linked to a Facebook
  Page plus App Review.
- Meta's Automated Data Collection Terms require Meta's express written permission before
  "Automated Data Collection"; the Terms of Service (section 3.2.3) bar automated access without
  prior permission. Both apply to the current Playwright path; whether they cover a script that
  reads a page the owner opened in their own browser is the subject of gate G1.

## Gates before planning

- **G1 Terms** (passed 27/10/2026, owner accepted): the owner decides whether running a packaged extractor over Threads and Instagram
  search pages opened in their own Chrome is acceptable under Meta's terms. If not, the host-browser
  story 1 stops: Threads waits for the API (story 3), and story 2
  still retires the Playwright path, which carries the same terms question plus evasion.
- **G2 Surfaces**: one manual look in the Finos Chrome profile at a G3 keyword on Threads search and
  on Instagram keyword search records what each result card shows (post link, excerpt, counters, date,
  author elements) and whether results appear while signed in. The extractors are designed from
  that record, as `tiktok-public-grid-v1` was from the TikTok trial of 26/10/2026.
  Observed on 27/10/2026, see [g2-surfaces.md](g2-surfaces.md). Threads: results while signed in,
  counters (`1.4K` style) and `time[datetime]` on each card; post links embed the author handle,
  which Spec 015 FR-005/FR-006 already turn into an identity-free link or "link unavailable";
  image alt text carries an English "Photo by …" attribution. Instagram keyword search: 24 posts
  as `/p/<post-id>/` links without a handle, but the grid shows no counters, no publication time
  and no caption, only image alt text of unknown provenance. The owner removed Instagram from scope
  on 27/10/2026.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Collect Threads search results through the host browser (Priority: P1)

A watchlist run that allows `threads` prepares a host-browser batch for Threads. The owner's Chrome
opens each prepared Threads search, the packaged extractor reads the visible result cards, and the
relay stages the answer, as for TikTok.

**Why this priority**: Threads already feeds G3 through the Playwright path that carries the
evasion flag; this story gives it a replacement before that path is removed.

**Independent Test**: run G3 with `threads` allowed and the Finos profile connected; the Threads
outcome is measured from host-browser observations, each with source URL, query, capture time and
path identity, and none with a handle, display name or profile link.

**Acceptance Scenarios**:

1. **Given** the Finos profile is connected and signed in to Threads, **When** the run prepares
   Threads queries, **Then** each query receives its own measured outcome from the host path.
2. **Given** the Finos profile is not connected, **When** Threads is requested, **Then** the outcome
   is unavailable with the reason, and no other browser or path collects instead.
3. **Given** a card whose excerpt names its author, **When** the answer is validated, **Then** the
   name is removed before any receipt or stored observation, or the record is dropped.

---

### User Story 2 - Remove the evasion flags; keep Playwright only for Reels (Priority: P1)

Once story 1 is live, the Playwright collection path for `threads` is removed, and every
`AutomationControlled` flag is removed from all eight launch sites. `reels` keeps collecting through
Playwright without the flag; when the platform blocks it (login wall, checkpoint, challenge or an
unusable page), the outcome is unavailable with the reason.

**Why this priority**: the flags contradict the owner's decision of 26/10/2026; this story makes
the code match it while keeping Reels data for as long as the platform serves it.

**Independent Test**: a search of `src/` finds no `AutomationControlled`; a run with no host
browser and no approved API reports Threads unavailable rather than collecting through Playwright; a
`reels` run that meets a blocked page reports unavailable, not zero.

**Acceptance Scenarios**:

1. **Given** the change is merged, **When** the source is searched, **Then** no launch site passes a
   flag that hides automation.
2. **Given** stored Threads tier-1 cookies still exist, **When** a run asks for Threads, **Then**
   they are not used for collection.

---

### User Story 3 - Threads uses the owner's Threads MCP once it can search public posts (Priority: P1, takes precedence over story 1 when available)

When the owner's Threads MCP holds an approved keyword-search grant, Threads collects through the
official API via that MCP, and the host-browser path for Threads is used only if the owner keeps it
as a separate choice.

**Why this priority**: the owner prefers existing MCP servers for collection so Ignis can focus on
analysis, and the API is the path Meta permits. Its availability depends on App Review and business
verification, which are outside this feature's control, so story 1 covers Threads until then.

**Independent Test**: with an approved grant in Threads MCP, a G3 run's Threads outcome comes from
the API path; without approval, results limited to the account's own posts are not counted as
evidence.

**Acceptance Scenarios**:

1. **Given** approval is granted, **When** G3 runs, **Then** Threads observations carry the API path
   identity and the period view marks the path change.
2. **Given** no approval, **When** G3 runs, **Then** Threads uses the host path (if G1 passed) or is
   unavailable.

---

### Edge Cases

- The Threads page shows a login wall, a checkpoint or a challenge: the outcome is
  degraded with the reason; the agent does not sign in, solve it or change a setting.
- A result card is a repost, quote or carousel: one observation per public post URL, with the
  queries that found it.
- The page language or layout changes: the extractor fails closed as degraded, never as zero.
- A period spans two collection paths (Playwright, host browser, API): the period view reports the
  channel as not comparable for that pair, with a path-change reason.
- The same post appears under two topic keywords: counted once per topic.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Threads host-browser collection MUST keep every Spec 012 boundary:
  explicit bounded request, the owner's connected Chrome, the loopback relay, no cookie export, no
  debugging port, no unattended or fallback collection.
- **FR-002**: Each surface MUST have one packaged, versioned extractor; the agent only opens the
  prepared URL and runs it, with no clicking or typing on the page. Instagram host-browser collection is out of scope.
- **FR-003**: No observation, receipt or excerpt MAY carry a handle, display name, profile link or
  platform attribution sentence; removal uses seeded vocabulary per locale and fails closed without
  it (Constitution VII, Spec 012 FR-012).
- **FR-004**: Observations MUST keep source URL, exact query, capture time, path identity, excerpt,
  and counters with their units as shown; publication date only when the card shows it.
- **FR-005**: Host-browser preparation MUST let the caller choose TikTok or Threads through one
  optional parameter that defaults to TikTok; no other MCP signature
  changes (owner gate on the MCP surface, AGENTS.md section 8).
- **FR-006**: Threads host-browser and API observations MUST feed the existing `threads` channel,
  and `reels` keeps its channel; the period view MUST mark a pair of periods collected on different paths as not
  comparable with a path-change reason.
- **FR-007**: The Playwright session collection for `threads` and every
  `--disable-blink-features=AutomationControlled` flag MUST be removed; no replacement flag or tool
  that hides automation is added. `reels` keeps Playwright without the flag and MUST report
  unavailable, with the reason, when it meets a login wall, checkpoint, challenge or unusable page. This covers all eight launch sites, including the TikTok
  Playwright plugin, TikTok login and Creative Center.
- **FR-008**: Threads MUST prefer the owner's Threads MCP whenever it holds an approved
  keyword-search grant, and use the host browser only otherwise: the host agent calls its keyword search and submits the results to Ignis
  under the same request, provenance and identity rules as a host-browser answer. Results that
  Threads MCP marks as limited to the account's own posts stay excluded from evidence. Ignis's own
  Threads OAuth tier is not used for collection. Accepting those results is an MCP surface change
  under the same owner gate as FR-005.
- **FR-009**: Changing the G3 routine to use the new paths MUST wait for a separate owner approval.
- **FR-010**: Behaviour MUST be identical on SQLite and PostgreSQL; any migration only seeds
  vocabulary rows.
- **FR-011**: A live run through the implemented Ignis-to-host path is required before the channel
  is reported repaired; a manual lookup or a fixture test alone does not count (Spec 012 FR-010).

### Key Entities

- **Surface extractor**: a packaged, versioned script for one platform's search page that returns
  public post records and counts only.
- **Collection path identity**: which path produced an observation (Playwright session, host
  browser with extractor version, or API); used to decide period comparability.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A live G3 run returns at least one Threads observation through the host path when the
  Finos profile shows results for the same keyword.
- **SC-002**: Zero handles, display names or profile links are found at rest after such a run (the
  author-identity scan of Spec 015 passes).
- **SC-003**: Zero occurrences of `AutomationControlled` remain in `src/` after story 2.
- **SC-004**: Every wrong-page, login-wall, challenge and malformed-answer case is reported as
  degraded or unavailable; none is reported as a measured zero.
- **SC-005**: Every period pair that spans a path change is reported as not comparable.
- **SC-006**: A live `reels` run after the flags are removed either returns observations or reports
  unavailable with a blocking reason; it never reports a measured zero for a blocked page.

## Assumptions

- The owner's Finos Chrome profile is signed in to Threads, as it is to TikTok.
- Without the flag, Instagram may block the Playwright `reels` path sooner; the owner accepts that
  risk and the risk of a checkpoint on the Instagram account whose session it uses.
- Rounded counters are acceptable as rounded values; exact figures are not inferred.
- App Review and business verification for Threads are the owner's actions and may not succeed;
  story 3 waits for them and does not block stories 1 and 2.
- The Instagram tier-1 session keeps its 30-day lifetime set by Ignis and must be renewed before it
  expires (currently 22/11/2026); the Threads session stops mattering once story 1 lands.
