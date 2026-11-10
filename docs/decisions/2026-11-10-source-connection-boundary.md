# Decision: Ignis Builds a Source Connection Only When No Official MCP Exists

**Status:** Accepted by the owner on 2026-11-10
**Date:** 2026-11-10
**Scope:** Which data sources Ignis connects to itself, and which it leaves to a connection the host already has

## Context

Ignis has accumulated connectors that no longer return evidence. Stored data on 2026-11-10 holds
364 YouTube, 227 Threads, 32 TikTok, 11 Reels and 0 Google Trends observations. Probes on the same
day found the TikTok Creative Center tool returning no hashtags, TikTok search suggestions returning
general trends unrelated to the keyword, the Threads trending and suggestion tools returning only
`UNAVAILABLE`, and Reels collection returning `REELS_PAGE_UNUSABLE` even with a fresh session.

The owner's direction is that Ignis does not try to build every data source connection; its main job
is to identify which sources answer the question. Asked whether the sources have official MCP
servers or official access for personal accounts, a search on 2026-11-10 found no official MCP server
for YouTube, TikTok, Threads, Instagram or Google Trends. Official access for a personal account to
search public content by keyword exists only for YouTube (Data API v3 with an API key). Threads keyword
search over public posts needs Meta app review, Instagram hashtag search needs a Business or Creator
account, TikTok's Research API is limited to approved non-profit researchers, and the Google Trends API
is in a gated alpha.

## Decision

The owner stated the rule on 2026-11-10: "Cái nào mà có mcp chính hãng thì mới tích hợp sang đó, còn
không là phải built-in vào ignis." (Where a source has an official MCP, integrate with it; otherwise the
connection is built into Ignis.)

- A source with an official MCP server, published by the platform owner, is collected through that
  server by the host agent. Ignis receives and qualifies the evidence; it keeps no connector of its own.
- A source without one keeps a built-in connection in Ignis, through an official API where one is usable
  by the target users, otherwise through the user's own browser as host-browser search.
- A built-in connection that no longer returns evidence is removed rather than kept as a placeholder.
- A community MCP server does not count as official.

## Consequences

- No current source has an official MCP server, so nothing moves out of Ignis now.
- YouTube stays built in through its official API. TikTok and Threads stay built in through host-browser
  search, and TikTok public comments stay built in.
- Google Trends RSS, TikTok Creative Center, TikTok headless keyword search and Reels headless collection
  are removed (Spec 022), together with the twelve tools that only served them, which takes the catalog from 53 to 41 tools.
- When a platform publishes an official MCP server, its built-in connection becomes a candidate for
  removal in a spec of its own.

## Relation to earlier decisions

This amends the description of the Collection capability in the 2026-09-29 decision and in `AGENTS.md`
("integrated connectors and skills pull source observations"): integrated connectors remain where no
official MCP exists. Mission-bound collection, evidence qualification and the frozen Market verdict are
unchanged.
