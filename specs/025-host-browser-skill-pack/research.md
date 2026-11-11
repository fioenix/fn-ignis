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
