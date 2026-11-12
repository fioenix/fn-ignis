---
name: ignis-tiktok-browser
description: Run one bounded TikTok keyword search through the requester's own signed-in Chrome with Ignis host-browser search. Use when a person asks to look something up on TikTok through their browser, or a confirmed mission needs TikTok host-browser collection.
---

# Ignis TikTok browser search

The procedure lives in two packaged guides so every host reads the same text:

1. The shared relay steps and failure table: MCP resource `fn-ignis://guide/ignis-browser-relay`
   (prompt `ignis_browser_relay`; in this repository
   `src/ignis/interfaces/mcp/guides/ignis_browser_relay.md`).
2. The TikTok specifics: MCP resource `fn-ignis://guide/ignis-tiktok-browser` (prompt `ignis_tiktok_browser`;
   in this repository `src/ignis/interfaces/mcp/guides/ignis_tiktok_browser.md`).

Read both before calling `prepare_host_browser_search` with `source: "tiktok"`. Collection starts only
for a search the person asked for, in the browser profile they named. On the TikTok page itself, never
click, type, scroll, sign in or solve a challenge; the only clicks are on the local relay page.
