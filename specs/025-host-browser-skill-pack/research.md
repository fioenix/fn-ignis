# Research: live host-browser run, 2026-11-11

One bounded TACTICAL run per source, keyword **áo khoác chống nắng**, through the owner's Chrome
profile **Finos** (Claude in Chrome, deviceId `a20397fd-…`), between about 23:12 and 23:20
Asia/Ho_Chi_Minh. The owner confirmed in chat on 2026-11-11 that real TikTok and Threads sessions
were already permitted. No page-content clicks, typing, sign-in, consent or social actions on a
platform page; the only clicks were the relay's own "Open search" buttons on `127.0.0.1`.
No author identity is reproduced here.

## Operation log

### TikTok (`tiktok-public-grid-v3`)

| Step | Action | Result |
|---|---|---|
| 1 | `prepare_host_browser_search` (source `tiktok`, 1 query, limit 12, lifetime 900 s) | `request_id`, `relay_url`, `tab_script` (~4 KB), `search_url` |
| 2 | Open `relay_url` in a tab of the agent's group; click "Open search: <query>" | New tab on the TikTok search URL, `window.opener` set |
| 3 | Pre-check in the search tab: `lang`, card count, opener, login button | `vi-VN`, 12 cards, opener true, no login wall |
| 4 | Evaluate `tab_script` verbatim in the search tab | `{posted: true, status: HEALTHY, records: 12}` |
| 5 | Read the relay page | `STAGED — Task listener closed` |
| 6 | `submit_host_browser_search` | `ACCEPTED`, 12 observations, all `published_at: null`, counters unknown |

Wall time from prepare to accepted: about 40 s.

### Threads (`threads-search-top-v2`)

| Step | Action | Result |
|---|---|---|
| 1 | `prepare_host_browser_search` (source `threads`) | Same shape; `tab_script` (~8 KB) uses an AES-GCM encrypted URL-fragment handoff, not `postMessage` |
| 2 | Open `relay_url`; click "Open search: <query>" | Threads search tab (UI `en`) |
| 3 | Evaluate `tab_script` | The tool returned `{}`: the script is `async` and the evaluator did not await it. The tab still navigated to the relay `/receive` page 100 ms later |
| 4 | Read the relay page | `STAGED` |
| 5 | `submit_host_browser_search` | `ACCEPTED`, 9 observations, all with `published_at` and rounded/exact counters |

Content was customer voice: complaints ("sun goes through the jacket"), requests for links,
comparisons of brands, a second-hand listing.

### Instagram keyword search (observation only, no extractor exists)

- URL `https://www.instagram.com/explore/search/keyword/?q=<query>`; signed-in grid, UI `en`, no login wall.
- 24 tiles, every tile a `/p/<id>/` link; each carries an icon labelled `Reel` or `Carousel`.
- 15 of 24 tiles have an `img[alt]` that holds the caption (mean about 450 characters); 1 of 15 contains an `@mention`, 5 contain hashtags; none starts with an author attribution.
- No `time[datetime]`, no counters in the grid. Most captions were seller listings, not customer voice.

## Findings

1. **The packaged path works on both live sources.** No extractor change is needed to run them today.
2. **The `.venv` wheel install breaks when `uv sync` or `uv run` runs in the checkout.** The running MCP server reads `tiktok_search.js` from `site-packages`; an editable reinstall removed it, and `prepare_host_browser_search` failed with `No such file or directory`. Reinstalling `dist/fn_ignis-0.10.0-py3-none-any.whl` fixed it without a restart.
3. **Async tab scripts return `{}` through Claude in Chrome's evaluator.** Success must be read from the relay page (`STAGED`) or the tab's navigation to `/receive`, not from the evaluator's return value.
4. **Tab-group drift.** Tabs the owner touches can leave the agent's tab group; every step must re-read `tabs_context_mcp` before acting on a tab id.
5. **TikTok hashtags can carry creator handles** (for example a hashtag equal to the poster's name). The TikTok extractor keeps hashtags after the caption, so this is a Principle VII gap for free-text handles. Not fixed here.
6. **TikTok `published_at` is derivable.** The upper 32 bits of a TikTok video id are the Unix publish second; four sampled ids decode to 2024-06 to 2026-09. Unverified against the rendered date.
7. **Instagram keyword search returns captions only.** No date, no counters, and mostly seller posts: it is supply-side context (what sellers pitch), not customer voice.

## Repeat run for collection variance (backlog VAL-3, reduced)

Same keyword, same profile, same `result_limit` 12, second run about 44 minutes after the first
(23:56 Asia/Ho_Chi_Minh). Overlap is over canonical source ids.

| Source | Run 1 | Run 2 | Shared | Jaccard |
|---|---|---|---|---|
| TikTok | 12 | 12 | 10 | 10/14 = 0.71 |
| Threads (Top) | 9 | 7 | 5 | 5/11 = 0.45 |

- TikTok's visible grid is stable within an hour; the two new items replaced two at the tail.
- Threads Top churns: one of the two new posts was published about 13 hours before the run, and the
  record count itself moved from 9 to 7 because the extractor keeps only fully rendered cards.
- Two runs per source are a floor, not the backlog's three-run study; read this as a first estimate of
  sampling noise, not a tolerance. The 30 percent Jaccard kill line proposed in VAL-3 is not crossed.

## T014 live acceptance on the built wheel (2026-11-12)

Server: wheel `fn_ignis-0.10.0` built from main `ebe9e67` (Spec 025 Phase 2 and 3 merged), reinstalled
into the server environment and restarted; `fn-ignis://guide/ignis-tiktok-browser` was read from the
running server before the run. Browser: Claude in Chrome on the Finos profile. Keyword `áo khoác chống
nắng`, `TACTICAL`, `result_limit` 20, one source at a time, steps exactly as the packaged
`ignis_browser_relay` guide lists them.

| Source | Prepare to accepted | Accepted | Outcome | Steps outside the guide |
|---|---|---|---|---|
| TikTok | 69 s | 12 | HEALTHY, `search_verified` | none |
| Threads (Top) | 79 s | 8 | HEALTHY, `search_verified` | none |

- Threads' evaluator returned `{}` as the guide predicts; after two seconds the tab was on `/receive`
  ("Answer sent to the relay") and submit returned `ACCEPTED`. The script ran once.
- Both runs exceed SC-003's 60 seconds. Each includes a deliberate 8-second page-load wait and the
  agent's tool round trips; the 2026-11-11 baseline of about 40 seconds for TikTok had no fixed wait.
  SC-003 is not met by this run; the wait is the first thing to shorten (guide step 5 is optional).
- Identity: no Threads excerpt carries a handle or profile link. Seven TikTok excerpts keep hashtags
  that read as creator or channel names; this is the documented OQ-2 exception, not a leak.
- Limit: the run was made by the coordinating session that wrote the guides, not a fresh session, so it
  proves the shipped wheel serves the guides and both sources accept, but not SC-001's "fresh agent
  needs zero steps outside the skill". T014 stays open for that run.

## T016 TikTok rendered date versus video id (2026-11-12)

Three videos accepted in the T014 run, opened by URL on the Finos profile (navigation only). The rendered
date is read from the post header; a date without a year is the current year.

| Video id | `UTC(id >> 32)` | Rendered date | Match |
|---|---|---|---|
| 7643765792374361362 | 2026-05-25 09:55:09 | 5-25 (2026) | yes |
| 7555873331275222280 | 2025-09-30 13:27:31 | 2025-9-30 | yes |
| 7381292723459869969 | 2024-06-17 02:25:35 | 2024-6-17 | yes |

All three agree to the day (the page renders in Asia/Ho_Chi_Minh; none of the times crosses midnight
there). FR-007's precondition is met; Phase 5 proceeds.

## T015 relay guide against the findings (2026-11-12)

Each failure the runs produced, mapped to where `ignis_browser_relay.md` handles it:

| Finding | Guide location |
|---|---|
| Wheel install replaced by an editable one (finding 2) | Failure table, "Prepare fails with `No such file or directory`" |
| Tab-group drift (finding 4) | Step 4 and failure table, "Tab is not in the same group" |
| Async tab script returns `{}` (finding 3) | Failure table, "Evaluator returns `{}`" |
| Opener refusal | Failure table, `This tab was not opened by the relay` |
| Unapproved search page | Failure table, `Unapproved search page` / `This tab is not an approved search page` |
| Ticket expiry | Failure table, "Relay never stages" |
| Wrong signed-in profile | "Before you start" and failure table, "Wrong account or profile" |
| Unsupported UI language | Added: failure table row for Threads `DEGRADED` "page locale is unsupported"; TikTok does not gate on language (TikTok guide) |

Findings outside the relay guide: finding 1 (the packaged path works) needs no row; finding 5 (hashtags
can carry creator names) is an extractor matter the owner settled as free text outside Principle VII
(Spec 025 OQ-2, TikTok guide); finding 6 (TikTok dates) is Phase 5, T016–T019; finding 7 (Instagram
captions only) belongs to Phase 6.

## T020 Instagram transport spike (2026-11-12)

Owner authorized a real Instagram session on the Finos profile (spec Clarifications, 2026-11-12). A local page on
`127.0.0.1` with one button opened `https://www.instagram.com/explore/search/keyword/?q=áo%20khoác%20chống%20nắng`
in a new tab on click, as the relay does. After load, one read-only evaluation in that tab returned:

| Check | Result |
|---|---|
| `window.opener` | `null`: the opener does not survive Instagram's load |
| `<html lang>` | `en` |
| Sign-in wall | none |
| Tiles linking `/p/<id>/` | 24 (no `/reel/<id>/` link on this grid) |
| Tile icon labels | `Reel`, `Carousel`, none |
| Tiles with a caption in `img[alt]` | 12, mean 367 characters |
| Captions with an `@mention` | 1 |
| Captions starting with an author attribution | 0 |

Transport chosen: `fragment_receive` (Threads' path). No click, typing or scrolling on the Instagram page; both tabs
closed after the check. 12 captioned tiles is close to SC-002's floor of 10.

## Instagram attribution check (2026-11-12, PR 152 security review)

Same keyword grid on the Finos profile, UI `en`, one read-only evaluation after load: 24 tiles; 14 render no
image element, 10 carry an `img[alt]`, and every one of those 10 is the poster's own caption. None matches an
automatic attribution shape ("Photo/Video by <name> on/in/with …"), and none reads "May be an image of …".
Instagram's own attribution wording therefore stays unobserved. Records are accepted only on a page locale with
seeded wording (`instagram_attribution_en`, borrowed from Threads' observed Meta wording); any other locale
returns `DEGRADED` with no observations until its wording is observed and seeded.

## T029 Instagram live acceptance (2026-11-12)

Server: wheel built from main `fc4fef0` (PR 152 merged), reinstalled, this session's server restarted, and
`fn-ignis://guide/ignis-instagram-browser` read from it first. Browser: Claude in Chrome on the Finos profile, UI
`en`. Keyword `áo khoác chống nắng`, `TACTICAL`, `result_limit` 20, steps exactly as the relay and Instagram guides
list them: prepare, open the relay, click "Open search", evaluate `tab_script` once (the evaluator returned `{}`
as the guide predicts), relay `STAGED`, submit.

| Measure | Result |
|---|---|
| Prepare to accepted | about 65 s (15:49:31 to 15:50:36 UTC) |
| Outcome | `ACCEPTED`, query `HEALTHY`, 12 observations (SC-002 needs at least 10) |
| Links | all 12 `https://www.instagram.com/p/<id>`, no account segment, query or fragment |
| `@handles`, profile links | none in any excerpt |
| Automatic attribution ("Photo by … on") | none in any excerpt |
| Phone number, email | one caption: both replaced by `[REDACTED_PHONE]`, `[REDACTED_EMAIL]` |
| Dates, counters | `published_at` null, `metric_known` false, as designed |
| Steps outside the guides | none |

Identity check: one caption carries a seller's first name in free text (not quoted here); free-text personal
names are outside Principle VII under its own documented clause, as for TikTok hashtags (OQ-2). Content is
seller listings and one garment-maker's advice post: supply-side context, as the guide says, not customer voice.
The `en` attribution wording stays unobserved on Instagram; the locale gate keeps any other UI language closed.
