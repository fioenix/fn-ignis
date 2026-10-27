# G2 surface observation — Spec 020

Observed **27/10/2026, approximately 22:45–22:54, Asia/Ho_Chi_Minh**.
Branch: `claude/meta-host-browser-spec`. Keyword: **áo khoác chống nắng**.

**Disposition: partial; G2 is not fully observed.** Threads was usable; the Instagram-only
retry on **27/10/2026, approximately 22:59, Asia/Ho_Chi_Minh** was still denied by the
browser origin approval gate before its page could be read. The tool reported a saved
permission or managed-policy denial despite the owner's renewed authorization.
This record does not establish extractor implementation, relay acceptance, or channel repair.

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

### Navigation attempt and availability

- Retried **27/10/2026, approximately 22:59, Asia/Ho_Chi_Minh**, after the owner said
  they would approve the Instagram origin; whether that approval was saved is not known. Reconfirmed browser inventory before navigation:
  `family: chrome`, `type: extension`, `profileName: Finos`, browser ID `2`.
- Exact attempted URL:
  `https://www.instagram.com/explore/search/keyword/?q=%C3%A1o%20kho%C3%A1c%20ch%E1%BB%91ng%20n%E1%BA%AFng`
- Origin approval **did not work** for this attempt. The browser tool rejected
  navigation before page observation, reporting: **"A saved user permission setting
  blocks this action"** and **"A saved permission or managed policy denies access."**
  The denied origin was `https://www.instagram.com`. The tool did not establish
  which of those policy sources applied. This was a browser authority denial,
  **not** an Instagram page response or proof of a nonexistent search route.
- Stopped this surface immediately. No settings changes, alternate origin, browser,
  profile, Playwright instance, API, guessed route or indirect access was attempted.
- Final page URL, redirect and actual Instagram search URL: **not observed**.
  Whether the requested route exists: **not observed**.
- Signed-in results, login wall, consent interstitial, checkpoint or challenge:
  **not observed**.

### Counts and scrolling

- Distinct result-item count: **not observed**, not zero. No result paths were
  available to track in memory.
- Scrolling, lazy loading, per-load increments, DOM virtualization and exhaustion:
  **not observed**. No page was available for the authorized scroll observation.

### Card contents and measurement formats

- Canonical post URL pattern (`/p/`, `/reel/` or other), and whether it embeds an
  author handle: **not observed**.
- Excerpt/caption availability on the results page: **not observed**. No post was
  opened; caption availability after opening a post is also **not observed**.
- Media type (text, image, video or carousel): **not observed**.
- Likes, comments, plays/views, other counters and their exact display formats:
  **not observed**. This attempt does not establish that a grid shows no counters.
- Publication time, relative time and display format: **not observed**.

### Author elements and extractor hooks

- Handle, display name, avatar, profile link, verified badge and their placement:
  **not observed**.
- Attribution templates in image alt text or captions, including English
  `Photo by <author>` or Vietnamese equivalents: **not observed**.
- Stable structural hooks (roles, link shapes, aria labels, data attributes) and
  opaque/unstable classes: **not observed**. No Instagram selector is established.

### Empty-answer ambiguity

- Suggestion-only views and explicit no-results text, including exact Vietnamese
  wording: **not observed**.
- The origin denial cannot be classified as healthy emptiness, a login wall or
  an Instagram search result. No healthy-empty signature was established.

The Instagram retry remains blocked before page observation; G2 is still partial.
All Instagram surface properties remain **not observed**. Threads Recent rendering,
video cards, result-card verification badges and explicit empty-state wording also remain
unobserved from the earlier visit. The Threads section is unchanged by this retry.
No G2 pass, planning readiness or working extractor is claimed.
