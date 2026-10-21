# Data Model: Watchlist Listening and Period Comparison

Additive to the schema after Spec 015 (latest migration `031`); delivered as
`sql/032_watchlists.sql` with SQLite parity in `_ensure_schema`. All three tables are owner-only,
with caller-bound identities like 028–031.

## New: `watchlists`

| Field | Type | Rule |
|---|---|---|
| `id` | UUID PK | |
| `workspace_id` | FK → research_workspaces | A watchlist belongs to one workspace. |
| `name` | text | Non-blank; unique per workspace. |
| `current_version` | integer ≥ 1 | Number of the latest version. |
| `created_at` | timestamp | |

## New: `watchlist_versions`

| Field | Type | Rule |
|---|---|---|
| `watchlist_id` | FK → watchlists, part of PK | |
| `version` | integer ≥ 1, part of PK | Increments by one per revision. |
| `definition` | JSON text | Topics (≤ 10), each with `name`, `categories`, `keywords` (≤ 20), `brands` (platform, account key, declared name), `discovery_share` (0–0.2). Validated in the domain; JSON object enforced by a CHECK. |
| `definition_digest` | 64 hex | SHA-256 of the canonical definition; unique per watchlist. |
| `created_at` | timestamp | |

Immutable: no update or delete (trigger on PostgreSQL, trigger on SQLite).

## New: `watchlist_runs`

| Field | Type | Rule |
|---|---|---|
| `mission_id` | PK, FK → research_missions ON DELETE CASCADE | One mission belongs to at most one watchlist version. |
| `watchlist_id` | composite FK with `version` → watchlist_versions | |
| `version` | integer | |
| `started_at` | timestamp | |

## Derived values (no table)

- **Period**: kind (`day`, `week`, `month`), start date in Asia/Ho_Chi_Minh, complete flag.
- **Placement**: observation → period start, basis (`published` or `collection_date`).
- **Channel-day coverage**: (topic, channel, day) → complete or missing, from
  `mission_probe_outcomes` of the watchlist's runs (research R3).
- **Comparison cell**: (topic, channel) → `comparable` with both indicators and change, or
  `not_comparable` with reasons and missing days.
- **Counted value**: per item, the latest observation collected within 7 days of publication.

## Runtime configuration (seeded in `sql/032_watchlists.sql`)

- `connector.<platform>.daily_request_ceiling` for youtube, google, tiktok, threads, reels.
- `listening.terms.rising_min_count` (2) and `listening.terms.rising_min_growth` (0.5).
- `listening.counter_observation_days` (7).
