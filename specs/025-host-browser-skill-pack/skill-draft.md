# Draft: `ignis-browser-collect` skill (Story 1, TikTok and Threads)

Draft for review under Spec 025; it becomes `.agents/skills/ignis-browser-collect/SKILL.md` and a
packaged guide only after the plan. Every step below was run live on 2026-11-11 (`research.md`).

---
name: ignis-browser-collect
description: Run one bounded TikTok or Threads keyword search through the user's own signed-in Chrome
  with Ignis host-browser search. Use when the user asks to look something up on TikTok or Threads
  "through my browser", or a mission's channel needs host-browser collection.
---

## Before you start

- The user asked for this search, for these sources. Use the Chrome profile the user named for
  research (for the owner: the Finos profile); `list_connected_browsers` then `select_browser` by
  deviceId. Never take over a browser the user is working in.
- Never click, type or scroll on a TikTok or Threads page. The only clicks are on the local relay page.
- If `prepare_host_browser_search` fails with `No such file or directory` for an extractor file, the
  running server lost its packaged files (an editable `uv sync`/`uv run` replaced the wheel). Tell the
  user; do not edit the server's environment yourself unless they ask.

## Steps (one source at a time)

1. `prepare_host_browser_search` with `source` (`tiktok` or `threads`), `mode: TACTICAL`, the exact
   queries, `result_limit` (12 is enough for a first look), `lifetime_seconds: 900`, `authorized: true`.
   Keep `request_id`, `relay_url` and `tab_script`.
2. `tabs_context_mcp` (create the group if empty), navigate one tab to `relay_url`.
3. `find` the button "Open search: <query>" on the relay and click it. A new tab opens on the search URL.
4. `tabs_context_mcp` again: tab ids can change or leave the group. Use the new search tab's id.
5. Optional pre-check in the search tab: `document.documentElement.lang`, a non-zero card count, no login
   button. If a sign-in wall or challenge shows, stop: the channel is unavailable.
6. Run `tab_script` verbatim, once, in the search tab.
   - TikTok returns `{posted: true, status, records}`.
   - Threads is asynchronous: the evaluator may return `{}`. Wait two seconds and confirm the tab moved to
     the relay's `/receive` page.
7. Read the relay page: `STAGED — Task listener closed` means the answer is staged.
8. `submit_host_browser_search` with the three ids. Expect `ACCEPTED` and per-query outcomes.
9. Close the tabs you opened.

## Reading the result

- Observations are context from a bounded visible sample, never a market conclusion.
- TikTok: `published_at` is null and counters are unknown. Threads: publication time and rounded or
  exact counters per post.
- `DEGRADED` means the extractor could not prove the page; report the channel unavailable. Do not retry
  in another browser or with an evasion tool.

## Failure table

| Symptom | Check | Remedy |
|---|---|---|
| Prepare fails: extractor file missing | Server's `site-packages/ignis/.../host_browser/` lacks `*.js` | Tell the user the install was replaced; reinstall the built wheel only with their go-ahead |
| "Tab is not in the same group" | `tabs_context_mcp` | Re-read tabs; create the group again if it was removed |
| Evaluator returns `{}` (Threads) | Relay shows `STAGED` or tab is on `/receive` | Treat as posted; never run the script twice |
| `{posted: false, reason: 'This tab was not opened by the relay'}` (TikTok) | `window.opener` | Open the search from the relay button, not by navigating directly |
| Relay never stages | Request expired (`expires_at`) | `cancel_host_browser_search`, then prepare again |
