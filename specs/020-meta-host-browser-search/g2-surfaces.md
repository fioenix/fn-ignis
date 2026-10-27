# G2 surface observation — Spec 020

Observed **27/10/2026, approximately 22:45–22:54, Asia/Ho_Chi_Minh**.
Branch: `claude/meta-host-browser-spec`. Keyword: **áo khoác chống nắng**.

**Disposition: both populated surfaces observed within the bounded G2 visit.**
Threads was usable in the earlier visit. The third Instagram attempt on
**27/10/2026, approximately 23:00–23:04, Asia/Ho_Chi_Minh** passed origin approval
and rendered signed-in keyword results. Unobserved properties remain explicit below.
This record does not establish a G2 pass, planning readiness, extractor implementation,
relay acceptance, or channel repair.

## Scope and method

- Confirmed the owner's real Chrome profile **Finos** from the browser capability's
  inventory (`family: chrome`, `type: extension`, `profileName: Finos`, browser ID `2`)
  before opening a Meta page. The other listed Chrome profile was not used.
- An additional `chrome://version` attempt was blocked by the tool's HTTP/HTTPS-only
  URL policy. No workaround was attempted; the profile confirmation above is browser
  inventory evidence, not a read of Chrome's profile path.
- Read Spec 020, including Clarifications, G2 and FR-002–004; Spec 012 FR-012–013;
  and `src/ignis/infrastructure/connectors/host_browser/tiktok_search.js`, loaded as
  `tiktok-public-grid-v1`. That extractor checks the query, rendered card/link structure,
  content availability and uniqueness, and returns capture provenance. Its TikTok
  selectors are not evidence of Meta structure.
- Used URL navigation, scrolling, accessibility reading and read-only rendered-DOM
  inspection through the connected Chrome extension. No separate Playwright browser,
  headless browser or new browser profile was started. The tool's DOM-reading API is
  named `playwright.evaluate`; it inspected this same real Chrome tab only.
- No page-content clicks, typing, sign-in, challenge handling, consent interaction,
  settings changes or social actions. No cookies, storage or credentials were read.
  No screenshots were saved. No real author identities or post excerpts are reproduced here.

## Threads keyword search

### Navigation and availability

- Requested and final URL:
  `https://www.threads.com/search?q=%C3%A1o%20kho%C3%A1c%20ch%E1%BB%91ng%20n%E1%BA%AFng`
- Results appeared in an existing signed-in session. Profile, notifications, messages
  and new-thread controls were present; none was opened.
- Login wall, consent interstitial, checkpoint or challenge: **not observed**.
- The interface was English. The populated search field contained the exact keyword.
- Rendered sort links exposed **Top** at the requested URL, **Recent** at the same
  URL plus `&filter=recent`, and **Profiles** plus `&filter=profiles`.
  These hrefs were read, not clicked. The Recent URL variant was **not loaded**;
  its result layout and ordering are **not observed**.

### Counts and scrolling

- Initially **3** distinct canonical post links/cards were rendered; after the first
  two-page downward scroll, **9** were in the DOM.
- Later DOM counts fell as older cards were removed. A separate in-memory set of
  canonical post paths then counted **20 distinct cards** during the remaining
  observation. This is an exact count for that tracked interval and a lower bound
  for the whole visit; earlier cards were not all included in that set. The exact
  whole-visit unique total is **not observed**. The final DOM held **10** cards.
- Lazy loading on scroll: **yes**. New distinct cards in successive tracked reads
  increased from **7 → 11 → 12 → 12 → 18 → 20**. The unchanged read was followed
  by more results, so it was not evidence of exhaustion.
- Observed increments were **4**, **1**, **0**, **6**, **2** distinct cards between
  those reads. Roughly **1–6** new cards appeared per sampled read after scrolling;
  this does not establish a backend batch size. One earlier DOM increase was **6**.
- Scrolling was stopped at the bounded target, not at a proven end of results.

### Card contents and measurement formats

- Canonical post href pattern: `/@<author>/post/<post-id>` on `www.threads.com`.
  Image-media links also used `/@<author>/post/<post-id>/media`.
  The timestamp link targets the canonical post. The URL itself embeds author identity;
  this is a concrete issue to resolve against FR-003 before designing persisted URLs.
- Post body text was available directly as rendered text, separate from the author
  header and action row. No post text is copied here. Some bodies were long and
  multiline; a `Translate` button could follow them.
- Media observed: text-only cards, single-image cards and multi-image/carousel-style
  cards. A carousel indicator displayed exactly **`1 / 2`**. Multiple image nodes
  and `Combine media into panorama` buttons could occur within one card; image-node
  counts must not be treated as post counts or a proven slide count.
- Video: **not observed**; sampled card DOM checks returned **0** `video` elements.
- Action row: icons named **`Like`**, **`Reply`**, **`Repost`**, **`Share`**.
  One observed card displayed respectively **`12`**, **`9`**, no numeric text, **`2`**.
  Another displayed **`276`**, **`108`**, **`38`**, **`142`**.
  A text-only card displayed **`1.4K`**, **`133`**, **`26`**, **`126`**.
  Thus `K` with a decimal point is observed; `1.4K` is rounded display text,
  not proof of an exact count. `1,2K`, `12 N`, `M` and `B`: **not observed**.
- Some action controls had empty numeric text. An icon without a number is not
  evidence of an exact zero. DOM `aria-label` on these sampled action wrappers was
  null; descendant SVG `title` supplied the action name. Accessibility reading
  combined these as labels such as `Like 12`, `Reply 9`, `Repost 38`, `Share 142`.
- Views and plays counters: **not observed**. Sidebar trending-post and follower
  counts were outside result cards and are not engagement measurements for the results.
- Publication time was shown by a linked `time` element. Observed visible text:
  **`3h`**, **`4h`**, **`1h`**, **`6d`**, **`3d`**, **`10/06/26`**, **`09/29/26`**.
  Calendar dates are **MM/DD/YY**, confirmed by `09/29/26` and matching datetime/title.
  The element also supplied an ISO `datetime`, for example
  `2026-10-27T12:01:43.000Z`, and a title such as
  `Tuesday, October 27, 2026 at 7:01 PM`.
  Accessibility expanded `3h` to `3 hours ago`; preserve the distinction from visible text.

### Author elements and extractor hooks

- Avatar at the card's leading edge; its image accessible name followed
  `<author>'s profile picture`. A surrounding avatar control exposed that name
  together with `Follow`. Do not treat either as excerpt content.
- Author-name/handle link in the card header, beside the timestamp region, points to
  `/@<author>`. Sampled final cards each contained **1** such profile link.
  A separate display-name field in result cards: **not observed**.
- A `Verified` image was observed beside an account in the separate follow-suggestions
  sidebar. Verified badges in sampled result cards: **not observed**; the final
  ten-card structural check found **0**. Keep sidebar author information out of cards.
- Content image alt text included an English attribution template:
  **`Photo by <author> on <date>. May be …`**. It appeared both as image text and,
  for some media, the enclosing link/button's accessible name. It can name a different
  identity from the card header. Do not retain the attribution or assume stripping
  only the header is sufficient. Vietnamese `do … tạo` attribution: **not observed**.
- Candidate structural hooks actually observed: canonical `/post/` link shape;
  descendant `time[datetime]`; profile link shape; `img[alt]`; `role="link"`,
  `role="button"`, `role="img"`; and SVG `title` action names listed above.
  A result card was found structurally by walking from its timestamp link to an
  ancestor containing the action row. This is an observation, not a validated selector.
- Sampled cards had **no** `data-testid` or `data-e2e` hooks. Their div/span wrappers
  used many opaque classes such as `x1lliihq`, `x78zum5`, `xrvj5dj` and `x1n2onr6`;
  treat these as unstable. No semantic `article` card hook was established.
- Deduplicate canonical post links within a card; do not count the media link as
  another result. Streaming/deduplicated observation is needed because the DOM is
  virtualized; a final snapshot alone undercounts the visit.

### Empty-answer ambiguity

- The first read exposed the signed-in navigation shell but **0** post links;
  results rendered afterward without another navigation. That initial shell is not
  a measured empty result.
- `Loading...` appeared while more cards were pending. A brief unchanged count also
  preceded another load.
- `Trending now` and `Follow suggestions` occupied separate regions. The page was
  not suggestion-only during the populated observation; these regions must not be
  mistaken for keyword result cards.
- Explicit no-results text, including exact Vietnamese empty-state wording:
  **not observed**. No healthy-empty signature was established by this visit.

## Instagram keyword search

### Navigation and availability

- Earlier attempts, including approximately 22:59 on 27/10/2026, were denied by the browser origin gate before Instagram could be observed.
- Third attempt: **27/10/2026, approximately 23:00–23:04, Asia/Ho_Chi_Minh**.
  Fresh inventory confirmed `family: chrome`, `type: extension`, `profileName: Finos`,
  browser ID `1`; the other profile was not used. IDs are session-local; ID `2` in
  the earlier method record describes the earlier visit.
- Requested and final URL, unchanged through scrolling:
  `https://www.instagram.com/explore/search/keyword/?q=%C3%A1o%20kho%C3%A1c%20ch%E1%BB%91ng%20n%E1%BA%AFng`
- Origin approval **worked**. The requested route rendered a populated grid, without
  an observed redirect or nonexistent-route message.
- Existing signed-in session: profile navigation, messages, notifications and new-post
  controls were present; none was opened. Heading: **`Áo khoác chống nắng`**.
  Navigation was English. Login wall, checkpoint, challenge and consent interstitial:
  **not observed**.
- Only URL navigation, one downward scroll and read-only rendered-DOM/accessibility
  inspection were used. No post opening, page-content click, typing, sign-in,
  consent handling, settings or social action. No cookies, storage or credentials
  were read; no screenshots were captured or saved. No fallback browser, profile,
  separate Playwright instance, API or alternate origin was used.

### Counts and scrolling

- The initial accessibility read exposed the signed-in shell without result cards.
  A subsequent DOM read found **24 distinct canonical post paths**, tracked from
  that read in an in-memory set only.
- One two-page downward scroll moved the document to approximately `scrollY=1690.5`
  (viewport height `862`, document height `4768`). The next read still held **24**
  DOM cards and **24** tracked distinct paths: **0** new paths in that interval.
- A main-region `role="progressbar"` was present before and after scrolling.
  This does not prove another batch completed or loading failed.
- Lazy-load additions, per-load batch size and DOM virtualization: **not observed**
  in this bounded interval. No sampled card removal was established.
- Stopped because the approximately 20-item target was exceeded, not at proven
  exhaustion. End of results and no-more-load behaviour: **not observed**.

### Card contents and measurement formats

- All **24** canonical links used **`/p/<post-id>/`**, including the tile marked
  `Reel`. These paths do **not** embed an author handle. `/reel/` and other post
  path shapes: **not observed** in the sampled grid.
- All sampled tile links had empty rendered text; main-region rendered text was
  only the keyword heading. A separate visible excerpt/caption field: **not observed**.
  Caption availability after opening a post: **not observed**; no post was opened.
- **23** image nodes had nonempty alt text, approximately **16–111 whitespace-separated
  words** each. Text is available in the results DOM/accessibility surface, but its
  provenance as caption, generated image description or mixed content is **not
  established**. No alt text is reproduced; it must not automatically become an excerpt.
- Media: **23** image tiles and **1** tile containing a `video` element. Descendant
  SVG labels: **`Carousel`** on **22** tiles, **`Reel`** on **1**. One image tile
  had neither label. The carousel icon does not establish a slide count.
- The sampled grid showed **no likes, comments, plays/views or other numeric counters**
  as rendered tile text. Main-region Like/Comment aria-label checks also found none.
  Exact counter display formats: **not observed**. No hover or detail interaction
  was used; absence on this grid is not an exact zero engagement count.
- Publication time and format: **not observed**. Main contained **0** `time`
  elements and no observed visible relative or calendar timestamp.

### Author elements and extractor hooks

- Result tiles had no observed separate handle, display name, avatar, profile link
  or verified badge. Main-region links were the **24** post links only. Sampled SVG
  labels were `Carousel` and `Reel`, with no `Verified` label.
- The signed-in account's profile picture/name and profile link sat in the navigation
  rail, outside results; their values are not recorded and are not result-author data.
- English `Photo by <author>`, `Photo shared by <author>` and `Video by <author>`
  prefixes: **not observed** in sampled image alts. Exact Vietnamese author-attribution
  templates and author-identity placement within free-form alt text: **not established**.
  Broad Vietnamese phrase matches were inconclusive, not proof of attribution.
  No claim that the alt strings are identity-free is made.
- Candidate structural hooks observed: `main`; canonical `a[href]` matching
  `/p/<post-id>/`; `img[alt]`; `video`; roles `link`, `img`, `progressbar`;
  SVG `aria-label="Carousel"` and `aria-label="Reel"`. The 24 tile anchors had
  no aria label themselves.
- Main contained **0** `article` elements and **0** `data-testid` or `data-e2e`
  hooks. Opaque tile/image classes included `x1i10hfl`, `xjbqb8w`, `_a6hd`,
  `x5yr21d`, `xu96u03`; treat these as unstable. Structural hooks are observations,
  not validated selectors or guarantees across locales/layouts.
- Deduplicate canonical post paths, not images, carousel badges or media types.
  Behaviour under longer scrolling remains **not observed**.

### Empty-answer ambiguity

- The initial shell exposed no result cards, then **24** rendered without another
  navigation. The initial shell is not a measured empty result.
- A progressbar and unchanged count do not establish exhaustion or measured zero.
  This visit was populated, not suggestion-only.
- Exact no-results wording (English or Vietnamese) and healthy-empty signature:
  **not observed**.

Both surfaces now have bounded populated-result observations. Instagram origin access
succeeded; the former origin blocker is no longer the current outcome. Instagram
lazy-load additions, virtualization, exhaustion, publication time, counter formats,
post-detail captions, exact alt-text provenance/identity attribution and empty-state
wording remain unobserved or unestablished as detailed above. Threads Recent rendering,
video cards, result-card verification badges and explicit empty-state wording remain
unobserved from the earlier visit. The Threads section is byte-for-byte unchanged.
No G2 pass, planning readiness or working extractor is claimed.
