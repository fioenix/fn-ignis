# fn-ignis

Ignis is a self-hosted, mission-bound social market research harness. It helps people collect
inspectable evidence from accessible social sources, then challenge a market hypothesis before
acting on it. Its two capabilities are independent: source collection can end with an evidence
frame, while Market analysis can end with a Gap Report rather than a forced verdict.

**Release boundary:** v0.10.0 exposes 41 tools, retires unusable source collection and the seeded
taxonomy and market vocabulary, with migrations through `040`. v0.9.0 still lists the removed tools; v0.7.0 is a
historical Dual-Track artifact, not the mission-bound surface here.

## Product contract

Ignis starts only for an explicit source probe or confirmed research mission. It does not run a
worker, daily discovery, or unattended baseline. A mission records the question, scope, sources,
stopping rule, and collection outcomes. Analysis follows Outcome, Design, and Critical thinking:
define the decision, inspect the user's context, seek disconfirming evidence, and report gaps.

Market verdicts require a current qualified evidence frame and persisted Claim Ledger. Every
rendered claim must identify its observations, contrary evidence, limitations, and conditions
that would change it. Missing or unavailable channels are not zero demand. Uploaded or purchased
datasets are context unless they acquire mission-scoped provenance and qualification. See
[Spec 011](specs/011-evidence-grounded-product-reset/spec.md) and its
[public contract](specs/011-evidence-grounded-product-reset/contracts/mission-bound-public-surface.md).

Ignis keeps no author identity at rest. Usernames, account and channel ids, profile links, avatars,
and handles in links or `@mentions` are removed before anything is stored; a per-mission marker
counts distinct voices instead. Only accounts a requester declares for one mission with
`set_mission_declared_accounts` are named. Personal names written in free text are not removed.
See [Spec 015](specs/015-no-author-identity-at-rest/spec.md).

## Local source setup

Requirements: Python 3.11 or newer. Run `./scripts/bootstrap.sh` from a source checkout. It
creates a local virtual environment and SQLite database, seeds filtering, language-detection and interface vocabulary, configures
supported MCP clients, and runs synthetic diagnostics. Connector credentials and real social
sessions are optional and require the operator's own authorization. Never interpret synthetic
readiness as live source access.

For a Codex-only installation with separate UAT storage, run
`./scripts/bootstrap.sh --client codex --env-file /absolute/path/to/uat/.env`.
Other client configurations remain unchanged; omitting these options retains the all-client setup.

The current source tree contains migrations through `sql/041_instagram_attribution.sql`, a seed-only row of
Instagram attribution wording for host-browser search. Migration 040 deletes only `system` rows in the seven retired market vocabulary domains; operator
rows and stored evidence remain unchanged. SQLite applies it at bootstrap; existing PostgreSQL
stores apply only the pending migrations after 039 (040, then 041). `register_domain_lexicon` still stores and lists
market terms, but they no longer affect topic matching or language detection. Filtering,
language-detection and interface vocabulary keep their existing roles.

Migration 039 resets stored labels from the retired industry taxonomy to `unclassified` and drops its table; a store that already holds clusters must run `scripts/retire_industry_taxonomy.py` (`project`, then `apply`) instead of applying this file directly. Do not replay the whole migration directory on a retired store: it would recreate the table. Migration 038 seeds locale-qualified TikTok attribution templates. Since `tiktok-public-grid-v3` keeps only the caption element and the hashtags after it, interface language no longer gates records. It rewrites no stored evidence. Migration 037 seeds the Threads action-button labels for each UI language that host-browser search uses to read counters; it rewrites no stored evidence. Migration 036 seeds the Threads author attribution wording that host-browser search removes from excerpts; it rewrites no stored evidence. Migration 035 adds append-only watchlist goals, comparison periods and snapshot cadences; it rewrites no stored evidence. Migration 034 seeds the TikTok author attribution wording that
host-browser search removes from excerpts; it rewrites no stored evidence. Migration 033 adds a per-channel, per-day count of keyword
searches for the daily request ceilings; it rewrites no stored evidence. Migration 032 adds watchlists, their immutable versions and the runs
bound to them; it rewrites no stored evidence. Migration 031 adds per-mission author keys, declared
accounts and author columns on mission evidence, and lets an observation with no content reference
be stored as unverifiable; it rewrites no stored evidence. Migration 030 adds current-input gaps, finite budget
grants, narrowed source authority, command receipts and conservative resource allocations.
Migration 029 adds immutable parent/child follow-up links and reservation storage. Neither
migration backfills evidence or adopts old authority. Migration 028 (`sql/028_research_work.sql`) adds bounded host research-work storage
and progress-event kinds without transforming persisted evidence. Migration 027 adds only PostgreSQL revision, progress-event,
and command-receipt tables, preserving canonical evidence. SQLite and PostgreSQL now commit collection, qualification and claim facts together with
their matching progress events. Relay provides bounded snapshots of installed mission storage;
Ignis serves no tracking page.
Migration 026
changes only the outcome-count constraint: partial DEGRADED results remain incomplete measurements.
A fresh SQLite bootstrap is exercised locally;
PostgreSQL migration rehearsal on a disposable database does not verify an operator's existing
database. For an existing database, inventory
legacy baseline rows with `python scripts/inventory_legacy_baseline.py --dsn sqlite:///ignis.db`
or an explicit existing PostgreSQL DSN before planning any migration or
archive. Apply only pending numbered migrations in order after reviewing the migration's data impact and
the operator's approval. The previous files include `sql/022_builtin_uuid_defaults.sql`,
`sql/023_evidence_qualification.sql`, `sql/024_youtube_quota_ledger.sql`, and
`sql/025_evidence_grounded_claim_ledger.sql`.
Do not rerun historical 025 after partial DEGRADED rows exist: it reinstalls the stricter count
CHECK before 026 can run. Replay verification for 026 is not whole-history replay verification.

For an existing PostgreSQL database on `035`, apply `036`, `037` and `038` in order as the
table owner. Without `038`, a MISSION TikTok host-browser search is refused before it starts.

The release workflow builds `ghcr.io/fioenix/fn-ignis:0.10.0` when the `v0.10.0` tag is pushed.
The v0.9.0 image still carries the removed tools and the retired sources.
PyPI publication is not advertised. Admitted mission calls write HTML to
`<root>/.fnignis/reports/`; the source-checkout fallback is gitignored `reports/`.
Committed report templates live only in `src/ignis/infrastructure/templates/html/`.

## Agent capabilities

The current MCP server exposes **41 tools**. Use the server's live tool descriptions as the
signature authority. Representative operations:

- `create_attention_mission` and `confirm_market_brief` establish a bounded question and
  confirmed scope; `execute_mission_ingress` collects the requested frame.
- `set_watchlist_listening_plan` records the user's goal, comparison period (`day`, `week`,
  `month`) and snapshots per period as append-only history. An identical save is unchanged.
  `get_watchlist` returns the plan in effect and its history. The optional `period_kind` on
  `get_watchlist_period_snapshot` defaults to the saved plan's period; without a plan, pass it
  explicitly. Routine setup asks for missing choices, shows firings and requests per period,
  and waits for confirmation before host scheduling. Saving a plan starts no collection or schedule.
- `save_watchlist`, `get_watchlist` and `start_watchlist_run` keep a versioned watchlist of
  topics and brands and start one Attention mission per run on its current version. Ignis never
  runs a watchlist on its own. `get_watchlist_period_snapshot` compares a complete day, week or
  month with the one before, per channel and in each channel's own unit; the `ignis_listen` guide
  renders the `seen` axis first (what successful snapshots showed, averaged per snapshot against
  the saved cadence) and the `created` axis second (items placed by publication date).
  Each axis reports comparability separately; never sum across channels or axes.
  Each channel stops at a daily request ceiling you can raise, and
  `scripts/prune_expired_observations.py` previews history older than 13 months and removes it
  only with `--apply`, keeping observations still cited by a stored claim or research work.
  With the `ignis_routine` guide your agent can set up a daily Claude Code Desktop scheduled task
  that runs one watchlist; Ignis itself still schedules nothing.
- The atomic source tool `get_tiktok_video_comments` can answer source-specific questions without a Market verdict.
- Opt-in `prepare_host_browser_search`, `submit_host_browser_search` and
  `cancel_host_browser_search` collect bounded public TikTok grids, Threads Top results and Instagram keyword-grid captions through an
  authorized host browser. See [host-browser scope and limits](docs/USER_GUIDE.md#explicit-host-browser-search-tiktok-threads-instagram).
- `get_mission_evidence_qualification_batch` and
  `submit_mission_evidence_qualifications` record evidence judgments.
- `submit_mission_claims`, `get_mission_claims`, and `get_mission_analysis` control
  current-frame claims and the Gap Report. `generate_mission_artifact` exports an HTML report
  when requested.
- `get_mission_relay_snapshot` reads a bounded selected-mission snapshot. Ignis serves no
  tracking page: the `ignis-track` guide (MCP prompt `ignis_track`, resource
  `fn-ignis://guide/ignis-track`) tells your agent how to build a point-in-time tracking artifact
  from it, saved as a local file unless you agree to publish it.
- `record_mission_research_work` records a bounded host command with mission authority,
  revision, epoch and input checks. Recording does not run agents, invoke providers or collect sources.
- `execute_mission_follow_up` executes one recorded gap-linked work item under its current
  assignment and independently authorized source capability. It preserves child provenance and
  reservations; viewing does not grant execution authority and uncertainty does not trigger reprobes.

Agent instructions are in [AGENTS.md](AGENTS.md). The separate
[collection](.agents/skills/ignis-collect/SKILL.md),
[analysis](.agents/skills/ignis-analyze/SKILL.md) and
[tracking](.agents/skills/ignis-track/SKILL.md) skills define the human-facing methods.
The [user guide](docs/USER_GUIDE.md) covers the current source workflow. Historical v0.7.0
diagrams and the published release remain available through the v0.7.0 Git tag; they are not
diagrams of this branch.

### Threads host collection and period paths

`prepare_host_browser_search` accepts optional `source="threads"` or `source="instagram"`; omitting it
keeps `source="tiktok"`. Instagram reads captions from the signed-in keyword grid (mission surface `instagram_host_browser`);
the retired `reels` surface stays refused. Submit and cancel keep their three ID parameters. There are still 41 tools.
Threads collection uses only the authorized host browser. Internal Playwright collection and
placeholder suggestion/trending tools have been removed. Stored Threads credentials do not
establish collection readiness. No API grant probe or API fallback is activated.

Spec 022 retires Google Trends RSS, Creative Center, TikTok headless keyword search and Reels
collection. Existing observations, channel outcomes and sessions remain readable and unchanged.
A mission naming a retired surface returns `BLOCKED / SURFACE_RETIRED` before collection.
A watchlist run removes retired entries from its requested resources and reports them explicitly;
if none remain, it is blocked. Retirement is never a measured zero.

TikTok now uses `tiktok-public-grid-v4`; Threads uses `threads-search-top-v2`. In v4 a TikTok
observation's publication time is decoded from its video id (the id's upper 32 bits are the publish
second), so its watchlist period follows the publish day instead of the first collection; v3 kept it
unknown. Watchlist periods spanning either upgrade report `not_comparable` with `collection_path_changed` or
`collection_path_mixed` when their collection paths differ or mix.

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


## Verification and release status

Run `.venv/bin/pytest tests/` for the CI test scope and `uv lock --check` for lock
consistency. The pilot and release gates are tracked in
[Spec 011 tasks](specs/011-evidence-grounded-product-reset/tasks.md).

## License

See [LICENSE](LICENSE).
