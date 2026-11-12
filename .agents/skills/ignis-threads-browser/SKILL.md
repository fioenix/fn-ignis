---
name: ignis-threads-browser
description: Run one bounded Threads keyword search through the requester's own signed-in Chrome with Ignis host-browser search. Use when a person asks to look something up on Threads through their browser, or a confirmed mission needs Threads host-browser collection.
---

# Ignis Threads browser search

The procedure lives in two packaged guides so every host reads the same text:

1. The shared relay steps and failure table: MCP resource `fn-ignis://guide/ignis-browser-relay`
   (prompt `ignis_browser_relay`; in this repository
   `src/ignis/interfaces/mcp/guides/ignis_browser_relay.md`).
2. The Threads specifics: MCP resource `fn-ignis://guide/ignis-threads-browser` (prompt `ignis_threads_browser`;
   in this repository `src/ignis/interfaces/mcp/guides/ignis_threads_browser.md`).

Read both before calling `prepare_host_browser_search` with `source: "threads"`. Collection starts only
for a search the person asked for, in the browser profile they named. On the Threads page itself, never
click, type, scroll, sign in or solve a challenge; the only clicks are on the local relay page.
