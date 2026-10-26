# MCP Surface: Goal-Driven Listening Period

Tool count 52 → 53. Owner gate OG-1 (AGENTS.md section 8) covers every signature change below.

## New: `set_watchlist_listening_plan` (Part A)

```text
set_watchlist_listening_plan(watchlist_id: str, goal: str, period_kind: str,
                             snapshots_per_period: int) -> str
```

- Records a new plan in effect from now. Ignis does not infer or default any argument.
- `status`: `SAVED` (new row), `UNCHANGED` (same as the plan in effect), `INVALID` with
  `reason_code` `INVALID_LISTENING_PLAN` (empty or long goal, unknown period kind, cadence outside
  1..days of the period kind), or `NOT_FOUND`.
- Returns the plan in effect and the full plan history. Collects nothing, starts nothing,
  schedules nothing.
- Routed to the caller store by the existing middleware rule (name contains `watchlist`).

## Changed: `get_watchlist` (Part A, additive)

Response gains `listening_plans`: every plan row, oldest first, and `listening_plan` (the one in
effect, or null). Existing fields unchanged.

## Changed: `get_watchlist_period_snapshot` (Part B)

```text
get_watchlist_period_snapshot(watchlist_id: str, period_kind: Optional[str] = None,
                              period_start: Optional[str] = None) -> str
```

- `period_kind` omitted: the plan in effect decides it; with no plan the call returns `status`
  `INVALID`, `reason_code` `PERIOD_KIND_REQUIRED`.
- Each topic gains `seen`: one cell per channel as in [data-model.md](../data-model.md), each
  figure with `axis: "seen"`.
- Each existing channel cell gains `axis: "created"`; nothing else in it changes.
- The response gains `listening_plan`: the plan in effect for each of the two periods.

## Unchanged

`save_watchlist`, `start_watchlist_run` and every other tool.

## Guides

- `ignis_routine`: reads the plan with `get_watchlist`; asks the user for goal, period and cadence
  when none is recorded and saves them with `set_watchlist_listening_plan` after the user states
  them; schedules N distinct days per period; shows requests per period; still refuses faster than
  daily.
- `ignis_listen`: renders the seen axis first and the created view second, each with its label;
  never sums across channels or axes.
