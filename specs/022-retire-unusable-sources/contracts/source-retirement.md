# Source retirement contracts

## MCP catalog
Remove exactly: `get_tiktok_creative_center_trends`, `get_tiktok_search_suggestions`,
`get_threads_trending_topics`, `get_threads_search_suggestions`, `authenticate_tiktok`,
`authenticate_threads`, `authenticate_instagram`, `clear_instagram_auth`,
`get_instagram_auth_status`, `clear_threads_auth`, `get_threads_auth_status`,
`extract_customer_pain_points`.
The runtime catalog and both generated Hermes catalogs contain exactly 41 entries. Removed names
are unknown tools, without handler aliases. All remaining parameter schemas are unchanged.

## Mission creation and collection
A new Attention or Market manifest, or execution of a stored manifest, containing a retired
required OR optional resource returns `status: BLOCKED`, `reason_code: SURFACE_RETIRED`, and
`retired_resources` naming the offending surfaces. No connector, quota reservation, writer or
journal is opened. Domain validation is reusable at host mission preparation and registry
preflight. Historical manifest deserialization is not rejected.

## Watchlist start
Given `[youtube, reels, tiktok_video_grid]`, create the next run for `[youtube]` and include
`retired_resources: [{surface: reels, reason_code: SURFACE_RETIRED},
{surface: tiktok_video_grid, reason_code: SURFACE_RETIRED}]`. Do not change caller authority,
quota, stored versions or previous runs. If no resource remains, return `BLOCKED /
SURFACE_RETIRED`, without a new mission. Empty input still follows existing invalid-input rules.

## Historical reads and kept collectors
Read paths preserve original platforms, channel outcomes, manifest digests and sessions.
URL-based TikTok comments retain validation/redaction/error shapes; no retired session is used.
YouTube and host-browser TikTok/Threads contracts stay unchanged. Historical period channels and
sample flags remain, including Reels; their existence is not current connector availability.

## URL-based comments
`get_tiktok_video_comments` keeps its existing name, parameters and shared TikTok comment code.
Keyword-based pain-point extraction and its exclusive helper are absent, including blocked aliases.
