# Ignis host-browser relay

Shared procedure for collecting one bounded keyword search through the requester's own signed-in
Chrome. The source guides (`ignis_tiktok_browser`, `ignis_threads_browser`, `ignis_instagram_browser`) add what
differs per platform.
Every step below was run live on 2026-11-11.

## Before you start

- The requester asked for this search, on these sources, now. This is never a background or default collector.
- Use the browser and profile the requester named for research. With several browsers connected, select by
  device id; never take over a browser the requester is working in.
- Check the host can open a tab, click in the relay page, evaluate read-only script in a tab it opened, and
  close tabs it opened. If any capability is missing, stop before collection: unsupported transport.
- On a platform page, never click, type, scroll, sign in, consent or solve a challenge. The only clicks are
  on the local relay page.

## Steps

TACTICAL runs one source at a time, steps 1–9 each. A MISSION with several host sources in scope
(TikTok, Threads, Instagram) is one run: prepare a sibling ticket per source with the same mission, `host_task_ref`
and `session_ref`, stage every one of them (steps 2–7 per source), and only then submit once (step 8).
Submitting before every required sibling is `STAGED` returns `BLOCKED` / `HOST_SEARCH_NOT_ACCEPTABLE`.


1. Call `prepare_host_browser_search` with `source`, `mode` (`TACTICAL`, or `MISSION` with a confirmed
   mission id, `queries=[]` and `result_limit=20`), the exact queries, `result_limit`, `lifetime_seconds`
   and `authorized: true`. Keep `request_id`, `relay_url` and `tab_script`.
2. Open `relay_url` in a tab of your own tab group. One relay tab may serve every source and run in a
   session: navigate it to the next `relay_url` only after the current relay shows `STAGED`. The open relay
   page is what receives the answer, so leaving it earlier loses that answer. Each relay accepts only its own
   request.
3. On the relay, find the button "Open search: <query>" and click it. A new tab opens on the approved search
   URL. With several queries, open them a few seconds apart.
4. Re-read your tab list: tab ids change, and a tab the requester touched can leave your group.
5. Wait for results to load. Optionally evaluate this read-only check in the search tab, with the card
   selector from the source guide in place of `CARDS`:

   ```js
   ({lang: document.documentElement.lang, cards: document.querySelectorAll('CARDS').length,
     signIn: !!document.querySelector('input[type="password"]')})
   ```

   `signIn: true` or a challenge means the source is unavailable for this run. With no cards, check once
   more after a few seconds, then run the tab script on what is there; never wait in a loop.
6. Evaluate `tab_script` once, verbatim, in that search tab. Never run it twice.
7. Read the relay page: `STAGED — Task listener closed` means the answer is staged. Close task-created tabs
   only after `STAGED` or after submit, never immediately after `posted: true`.
8. Call `submit_host_browser_search` with `request_id`, `host_task_ref` and `session_ref`. Expect `ACCEPTED`
   with observations and per-query outcomes (TACTICAL) or the canonical mission run and frame (MISSION).
9. Close the tabs you opened.

## Reading the result

- Observations are a bounded visible sample: context, never a market conclusion or representative demand.
- `DEGRADED` means the extractor could not prove the page. Report the source unavailable and move on; no
  retry loop, no other browser, no evasion tool.
- Unknown counters, dates and windows stay unknown. Repeat runs overlap only partly (2026-11-11: TikTok
  Jaccard 0.71, Threads 0.45 for the same query within an hour).

## Failure table

| Symptom | Check | Remedy |
|---|---|---|
| Prepare fails with `No such file or directory` for an extractor file | The server's installed package lacks `host_browser/*.js` | The install was replaced by an editable one; tell the requester. Reinstall the built wheel only with their go-ahead |
| "Tab is not in the same group" | Re-read the tab list | Create the tab group again and reopen the relay |
| Evaluator returns `{}` | Relay shows `STAGED`, or the tab moved to the relay `/receive` page | The script is asynchronous; treat it as posted and do not run it again |
| `{posted: false, reason: 'This tab was not opened by the relay'}` | The tab has no `window.opener` | Open the search from the relay button, never by navigating directly |
| `{posted: false, reason: 'Unapproved search page'}` (Threads) or `'This tab is not an approved search page'` (TikTok) | The tab URL differs from the approved search URL | Reopen from the relay; do not edit the URL |
| Relay never stages | `expires_at` passed | `cancel_host_browser_search`, then prepare a new request |
| A rejected payload | Relay closed | Prepare a new request before staging again |
| Wrong account or profile | The page shows another signed-in account | Stop and ask the requester which profile to use |
| Threads returns `DEGRADED` with "page locale is unsupported" | The search tab's `<html lang>` is missing or malformed | The source is unavailable for this run; report it and move on. A valid language without seeded labels still passes, with counters unknown |
