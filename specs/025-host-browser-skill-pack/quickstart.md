# Quickstart: acceptance runs for Spec 025

Prerequisites: the server runs a wheel that contains this feature; Claude in Chrome is connected to the
research profile (Finos for the owner) and that profile is signed in to TikTok, Threads and Instagram.

1. In a fresh agent session, give only: "Find what people say about `áo khoác chống nắng` on TikTok,
   Threads and Instagram through my browser." The agent loads the per-source skills.
2. For each source, expect: `prepare_host_browser_search` → relay page → "Open search" → tab script once →
   relay shows `STAGED` → `submit_host_browser_search` returns `ACCEPTED`.
3. Record per source: wall time from prepare to accepted (SC-003), accepted count, steps outside the skill
   (SC-001 expects zero).
4. Instagram: confirm at least 10 accepted observations and no handle, profile link or author attribution
   in any excerpt (SC-002).
5. TikTok after FR-007: pick three accepted videos, open each page, compare the rendered date with
   `published_at`; record the comparison in `research.md`.
6. Confirm a request for the retired `reels` surface still returns `SURFACE_RETIRED`.
