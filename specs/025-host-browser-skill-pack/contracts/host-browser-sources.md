# Contract: host-browser sources

## `prepare_host_browser_search`

- Parameters unchanged. `source` accepts `"tiktok"` (default), `"threads"` and, new, `"instagram"`.
- For `instagram` the response carries `extractor_version: "instagram-keyword-grid-v1"` and one
  `search_url` per query of the form `https://www.instagram.com/explore/search/keyword/?q=<encoded>`.
- An unknown `source` is refused before any relay starts, as today.
- `"reels"` is not a host-browser source; collection requests naming the retired `reels` surface keep
  returning `SURFACE_RETIRED`.

## `submit_host_browser_search`

- Unchanged shape. Instagram observations carry `collection_path: "host_browser:instagram-keyword-grid-v1"`,
  `published_at: null`, `metric_known: false`, `source: "instagram"`, platform `reels`.
- TikTok observations carry a derived `published_at` once FR-007 is enabled; otherwise unchanged.

## Packaged guides (MCP prompts and resources)

| Prompt name | Resource URI | Content |
|---|---|---|
| `ignis_browser_relay` | `fn-ignis://guide/ignis-browser-relay` | Shared relay procedure and failure table |
| `ignis_tiktok_browser` | `fn-ignis://guide/ignis-tiktok-browser` | TikTok specifics, points to the relay guide |
| `ignis_threads_browser` | `fn-ignis://guide/ignis-threads-browser` | Threads specifics (async script, `/receive`) |
| `ignis_instagram_browser` | `fn-ignis://guide/ignis-instagram-browser` | Instagram specifics |

Prompts and resources are not tools; the catalog stays at 41 tools.
