# Data model: Spec 025

No new table or migration. Three in-memory shapes and one derived field.

## Host-browser source descriptor

One immutable record per `source` value (`tiktok`, `threads`, `instagram`).

| Field | TikTok | Threads | Instagram |
|---|---|---|---|
| `origin` | `https://www.tiktok.com` | `https://www.threads.com` | `https://www.instagram.com` |
| `search_path` | `/search/video` | `/search` | `/explore/search/keyword/` |
| `search_url(query)` | `origin + search_path + "?q=" + quote(query)` | same | same |
| `transport` | `opener_post_message` | `fragment_receive` | decided by spike: `fragment_receive` if the page has no usable `window.opener`, else `opener_post_message` |
| `record_path` | `^/@[A-Za-z0-9_.]+/video/[0-9]+$` | `^/(?:@[A-Za-z0-9_.]+/post/|t/)[A-Za-z0-9_-]+(?:/media)?/?$` | `^/(?:p|reel)/[A-Za-z0-9_-]+/?$` |
| `accepted_record_path` (validator) | `^/(?:@[A-Za-z0-9_.]+/video/|share/video/)[0-9]+$` | same as `record_path` | same as `record_path` |
| `canonical_url(path)` | `/share/video/<id>` | `/t/<id>` | `/p/<id>/` |
| `extractor_version` | `tiktok-public-grid-v3` | `threads-search-top-v2` | `instagram-keyword-grid-v1` |
| `platform` | `tiktok` | `threads` | `reels` |
| `connector_surface` | existing | existing | `instagram_host_browser` (never `reels`, which stays retired) |
| `sampling.ordering` | `visible_grid` | `top_visible_sample` | `visible_grid` |

Validation: every request and submitted record is checked against its own descriptor; a record whose URL
matches another source's pattern is rejected.

## Instagram record (extractor output)

| Field | Rule |
|---|---|
| `source_url` | canonical `/p/<id>/` on `www.instagram.com`, no query, no fragment, no account segment |
| `excerpt` | the tile image's `alt` caption, NFC, control/format characters removed, at most 2000 characters; leading author attribution removed; `@mentions` masked downstream as for other sources |
| `published_at` | `null` (the grid exposes none) |
| `counters` | none (unknown) |
| `kind_hint` | `reel` or `carousel` from the tile icon label, when present |

A tile without a non-empty caption is skipped. A page with a login form, challenge or no tiles yields
`DEGRADED` with no records.

## TikTok publication date

`published_at = UTC(video_id >> 32)` when `video_id` is a decimal integer and the result lies between
2016-09-01 and the submission time plus one day; otherwise `null`. Applied at submit time to new
observations only, and only after the recorded rendered-date check (FR-007) passes.
