# Ignis User Guide — v0.8.0

This guide describes v0.8.0, including Spec 011 and watchlists. The v0.7.0 Dual-Track
worker and its diagrams are historical and do not describe this branch. See [README](../README.md) for the product contract and release boundary.

## 1. Start and inspect

Use Python 3.11 or newer. From a source checkout, run `./scripts/bootstrap.sh`. It provisions
local SQLite and an MCP client configuration, then runs synthetic diagnostics. Inspect the
diagnostic result for each connector; a configured client or synthetic check is not proof of
live social access. Supply credentials or browser sessions only for the exact source and
research task you authorize. Never place a secret in a prompt, command transcript, or report.

The source migration chain ends at `sql/037_threads_action_labels.sql`. Migration 037 seeds the Threads action-button labels for each UI language that host-browser search uses to read counters; it rewrites no stored evidence. Migration 036 seeds the Threads author attribution wording that host-browser search removes from excerpts; it rewrites no stored evidence. Migration 035 adds append-only watchlist goals, comparison periods and snapshot cadences; it rewrites no stored evidence. Migration 034 seeds the TikTok
author attribution wording that host-browser search removes from excerpts; it rewrites no stored
evidence. Migration 033 adds a
per-channel, per-day count of keyword searches for the daily request ceilings; it rewrites no
stored evidence. Migration 032 adds watchlists, their
immutable versions and the runs bound to them; it rewrites no stored evidence. Migration 031 adds
per-mission author keys, declared accounts and author columns on mission evidence, and lets an
observation with no content reference be stored as unverifiable; it rewrites no stored evidence.
Migration 030 adds
private current-input gaps, explicit finite budget/unit grants, narrowed source authority, original
command receipts and conservative resource allocations. SQLite admission requires an independently
configured current capability provider and fails closed when it is absent; real host providers and
child execution remain unverified. Migration 029 adds immutable parent/child follow-up links and
conservative reservation storage. Neither migration backfills evidence or adopts old authority. Migration 028 (`sql/028_research_work.sql`) adds bounded host research-work storage
and progress-event kinds without transforming persisted evidence. Migration 027 adds only
PostgreSQL revision, progress-event, and command-receipt tables, preserving canonical evidence.
SQLite and PostgreSQL commit collection, qualification and claim facts together with matching
progress events. Relay provides bounded snapshots of installed mission storage; Ignis serves no tracking page.
Migration 026
changes only the count CHECK and retains partial DEGRADED observations without treating them
as complete measurements or measured absence. Fresh local
SQLite initialization has been exercised. Disposable PostgreSQL rehearsal does not verify an
operator's existing database. For an existing database, run
`python scripts/inventory_legacy_baseline.py --dsn sqlite:///ignis.db` or pass an explicit
existing PostgreSQL DSN to
inspect legacy baseline content read-only. Do not delete or migrate it merely because the
new workflow does not use it. Review and approve any data transformation before applying the
pending numbered migrations in order. Earlier files include `sql/022_builtin_uuid_defaults.sql`,
`sql/023_evidence_qualification.sql`, `sql/024_youtube_quota_ledger.sql`, and
`sql/025_evidence_grounded_claim_ledger.sql`.
Do not replay historical 025 after partial DEGRADED rows exist: its strict count CHECK would
reject them before 026 runs. Replay of 026 itself is a separate verified contract.

## 2. Choose the task

For a single source question, ask the agent for an atomic probe and specify a query, geography,
time window, and stop condition. The response should identify the source, request, collection
time, observed count, and channel state. It need not open a Market mission or produce a verdict.

Representative registered atomic calls are listed below (exact signatures are in the running
server's tool descriptions). They are registered options, not verified live availability. Invoke
one only for the bounded task the user explicitly requested, and only with the owner, source,
browser or session authority that task needs, obtained before use. A stored credential, browser
session or authentication status does not by itself grant that permission.

- `get_tiktok_video_comments(video_url, limit=30)` reads public comments under one TikTok video in
  a headless browser, using a stored TikTok session if one exists. It returns `status`,
  `video_url`, `total_comments` and the comments. A URL without a `/video/<id>` segment or a
  missing Playwright install returns `SUCCESS` with zero comments. A blocked or unparsed page can
  also yield zero parsed comments, or fail with `ERROR`, depending on where it breaks. Zero is
  therefore not proof that the video has no discussion.
- `get_tiktok_search_suggestions(keywords, geo="VN")` returns autocomplete expansions.
  `get_tiktok_creative_center_trends(geo="VN", period=7, limit=20, industry=None)` returns macro
  trends (`limit` capped at 50). These expand topics; they do not measure demand.
  The retained `get_threads_search_suggestions(keyword, geo="VN", limit=10)` and
  `get_threads_trending_topics(geo="VN", limit=15)` signatures return
  `UNAVAILABLE/HOST_BROWSER_REQUIRED`, without browser, cookie or OAuth fallback.
- `execute_mission_ingress(mission_id)` is the separate option for a confirmed mission: it runs only
  that mission's recorded plan and records a channel outcome for each requested source.

None of these calls forces a collection-then-analysis workflow or schedules further collection,
and they need not be chained. Each still has its own preconditions: actual source access, the
source and mission scope, and resource limits. `execute_mission_ingress` additionally requires a
confirmed mission and its recorded plan (for a Market mission, a confirmed Market Brief). `verify_connectors_health` runs synthetic diagnostics and authentication tools can run
an access probe, so do not call either merely to check whether a source is available.

For a market decision, state the decision you face, target audience, geography, time window,
hypothesis, plausible alternative, and what observation would change your mind. The agent
creates an Attention mission or confirms a Market Brief with you before collecting. Once the
scope is confirmed, `execute_mission_ingress` runs only that mission's plan. There is no daily
worker or unattended collection.

The [collection skill](../.agents/skills/ignis-collect/SKILL.md) is the method for gathering
an inspectable frame. The [analysis skill](../.agents/skills/ignis-analyze/SKILL.md) is a
separate method for testing the Market hypothesis. Ask for either or both.

### Follow a watchlist

To follow the same subject across runs, ask the agent to save a watchlist in a confirmed research
workspace: up to 10 topics, each with categories, up to 20 keywords and the brand accounts you
name. `save_watchlist` stores every change as a new immutable version, and `get_watchlist` lists
the versions and the runs. Each `start_watchlist_run` creates one Attention mission on the current
version and declares its brands as that mission's accounts, the only accounts Ignis ever names.
You state the allowed sources and authority for every run; collection then goes through
`execute_mission_ingress` as for any mission. Ignis never runs a watchlist on its own.

`set_watchlist_listening_plan` records the user's goal, comparison period (`day`, `week`,
`month`) and snapshots per period as append-only history. An identical save is unchanged.
`get_watchlist` returns the plan in effect and its history. Omit `period_kind` to use that plan's
period; without a plan, pass a period explicitly. Routine setup reads the plan, asks for missing
choices, shows firings and requests per period, and waits for confirmation before host scheduling.
Ignis starts no collection or schedule when a plan is saved.

To see how a watchlist moved, ask for its period view. `get_watchlist_period_snapshot` compares a
complete day, Monday-to-Sunday week or calendar month in Asia/Ho_Chi_Minh with the one before,
and refuses an unfinished period. Its optional `period_kind` defaults to the saved plan's period;
without a plan, pass it explicitly. The `ignis_listen` prompt and
`fn-ignis://guide/ignis-listen` resource render a local file with two separate axes:

- `seen` comes first: what successful snapshots showed, placed at each channel's collection
  completion time. Relevant items, visible views, interactions, first sightings and items created
  in the period are averages per snapshot held. An old post counts each time it appears.
  Each period uses the plan in effect at its start. More than 20% missing snapshots, no cadence
  for that period kind, or unjudged snapshot evidence makes the cell "not comparable": show
  reasons and snapshot counts, never indicators or change.
- `created` comes second: items placed by publication date, or by collection date with an explicit
  label when no plausible publication date exists. It retains Spec 016's daily coverage rules and
  seven-day counting window. More than 20% missing days in either period, or an unjudged day,
  makes the channel "not comparable", showing missing or unjudged dates instead of numbers.
  Only observations qualified as relevant count.

Each channel keeps its own units and sample labels. Comparability is independent between axes;
never sum across channels or axes. Unknown values are not zero. Google Trends RSS supplies macro
feed topics and feed-reported traffic; keyword Trends measurement remains unavailable and
reports `DEGRADED`, not a demand score.

Each channel has a daily request ceiling: one request is one keyword searched on that channel, and
the count is shared by every session on the same store for the calendar day in Asia/Ho_Chi_Minh.
The defaults are 200 for YouTube and 50 for every other channel; raise one with
`update_runtime_config` on `connector.<platform>.daily_request_ceiling`. A search that would pass
the ceiling sends nothing to that channel and records it as `RATE_LIMITED` with a `daily_ceiling`
note, while the other channels run. A pass counts every keyword it searches (Reels reads at most
10), so a watchlist with more keywords than a channel's ceiling skips that channel until
you raise it. History is finite but never pruned on its own:
`scripts/prune_expired_observations.py` lists observations collected more than 13 months ago, and
removes them with `--apply`, keeping any that a stored claim or recorded research work still cites.

To have a watchlist run every day, ask your agent for it, for example "run my matcha watchlist
every morning at 7". The `ignis_routine` prompt and `fn-ignis://guide/ignis-routine` resource tell
it how to set up one Claude Code Desktop scheduled task: at most one per watchlist, at most once a
day, and only after you confirm what will run. Each firing is one watchlist run and nothing else.
Create it from a session opened in the research workspace's repository folder, because a firing
starts in that folder. Before creating it, the agent checks that each channel can collect for your
workspace: YouTube needs its key in the workspace's own `.fnignis/.env`, and browser channels need a
saved sign-in. A routine never runs in a Bypass permission mode, and runs in Auto only if you accept
that during setup. Each firing also judges which collected items are on your topics, because the
period view counts only judged items. Setup ends with a first run you watch; in a mode that asks,
you approve only `start_watchlist_run`, `execute_mission_ingress`,
`get_mission_evidence_qualification_batch` and `submit_mission_evidence_qualifications`.
You pause or remove it in the app, and removing it keeps the watchlist's history. A firing happens
Ignis itself schedules nothing.

## 3. Understand evidence and analysis

Ignis records a channel outcome for every requested source. `HEALTHY`, `EMPTY_NO_DATA`,
`AUTH_REQUIRED`, `RATE_LIMITED`, `DEGRADED`, `FAILED`, and `NOT_REQUESTED` are not
interchangeable: an inaccessible or failed channel is a coverage gap, and a surface outside the
requested plan was not measured; neither is proof that the market is empty. The agent reviews an evidence
qualification batch, records typed support, contradiction, or context judgments, and checks
that the current frame is terminal before making Market claims.

Threads collection requires a separately authorized host browser. Stored Graph credentials are
compatibility state, not proof of public keyword access. `authenticate_threads`,
`get_threads_auth_status` and `clear_threads_auth` retain their public signatures; they do not
activate collection or probe an API grant. Use explicit host preparation or report the gap.

Google Trends RSS supplies current macro topics and feed-reported traffic, not a keyword
time series. Keyword Trends measurement is currently unavailable and reports `DEGRADED`
rather than a fabricated demand score. The existing connector suggestions interface exposes
Google Autocomplete as `google_autocomplete` keyword expansion only: suggestion counts are
not search volume, demand, or growth. A valid empty suggestion response differs from an
unavailable probe; neither establishes zero market demand. Existing historical observations
are not rewritten by this connector correction.

Each strategic statement belongs in the persisted Claim Ledger. `submit_mission_claims`
binds it to observations or eligible measured absence, and `get_mission_claims` shows whether
it may be rendered. `get_mission_analysis` must return only permitted current-frame claims.
If coverage, qualification, or claims are insufficient, it returns a Gap Report with safe
partial observations and the smallest useful next probe. A numeric score or raw signal is
not a substitute for that gate.

Uploaded files and purchased datasets can help phrase a question or identify a competitor.
Without mission-scoped provenance and qualification, they remain context rather than primary
Market evidence. The analysis should show disconfirming evidence and state when its conclusion
would change. Export HTML with `generate_mission_artifact` only when a saved report is wanted.
Like every mission tool, it is admitted only through one validated caller root, and the report is
written to `<root>/.fnignis/reports/`. The server keeps a fallback for calls made without a caller
root: gitignored `reports/` in a source checkout, `~/.ignis/reports/` for an installed package, or a
temporary directory if needed; admitted MCP calls do not use it. Templates live in
`src/ignis/infrastructure/templates/html/`.

### Author identity

Ignis studies a market in aggregate and keeps no author identity at rest. Before a sighting is
stored, it removes the author fields connectors report (usernames, user and channel ids, display
names, profile links, avatars), replaces a link that names an account with a handle-free link to
the content (`tiktok.com/share/video/<id>`, `threads.com/t/<shortcode>`) or drops it when none
exists, and turns `@mentions` in titles, captions and comments into `@[user]`. It keeps a
per-mission author marker instead: a keyed hash that tells many voices from one voice within one
mission and links nothing across missions. `get_mission_analysis` reports `author_concentration`
per channel; without a persistent `IGNIS_ENCRYPTION_KEY` Ignis cannot count authors and the
analysis says so. Content with no content reference is kept as context only and never supports a
claim.

Ignis keeps identity only for accounts a requester declares for one mission with
`set_mission_declared_accounts`, such as the brand's own account or a named competitor, as
`{platform, account, declared_name}`. Each call replaces the mission's set; an empty list
withdraws every declaration. Content from a declared account collected after `declared_at` is
attributed by the declared name, and mentions of it render as `@<declared name>`. Earlier
observations are never re-attributed; after a withdrawal the name disappears from reports without
rewriting evidence.

Ignis does not remove personal names written in free text, such as a commenter signing a post.
Rows stored before Spec 015 keep their identity at rest until the owner decides what to do with
them; every report and tool response strips it on output, and
`scripts/inventory_author_identity.py` counts it without showing any value.

### Mission Relay

Ignis serves no tracking page. To follow a mission, ask your agent to read
`get_mission_relay_snapshot` and build a tracking artifact with the `ignis-track` guide: the MCP
prompt `ignis_track`, the resource `fn-ignis://guide/ignis-track`, or the repository skill
[`ignis-track`](../.agents/skills/ignis-track/SKILL.md). The agent regenerates the artifact only
when you ask or at a milestone inside its own turn, and never polls. Each artifact is a
point-in-time snapshot that keeps withheld, stale and unavailable states visible. It is saved as a
local file; publishing it anywhere else needs your consent for that publication. Reading never
starts, pauses or cancels collection, and server shutdown leaves retained evidence in place.

Source policy appears against each original source/observation identity. Registered official
YouTube API metadata with exact ingestion time shows its original capture and 30-calendar-day
boundary; ambiguous historical access, missing capture time or future timestamps remain UNKNOWN.
Publication dates, artifact clocks and restart never replace capture time. A boundary warning
requires a source-specific owner decision; it grants no indefinite compliance, OAuth exception,
collection authority or Market support. Snapshot reads perform no deletion or quota calls.
See [YouTube developer policies](https://developers.google.com/youtube/terms/developer-policies).

Use `get_mission_relay_snapshot` for a bounded snapshot of the selected mission and optional run.
It validates installed storage without bootstrapping a database or starting collectors. Like
every mission tool, it is admitted only through one caller root: the folder your agent was opened
in, which is the MCP server's working directory at startup. Set `IGNIS_CALLER_ROOT` (an absolute
directory, unchanged since startup) only when your host starts the server somewhere else. Client
roots are not consulted. A startup folder that cannot be one project is refused: the filesystem
root, your home directory or a parent of it, a world-writable or sticky directory, or one owned by
another user. A folder replaced since startup is refused too. Each refusal fails with
`ROOT_REQUIRED`. For an admitted call, canonical mission storage defaults
to caller-local SQLite at `<root>/.fnignis/canonical.sqlite3`; an explicit `DATABASE_URL` in
`<root>/.fnignis/.env` can select another SQLite file inside the root or a PostgreSQL database.
Caller configuration, logs, reports and research files stay under `<root>/.fnignis/`.
That file must be a regular file with no group or other permissions (Ignis creates it as 0600),
at most 32 KiB, holding only literal values (no `${...}` interpolation) for the keys listed in the
generated `<root>/.fnignis/.env.example`. A file, key, value or syntax violation fails with
`CALLER_CONFIG_REFUSED`; a SQLite path that is relative or outside the root fails with
`ROOT_SCOPE_REQUIRED`. The server's own `.env` and the `DATABASE_URL` written by bootstrap do not
select caller mission storage, and settings never authorize a source probe.
`record_mission_research_work` records an explicit bounded host command through the local stdio
session, enforcing mission authority and exact revision, epoch and input bindings. Recording
does not execute agents, invoke providers or collect sources.

`execute_mission_follow_up(mission_id, follow_up_work_id, expected_research_epoch, idempotency_key)`
executes one recorded gap-linked work item through the owning local stdio session. Its current
assignment, exact input frame, remaining budget and independent source/session capability must
admit execution before child creation or collection. No queries, credentials or provider flags
are accepted. A missing capability provider refuses before auth/collection. Admitted responses
identify the actual parent/work/gap/assignment/child/reservation/run and channel outcomes; retries
recover the same child, while uncertain execution retains its reservation and cannot reprobe.
Caller cancellation stops the owned execution and waits for cleanup. The parent lifecycle stays
unchanged, and reading a snapshot confers no execution authority.

## 4. Tool and deployment boundaries

The local MCP server exposes **53 tools**. Discover the running server's descriptions for exact
signatures; removed daily-discovery and unguided-research tools are not part of this branch.
The release workflow builds `ghcr.io/fioenix/fn-ignis:0.8.0` when the `v0.8.0` tag is pushed.
The v0.7.0 image does not contain the workflow described here.
PyPI publication is not advertised. Run the branch's
`.venv/bin/pytest tests/` (the CI scope; PostgreSQL cases skip unless `IGNIS_TEST_POSTGRES_DSN`
names a disposable test database) and `uv lock --check` for local checks. The test suite
replaces credentials with inert values; to also keep the checkout's `.env` out of a run, use the
[isolated-settings pattern](../specs/014-evidence-factory/quickstart.md#isolated-settings). Consult
[the Spec 011 task ledger](../specs/011-evidence-grounded-product-reset/tasks.md) for its outstanding
PostgreSQL, pilot, integration, and owner-controlled release gates, and
[the Spec 014 task ledger](../specs/014-evidence-factory/tasks.md) for the Mission Relay,
research-work and follow-up gates that remain open.

### Explicit host-browser TikTok search (development branch)

`prepare_host_browser_search`, `submit_host_browser_search` and `cancel_host_browser_search` provide
an opt-in, task-bound host path. It needs an explicitly authorized browser and supported host DOM
evaluation; Python does not drive the host or export its cookies. Prepare a finite batch and open
the returned localhost relay. Its "Open search" buttons open the exact public search URLs; the
`tab_script` that preparation returns, run in each opened tab, posts the answer back and returns only counts, and the
relay stages the batch once every query has an answer. Filling the relay's form from retained JSON
still works. MCP submit consumes the staged answer by IDs only. Excerpts lose the selected source's author
attribution sentence before any receipt or storage; preparation is refused with
`AUTHOR_ATTRIBUTION_VOCABULARY_MISSING` when no attribution wording is seeded.

TACTICAL returns observations without database initialization. MISSION requires a confirmed mission
ID, mode=MISSION, queries=[] and result_limit=20; it derives the complete query/falsifier union,
rechecks scope under the normal writer and returns the canonical run/frame. Quota/authority limits
and qualification still apply. Failed ingestion requires journal/frame readback, not replay.

Requests expire within an hour; form payloads are capped at 1 MiB. The localhost listener accepts
only its exact Host/Origin and closes on terminal transport states. Unknown publication, counters
and window filters stay unknown. This is bounded public video-grid collection, not comments, a
representative market sample, or an automatic fallback. Host cleanup preserves owner tabs.

### Threads host collection and period paths

`prepare_host_browser_search` accepts optional `source="threads"`; omitting it keeps
`source="tiktok"`. Submit and cancel keep their three ID parameters. There are still 53 tools.
Threads collection uses only the authorized host browser. Internal Threads Playwright collection
is removed; the retained suggestions/trending tools return `UNAVAILABLE/HOST_BROWSER_REQUIRED`.
Stored Threads credentials do not establish collection readiness. No API grant probe or API path
is activated, and failure never selects a fallback collector.

Reels stays on Playwright without automation-hiding flags. A login wall, checkpoint, challenge,
unparseable response or missing search envelope is unavailable with a reason, never a measured
zero. A verified, well-formed empty search envelope may return `EMPTY_NO_DATA` for the executed
keyword. This does not establish coverage for other keywords or a known time window.

Threads `threads-search-top-v2` collects a bounded visible Top sample on `www.threads.com/search`.
Posts are found by page structure in any UI language; counters are read only for UI languages
with seeded action labels (English and Vietnamese) and stay unknown otherwise. Loading, an
empty shell or all records being dropped cannot prove an empty market. Capture time and publication time stay separate.
Counters retain raw display and precision: `1.4K` or `1,4K` is rounded, a blank is unknown, and shares are
not quotes. Rounded counters do not become exact period totals. Author headers and attribution
are removed before receipts or storage; links use identity-free content references. Free-text
personal names remain a sanitization limitation.

On both seen and created axes, `collection_path_changed` refuses different proven paths,
`collection_path_unknown` refuses a proven path against an unknown path, and
`collection_path_mixed` refuses multiple proven paths or proven/unknown mixtures within either
period. These cells have no indicators or deltas. Identical proven paths remain eligible;
if both periods have only unknown paths, legacy comparison rules and output stay unchanged.
Cadence, coverage, publication placement and judgment rules still apply.
