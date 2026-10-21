# Contract: MCP Surface for Watchlist Listening

Four new tools; no existing signature changes. Tool count 48 → 51 in Part A, 52 in Part B (OG-1, owner to
confirm). Refusals carry `status` and a stable `reason_code`.

## `save_watchlist(workspace_id, name, definition, watchlist_id=None)`

Creates a watchlist (no `watchlist_id`) or a new version of one. Returns `{watchlist_id, version,
definition_digest}`. Refuses: more than 10 topics or 20 keywords per topic, a discovery share
above 0.2, more than 20 categories per topic, a name, category or keyword over 200 characters or
with a control character, a brand a run could not declare (Spec 015 bounds: at most 50 accounts,
an account of at most 100 characters without spaces, a declared name of at most 120), a brand on a
platform without accounts, a duplicate name in the workspace, an unknown
watchlist. Brand accounts are normalised as in Spec 015 (lower case, no leading `@`).
Saving an identical definition returns the current version without creating one. `status` is
`CREATED`, `VERSION_ADDED` or `UNCHANGED`. A revision keeps the watchlist's workspace and name;
renaming is refused with `NAME_MISMATCH`.

## `get_watchlist(watchlist_id)`

Returns the watchlist, every version's definition and digest, and its runs (mission id, version,
started_at, mission status). No observation data.

## `start_watchlist_run(watchlist_id, allowed_resources, authority_boundary, quota_budget=None, geo="VN", timeframe="7d", agent="claude", session_id=None)`

Creates an Attention mission bound to the current version (research R1) and returns its id. Its
keywords are every topic's keywords, then every brand's declared name, each once; its brands
become the mission's declared accounts (Spec 015). The caller states `allowed_resources` and
`authority_boundary` on every run, exactly as for `create_attention_mission`, so a run never
inherits authority from an earlier one; the outcome, output type (`COLLECTION_FRAME`), stop
condition and retention policy follow from the watchlist. Collection then runs through
`execute_mission_ingress` as for any mission. Refuses an unknown watchlist and an invalid manifest.
The response reports `declared_accounts_status`; a refused declaration leaves every author
anonymous. A mission that could not be bound to the watchlist returns `FAILED`/`RUN_NOT_BOUND` with its
id and must not be run.
The discovery share is stored with the version but not yet spent by collection (Part A).

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
