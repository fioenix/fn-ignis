# Ignis Threads browser search

Use with the `ignis_browser_relay` guide, which holds the shared steps and failure table.

- `source: "threads"`. The search opens `https://www.threads.com/search?q=<query>` (the Top sample).
- Transport: the tab script encrypts the answer and, 100 ms later, navigates the same tab to the relay's
  `/receive` page. The script is asynchronous, so the evaluator can return `{}`. Wait about two seconds and
  confirm the relay shows `STAGED` or the tab is on `/receive`. Never run the script a second time.
- Extractor `threads-search-top-v2` keeps the post text without the author header. Each observation has a
  canonical `https://www.threads.com/t/<id>` link, a publication time, and likes, replies, reposts and shares
  as exact, rounded (`1.4K`) or unknown values.
- Counters are read from the action buttons' labels for the page language (`en` and `vi` are seeded). On
  another language, counters stay unknown while records still pass.
- Only fully rendered cards are kept, so the count varies between runs (9 and 7 for the same query on
  2026-11-11).
