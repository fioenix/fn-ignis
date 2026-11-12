# Ignis Instagram browser search

Use with the `ignis_browser_relay` guide, which holds the shared steps and failure table.

- `source: "instagram"`. The search opens `https://www.instagram.com/explore/search/keyword/?q=<query>`, the
  signed-in keyword grid. This is the host-browser tier only; the retired `reels` surface stays refused.
- Transport: as for Threads, the tab script encrypts the answer and, 100 ms later, navigates the same tab to the
  relay's `/receive` page (Instagram drops `window.opener`, checked 2026-11-12). The evaluator can return `{}`.
  Wait about two seconds and confirm the relay shows `STAGED` or the tab is on `/receive`. Never run it twice.
- Extractor `instagram-keyword-grid-v1` keeps each tile's image caption (`img[alt]`) and skips tiles without one.
  Each observation has a canonical `https://www.instagram.com/p/<id>` link without the account. Publication
  time, views and interactions are unknown; the grid shows none.
- In a mission the source is admitted by the manifest resource `instagram_host_browser` and stored as
  platform `reels` under its own collection path. Instagram links name no account, so the requester's own
  posts cannot be excluded from a mission; say so when it matters.
- Captions are mostly seller listings: supply-side context (what sellers pitch), not customer voice.
- Hashtags are kept as written. A hashtag can equal a creator's name; it is a free-text name outside
  Principle VII (owner decision, Spec 025). `@mentions` are masked.
- Records are accepted only on a page language whose attribution wording is seeded (`en` today). Another
  interface language, such as `vi`, returns `DEGRADED` with no observations: report it, do not retry.
- A sign-in form or challenge, a missing page language, or a grid without captions returns `DEGRADED`.
- Live check (2026-11-12): 24 tiles, 12 with a caption.
