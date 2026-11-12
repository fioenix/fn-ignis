# Ignis TikTok browser search

Use with the `ignis_browser_relay` guide, which holds the shared steps and failure table.

- `source: "tiktok"`. The search opens `https://www.tiktok.com/search/video?q=<query>`.
- Transport: the tab script posts the answer to its relay opener and returns
  `{posted, status, records}` synchronously. If it returns
  `{posted: false, reason: 'This tab was not opened by the relay'}`, reopen the search from the relay button.
- Extractor `tiktok-public-grid-v3` keeps only each video's caption element and the hashtags after it. The
  interface language does not gate records.
- Each observation has a canonical `https://www.tiktok.com/share/video/<id>` link without the account.
  Views and interactions are unknown, and `published_at` is null.
- Hashtags are kept as written. A hashtag can equal a creator's name; it is a free-text name outside
  Principle VII (owner decision, Spec 025). `@mentions` are masked.
- Live baseline (2026-11-11): 12 records in about 40 seconds from prepare to accepted.
