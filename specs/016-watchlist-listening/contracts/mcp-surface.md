# Contract: MCP Surface for Watchlist Listening

Four new tools; no existing signature changes. Tool count 48 → 52 (OG-1, owner to confirm).

## `save_watchlist(workspace_id, name, definition, watchlist_id=None)`

Creates a watchlist (no `watchlist_id`) or a new version of one. Returns `{watchlist_id, version,
definition_digest}`. Refuses: more than 10 topics or 20 keywords per topic, a discovery share
above 0.2, an unnormalised brand key, a duplicate name in the workspace, an unknown watchlist.
Saving an identical definition returns the current version without creating one.

## `get_watchlist(watchlist_id)`

Returns the watchlist, every version's definition and digest, and its runs (mission id, version,
started_at, mission status). No observation data.

## `start_watchlist_run(watchlist_id, platforms=None, quota_budget=None)`

Creates an Attention mission bound to the current version (research R1), declares its brands
(Spec 015) and returns the mission id. Collection then runs through `execute_mission_ingress` as
for any mission. Refuses an unknown watchlist.

## `get_watchlist_period_snapshot(watchlist_id, period_kind, period_start=None)`

`period_kind` is `day`, `week` or `month`; `period_start` defaults to the latest complete period.
Compares that period with the one before it. Returns:

- `periods`: both periods with bounds in Asia/Ho_Chi_Minh and the watchlist versions active in each;
- `topics[]`: per topic, `channels[]` with `status` (`comparable` or `not_comparable`),
  `indicator` (kind and unit), `current`, `previous`, `change`, `measured_on_sample`,
  `missing_days`, `reasons`; plus `rising_terms`, `new_terms` and up to three `items` (content
  excerpt, identity-free link or "link unavailable", channel, publication date, basis flag);
- `refusal` when the requested period is not complete, with the time it completes.

Never contains author identity, summed cross-channel values, or values for a `not_comparable`
channel.

## Prompt and resource

`ignis_listen` prompt and `fn-ignis://guide/ignis-listen` resource serve the packaged period-view
guide, like `ignis_track`. They start no read, collection or write.
