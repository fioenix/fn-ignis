# Data Model: Goal-Driven Listening Period

## Watchlist listening plan (new, append-only)

| Field | Type | Rule |
|---|---|---|
| `watchlist_id` | UUID | References `watchlists(id)`, cascade on delete. |
| `effective_from` | timestamp with time zone | Set by the repository at save; primary key with `watchlist_id`. |
| `goal` | text | One sentence, trimmed, 1 to 300 characters. |
| `period_kind` | text | `day`, `week` or `month`. |
| `snapshots_per_period` | integer | At least 1; at most the days the period kind always has (day 1, week 7, month 28), so no cadence is faster than daily. A daily cadence on a monthly plan records 28, the count every month can hold. |

- Rows are never updated; a change inserts a new row (database trigger refuses updates, as for
  `watchlist_versions`).
- Plan in effect for a period: the latest row with `effective_from` at or before the period's
  start in Asia/Ho_Chi_Minh; none means no plan (spec FR-010).
- Saving a plan identical to the one in effect inserts nothing.
- Owner-only like the other watchlist tables: row-level security on, no grant to client roles.

## Snapshot (derived, not stored)

One completing probe outcome of one channel in one watchlist run (research R2): `run`, `channel`,
`completed_at` (snapshot time), `queried_keywords`, `judged`, and the run's signals on that channel.

## Seen-axis cell (derived, in the snapshot response)

Per topic, channel and the two periods: `snapshots` (held), `snapshots_called_for` (from the plan),
`status` (`comparable` or `not_comparable` with reasons), and per period averages per snapshot of
`relevant_shown`, `views_visible`, `interactions_visible`, `first_seen`, `created_in_period`, plus
`rising_terms` and `new_terms`. Every figure carries `axis: "seen"`.

## Created view (unchanged)

The existing per-channel cells of Spec 016, with `axis: "created"` added to each cell. No other
field changes (spec SC-004).
