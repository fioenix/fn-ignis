# fn-ignis — Review Context

Written for an engineer or agent asked to review this project and recommend what to do next.
It states what the system is, what has actually been measured, what has not, and where the
reasoning is thin. It is in English because it describes `src/` and is read alongside
`AGENTS.md`; regional documentation lives in the `*.vi.md` files.

## Current review target — updated 16/09/2026

The runtime storage model that produced the mission-evidence defect documented below has been
replaced, and the replacement is now on `main` at `v0.4.0`. That version is **not released**: no
tag exists and no GitHub Release is published. `python scripts/check_release_state.py` reads that
off Git and GitHub, which is where the answer lives; no document in this repository can settle it.
What remains outstanding is separate from the release state, and the items below are
separate from each other:

- **The existing PostgreSQL corpus has not been migrated.** It has received neither `sql/016` nor
  the backfill, and the new runtime has not been activated against it. This blocks activation on
  that corpus; it does not block publishing a release that a new user installs on a fresh SQLite
  database, because such an install has no legacy corpus to migrate.
- **The repository is private.** Every pre-public condition in the public-visibility decision
  below must be satisfied, and the commits that enforce them must be on `main` before visibility
  changes. The conditions are written once, in that decision, and this summary points at them
  rather than restating or counting them: a count here has to be re-counted by whoever changes
  the list, and nothing makes them.

The branch state independently verified before this documentation refresh:

| Gate | Result |
|---|---|
| Full suite | 866 passed, 2 skipped on the current tree (831 when the storage model was first reviewed) |
| Ruff, package build, clean-install smoke test | passed in GitHub Actions |
| Dual backend | SQLite plus a real disposable TimescaleDB service; no silent Postgres skip |
| PR | not draft, mergeable, merge state clean |
| Migration rehearsal | `VERIFIED` on a disposable copy of the real corpus; not rerun for the final pool/version-only commits |

The branch has one runtime source of truth:

- `sources`: canonical external object, enforced by `UNIQUE(platform, external_id)`;
- `observations`: one immutable collection event, including cluster membership, identity route and
  clock provenance;
- `mission_evidence`: the exact observation used by each mission.

Readers, writers, scoring and pruning use that model. `trend_signals` and `signal_metrics` remain
legacy migration inputs and receive no runtime writes. The canonical production sequence is in
[`docs/migrations/2026-09-10-source-observation-baseline.md`](migrations/2026-09-10-source-observation-baseline.md#production-cutover-runbook).
The tracked JSON is a policy/rehearsal artifact; production must generate a baseline from the exact
snapshot taken after ingress is quiesced.

Everything below this block describes the **historical 10/09 snapshot** unless explicitly amended.
It is retained because the failed measurements and reversals explain the contracts now present in
the branch.

**Historical snapshot re-taken 10/09/2026 at 08:10 UTC, after that day's fixes landed.** Every figure below
was read from the running system at that moment, not from a changelog — corpus counts came from
the live Postgres, test counts from `pytest tests/`, CI status from `gh run list`. Re-read them
before relying on them; `git log docs/PROJECT_REVIEW_CONTEXT.md` shows when this file was last
brought up to date.

The day this snapshot covers was spent on repair, not features, and that shows in §8: four
defects in the setup and config path were found by writing tests for them rather than by using
the product. §4 carries the project's first end-to-end product measurement, and §7 records what
the owner has decided since the previous snapshot.

**Amended the same day, after an external review.** That review found two defects that outrank
everything else here and that this document had asserted around rather than noticed: mission
evidence is not reproducible from the database, and the two mission execution paths disagree on
timeframe and on replacement semantics. Both were independently verified before this amendment —
see the note in §4 and item 0 in §6. The §4 signal counts are annotated rather than deleted,
because the gap between what a run summarised and what it persisted is the evidence for the
defect. The review itself is kept outside the repository.

---

## 1. What this is

A self-hosted social-listening and market-opportunity harness. It is an **agent harness**, not
a pipeline: it exposes 39 FastMCP tools and expects the calling agent to compose them. The
6-step research framework in `CLAUDE.md` is a recipe on offer, not a flow the code enforces.

Two ways in, and they differ in what they are allowed to filter:

| | Track 1 — worker | Track 2 — agent |
|---|---|---|
| Runs | Docker daemon, optional | On demand, per tool call |
| Connectors | HTTP-capable discovery/probe connectors available in the worker image | all registered connector surfaces, browser included |
| Cadence | `SCHEDULER_INTERVAL_SECONDS=8640` (~2.4h) | when asked |
| Off-locale content | filtered by a script guard | kept, in any language |

The cadence is derived, not chosen: one pass probes up to 10 keywords, a YouTube `search.list`
costs 100 quota units, and the default daily quota is 10,000, so ten passes a day is the
ceiling. Changing `MAX_TOPIC_KEYWORDS` changes the safe cadence.

The trigger distinction is deliberate and lives in `IngressTrigger`: a scheduled pass filters
by script because nobody asked for it, a requested pass keeps what it found because somebody
did. See `AGENTS.md` § "Ingress Filtering Depends on Who Asked".

## 2. Reading the architecture

Three diagrams, each answering a different question, all verified against code on the date in
their footers. The set is deliberately small: a reader choosing between six pictures reads none.
The date is recorded here as well as in the footer, and a test fails when the two disagree —
otherwise redrawing a diagram and leaving its footer alone dates the new picture to the day the
old one was checked.

- `docs/assets/architecture.{png,svg,html}` — **what the shape is** (footer verified 16/09/2026).
  The dual-track model, the two-stage ingress, and the evidence store it writes into.
- `docs/diagrams/ignis-source-map.{png,svg,html}` — **where the data comes from** (footer verified
  16/09/2026). Six connectors grouped by the runtime each needs, which is what decides whether the
  unattended worker can register it, with the credential each wants and whether it discovers topics
  or answers keyword probes.
- `docs/diagrams/ignis-pipeline.{png,svg,html}` — **how a signal becomes a dossier** (footer
  verified 17/09/2026). Lane-scoped flow from discovery through the quality gate to the artifact.

A fourth diagram, a tool-by-tool call trace of one session, was retired on 14/09/2026. It
documented a defect fixed on 10/09 — `trigger_ingress_refresh` took no timeframe, so every
requested pass ran at 24h — beside corpus counts from the day it was drawn. A picture of a bug that
no longer exists is worse than no picture; the fix is recorded in `BACKLOG.md`, where a decision
belongs.

**Convention, decided 10/09/2026, narrowed 16/09/2026: this repository does not use mermaid.**
A diagram is authored as HTML with one inline SVG, and that HTML is the only file anyone edits.

Exports are generated, never hand-written, by `scripts/export_diagram.py`, which reads the HTML,
extracts the inline SVG, writes the standalone `.svg`, and rasterizes the `.png` from it. `--check`
verifies both derived artifacts, and tests enforce the same thing. The SVG is compared byte for
byte, because it is generated deterministically. The PNG cannot be — a different Chromium on a
different OS renders the same picture to different bytes — so it carries the SHA-256 of the SVG it
was rasterized from in a `tEXt` chunk, and `--check` verifies the signature, that the declared size
is the viewBox at 2x, and that the stamped digest is the one the HTML exports to today. Before
that, replacing the PNG with a line of text left `--check` reporting success.

**Only a diagram a document embeds as an image gets exports.** All three qualify as of 17/09/2026:
both READMEs place each of them with an `<img>` tag, which cannot render HTML. Until then only
`architecture` was embedded and only `architecture` had exports, because generated files nothing
consumes are surface that drifts — the failure this convention exists to prevent. The rule was
written with that condition stated in advance ("if a document ever embeds one of those two, it
gets exports at that point"), so this is the rule firing rather than an exception to it. A
diagram that stops being embedded loses its exports again. The reason is the first failure mode in
§8: a mermaid block was labelled as the source of a hand-authored SVG, the two drifted, and the
label was the thing that lied. Do not add mermaid blocks when recommending changes here.

`ignis-pipeline` was redrawn on 17/09 before it could be embedded: six detail lines overflowed
their cards, measured with `getComputedTextLength()` rather than judged by eye. The export gate
had passed on it the whole time, because provenance says the picture came from its source, not
that the picture is legible.

Three things those diagrams got wrong until 09/09/2026, worth knowing because the old shape is
still in people's heads:

1. **The Quality Gate is not an ingress filter.** in `autonomous_discovery.py`,
   `evaluate_quality` runs after `save_signals`, and it returns a `QualityScorecard`. It scores
   a corpus that is already stored and never rejects a row. The only action taken on a low score
   is one further ingress pass, in `AutonomousRefinementOrchestrator.run_mission_harness`.
2. **Ingress is two-staged.** Stage 1 pulls the feeds that discover topics; stage 2 takes those
   topics plus lexicon seeds and probes the remaining connectors by keyword. That second stage
   is the only reason a cluster can span platforms.
3. **Track 1 cannot reach TikTok, Threads-without-token or Reels.** The worker image ships no
   browser. Each connector decides for itself via `resolve_ingest_runtime()`.

## 3. Measured state

Read from the live Postgres on 10/09/2026 at 08:10 UTC.

| | |
|---|---|
| Signals | 15,938 |
| Clusters | 1,128 |
| Lexicon terms | 338 across 25 domains in `market_lexicons` |
| Industry taxonomies | 14 rows in `industry_taxonomies` |
| Missions | 33 |
| `published_at` populated | 15,456 / 15,938 |

Signals by platform: `youtube 14,869 · threads 517 · tiktok 333 · google 189 · reels 30`.

The previous snapshot said "338 across 14 taxonomies", which conflated two tables. The 338 terms
span 25 `domain` values in `market_lexicons`; the 14 is the row count of `industry_taxonomies`,
a different thing. Worth noting as an instance of the pattern in §8: a number that reads as one
fact was two.

**YouTube is 93% of the corpus, and most of that is an artefact rather than a collection
result.** Until 10/09 `captured_at` held the *publish* time for YouTube and the Google Trends
feed, and the ingestion time for everything else. YouTube rows therefore carry publish dates
spread over three months and fill any window at once, while the browser connectors only
populate the days a pass actually ran. The column is split now (`captured_at` is always
ingestion, `published_at` is what the platform reports), but the historical rows still hold the
old meaning in `captured_at` and cannot be corrected — the true ingestion time was never
recorded. Windows over them stay approximate until they age out.

Clustering:

| | |
|---|---|
| Multi-platform clusters, all history | 51 / 1,120 — **4.6%** |
| Multi-platform clusters, the one full 6-connector pass | 8 / 31 — 25.8% |
| Clusters at BREAKOUT (`cross_platform_score >= 80`) | 5 |
| `unclassified` | 883 / 1,128 — 78% |

`topic_clusters` has no `platform_count` column; the multi-platform figure is computed by
grouping `trend_signals` on `cluster_id` and counting distinct platforms, over the 1,120
clusters that actually carry signals. Eight of the 1,128 carry none.

The gap between 4.6% and 25.8% is the point: most stored clusters predate the two-stage
ingress, so the lifetime figure describes history and the per-pass figure describes current
behaviour. Neither has been measured on a second full pass.

**TikTok metric coverage, all history: 316 of 333 rows carry a `metric_value`; 17 do not
(5.1%).** That ratio is the residue of a race fixed on 10/09 — see §4. Rows collected in the
window before the fix show a 68.8% loss, so a supply score computed over that window
understates supply and inflates the Opportunity Index.

## 4. What is verified, and what is not

**Current verification.** On the current tree, 866 tests pass and 2 skip. The two skips are Postgres-only cases under the SQLite parameter. CI runs
Ruff, `pytest tests/`, `uv build`, and an MCP session driven against the built wheel rather than an
editable install. Installation is `uv sync --locked`, so the committed lock is the environment under
test instead of a fresh resolution from the dependency ranges.

PostgreSQL contracts run against a real TimescaleDB service and are verified not to be skipping
silently: with `IGNIS_TEST_POSTGRES_DSN` set, 71 of them pass; with it unset, all 72 skip. The
service is disposable, never live Supabase.

**Convergence gaps measured 13/09/2026.** A local SQLite-only coverage run collected all 833 tests,
passed 740 and skipped 93 PostgreSQL cases because `IGNIS_TEST_POSTGRES_DSN` was not set. It measured
73% coverage overall and 71% across persistence/connectors. The latest CI run with Timescale reports
75% overall coverage and does not enforce `--cov-fail-under`; therefore SC-004's 85% target is not
an achieved gate. SC-001's `get_top_clusters` P95 < 50 ms target also has no reproducible
10,000-row benchmark in `tests/` or `scripts/`. These are T021 and T022 in the storage feature task
list.

**Historical snapshot verification.** 573 tests passed; CI ran Ruff then `pytest tests/` then `uv build` then a
quickstart install from a clean state, and is green. Dual-backend parity is exercised: a fresh
SQLite file, a pre-migration SQLite file upgraded in place, and the live Postgres. One full
6-connector pass completed in 171.6s on 09/09/2026 and stored 173 signals into 31 clusters with
nothing filtered out.

**The first product measurement exists now, and it is three missions, not one.** Same topic
(hair-colouring and salon services in Vietnam), same five keywords, geo VN, timeframe 7d, one
variable changed each time. Run 1 without a TikTok session, run 2 with one, run 3 after the
TikTok metric race was fixed.

| | 1 — no TikTok | 2 — logged in | 3 — race fixed |
|---|---|---|---|
| Signals **as summarised** | 55 | 115 | 156 |
| Signals **still attached in the DB** | 55 | **57** | **55** |
| tiktok | 0 `AUTH_REQUIRED` | 48 | 60 |
| threads | 0 `EMPTY_NO_DATA` | 10 | 39 |
| coverage | 40.0 | 100.0 | 100.0 |
| freshness | 100.0 | 90.4 | 77.6 |
| language precision | 34.5 | 40.9 | 38.5 |
| overall confidence | 67.0 `MEDIUM` | 80.7 `HIGH` | 75.5 `MEDIUM` |

> **This table is not reproducible from the database, and the reason is a defect.** An external
> review on 10/09 tried to recompute it and could not. Verified here: querying
> `trend_signals` by `mission_id` returns 55 / 57 / 55, not 55 / 115 / 156 — and mission 2 has
> **zero** Google rows and 3 YouTube rows, because those sources stayed attached to mission 1.
>
> Root cause, confirmed in `postgres_repository.py` (`save_signals`, mirrored in SQLite): rows are
> deduplicated globally on `(platform, source_url, raw_title)`, and the UPDATE branch refreshes
> `metric_value`, `captured_at`, `published_at`, `metadata` and `cluster_id` but **not
> `mission_id`**. A source therefore belongs permanently to whichever mission saw it first. The
> figures in the "as summarised" row are the in-memory counts each run collected; they were never
> persisted as that mission's evidence.
>
> A second confirmed defect compounds it. The two mission execution paths disagree:
> `ExecuteMissionUseCase` passes `custom_timeframe=mission.timeframe` and calls
> `delete_mission_signals` before saving; `AutonomousRefinementOrchestrator` — the path behind
> `run_autonomous_research_mission`, which produced these three runs — passes no timeframe and
> deletes nothing. It computes `tf_days` and hands it only to the quality evaluator. **So these
> runs collected on connector defaults while freshness was scored against 7 days.**
>
> Treat the rows below as directional evidence about connectors and about the metric fix, not as a
> measurement. The `55 → 115 → 156` growth and the coverage jump are corroborated by the channel
> summaries and by TikTok going from `AUTH_REQUIRED` to returning rows. The freshness decline, and
> therefore conclusion 3, rest on a comparison the collector never honoured.

Three things a reviewer should take from that table, because none of them is obvious:

1. **An authenticated session, not any algorithm change, is what moved the product.** Coverage
   40 → 100 and signals 55 → 115 came from one login. Everything the harness computes downstream
   was being computed over a corpus missing a whole platform.
2. **Fixing the metric race raised supply and therefore lowered the Opportunity Index.** For the
   three keywords with videos, supply went `20.4 → 44.4 → 95.4` (`hair colorist`),
   `8.3 → 16.3 → 44.1` (`nang tone`), `34.3 → 49.3 → 51.4` (`tay toc`), and the index fell
   correspondingly — `hair colorist` from `+9.8` to `−62.0`, reclassified
   `BALANCED_COMPETITION` → `SATURATED_SEGMENT`. That is the formula behaving correctly on
   better input, not a regression. Any earlier index reading was biased optimistic.
3. **Confidence fell while the corpus grew.** 80.7 `HIGH` → 75.5 `MEDIUM`, driven entirely by
   freshness 90.4 → 77.6 as Threads went 10 → 39 signals and the new ones were older. The
   scorecard treats a wider corpus as lower quality. Whether that is the right weighting is an
   open product question — see §9 — **but this particular reading is not evidence for it**,
   because the collector ignored the 7-day timeframe the freshness score was computed against.
   The weighting question stands on the formula, not on this number.

**Not verified.** Two of the five keywords (`salon toc`, `cong thuc nhuom`) returned n=0 videos
in all three runs, so their index reflects demand only and stays `UNVERIFIED_DEMAND_GAP`. And
run 3 logged `No TikTok JSON payload arrived within 12000ms` five times, once per keyword, at
~17s intervals. The database says only 6 of that run's 60 TikTok signals lack a metric, so the
fallback returned almost nothing and the other 54 came from other calls — but 10% is still
above the 2.1% measured in the controlled before/after test, and more than 20 TikTok searches
had been issued in the preceding 20 minutes. **This measurement is plausibly contaminated by
test volume.** A fourth run after a cooldown, same parameters, is what would settle it.

**Environment traps that have already produced wrong conclusions here.** CI installs the
Playwright module through the `browser` extra but never runs `playwright install`, so there is
no browser in CI and any test asserting a live browser-dependent result fails there and passes
locally. A local venv built the way CI builds it still shares this machine's Playwright browser
cache, so it is not CI-shaped in that dimension. `pytest tests/unit/` is four integration tests
short of what CI runs.

## 5. Where the design decisions are recorded

`BACKLOG.md` is the decision log, not a task list. Counts change as evidence closes or splits an
item; run `rg '^- \[ \]' BACKLOG.md` instead of copying a count into another document. Read the
closed entries — several record a conclusion that was
reached, tested, and then reversed, and the reversal is the useful part. In particular:

- Relevance is judged downstream, never at ingress. Judging it at ingress meant the radar could
  only store topics somebody had already seeded, which is the opposite of what a radar is for.
  It rejected 67.8% of a real corpus, including a course on AI for beginners.
- Vietnamese is matched with its tone marks. Folding accents to "canonicalise" collapses
  distinct words (`vàng`/`vang`, `tóc`/`tốc`, `chính phủ`/`chinh phục`) and produced a run of
  wrong categories. Four compensating rules were added before the premise itself was questioned.
- Cluster identity is `uuid5` of `canonical_name`, so that field is an identity key and must
  stay byte-stable; `topic_label` is the display string and is free to change.

## 6. Known debt, with locations

Ordered by how much a reviewer's conclusions would change if they did not know about it.

0. **Resolved in code; migrating an existing corpus remains.** The historical defect was that
   `trend_signals` combined source identity, observation and one mission owner. The branch now
   separates `sources`, `observations` and `mission_evidence`; one source can support two missions,
   one mission can retain two observations of a source, and both backends run the same behavioral
   contracts. Evidence replacement writes new claims before pruning old ones, and the mission paths
   preserve timeframe and observation identifiers. The `0.4.0` runtime is present on `main`; a
   deployment carrying a legacy corpus is not complete until its snapshot-specific backfill returns
   `VERIFIED`.

1. **Probe seeds were machinery vocabulary until 10/09/2026.** Adding eight machinery domains to
   `market_lexicons` on 09/09 left an exclusion list in `ingest_trends.py` naming only the two
   original domains, so every seed a public pass probed with was a Vietnamese function word —
   `ambiguous_unigrams` sorts first alphabetically and filled the budget. There is one list now,
   in `vocabulary_loader`, and a test that fails if a second copy appears. **Any measurement of
   the keyword fan-out taken before this date is void.**
2. **The taxonomy does not cover an open listening question.** 78% of clusters are
   `unclassified`. The taxonomy is shaped for market verticals; Google Trends VN daily is news
   and entertainment. This is a product-scope question, not a bug — see §7.
3. **Six vocabulary constants remain in `src/`**, tracked in
   `tests/unit/test_repo_conventions.py`: `VI_CORE_WORDS` and `TECH_LOAN_WORDS`
   (`language_detector.py`) are real language vocabulary; `RATE_LIMIT_HINTS`,
   `AUTH_SENSITIVE_PLATFORMS`, `VIDEO_PLATFORMS` (`strategic_reasoner.py`) and
   `BROWSER_API_MARKERS` (`reels_plugin.py`) are arguably platform enums rather than domain
   terms. The gate records them rather than blocking them; deciding which are exempt is open.
4. **The supply score cannot tell "no data" from "nobody watched".** `view_factor = 0.0` when
   `loc_views == 0`, and that is also what a keyword with zero retrieved videos produces. Two of
   the five keywords in §4 sat at n=0 through all three runs; their index is a demand reading
   wearing a supply-adjusted label. The `UNVERIFIED_DEMAND_GAP` type names the condition, but the
   number it is attached to is not comparable with the others.
5. **`_contiguous_phrase` only reads `canonical_name`.** When the phrase worth labelling lives
   in a sibling signal's title, the label falls back to a dot-joined token list.
6. **The `tiktok_ui_noise` vocabulary is probably net-harmful.** It exists to keep the operator's
   own notification and inbox wording out of the corpus, and it is now matched on word
   boundaries rather than raw substrings — the earlier behaviour dropped a genuine video because
   `"live "` matched inside `"olive oil review"`. Three of its terms (`live`, `thông báo`,
   `tin nhắn`) are ordinary Vietnamese that legitimate content uses. Removing them is the
   owner's call, because this guard fails closed on purpose: it protects privacy, so its cost is
   paid in recall.
7. **Five files stay on the non-ASCII allowlist**, each with a stated reason: character classes
   that are the algorithm, and third-party UI selectors that must match verbatim.
8. **`synthetic_probe` duck-types its collaborator.** Same weakness that produced the bug in §8:
   `hasattr` is true for any `Mock`, so a test double satisfies the check without satisfying the
   contract.

## 7. Decisions: open, and recently settled

Items 1–4 are not tasks. They are calls nobody has made, and code should not be written past
them. Items 5–6 were settled on 10/09 and are recorded here because a reviewer arriving with the
previous snapshot in hand will otherwise re-raise them.

1. **Scope.** Should a market-opportunity harness track football, weather and celebrities? The
   owner has said yes in principle ("to understand the market you have to understand every
   other field too"), which implies widening the taxonomy into a general Vietnamese classifier —
   a much harder thing to keep accurate. The alternative is to rank by cross-platform momentum
   and treat category as an optional tag, which makes `unclassified` harmless.
2. **How an open question should be answered.** `trigger_ingress_refresh` seeds from the lexicon,
   so "what is everyone discussing" is answered as "what is happening around terms we already
   seeded". A two-pass shape — discovery first, then the agent picks what to probe — is what the
   two-stage ingress was built for, and nothing currently does the picking.
3. **Whether to make the repository public.** The code side is close: `v0.4.0` is on `main`, CI is
   green on the merge commit, and the community files are present with one synchronised version
   across every release-controlled file (six files, not three; the count was corrected on 13/09).
   The acceptance gate that an MCP connection and direct JSON-RPC could not close is closed: on
   14/09 a signed-in Claude Code session had the model itself call `get_runtime_config`, which
   returned `SUCCESS` and `total_configs: 6`, and the model read that back. `BACKLOG.md` records
   it with the evidence. The keyword-search authority gap is closed too: the verdict the access
   probe establishes is now persisted, and the tier resolution, the runtime resolution and the
   search path all read it, so a public-market probe can no longer query an endpoint the system
   has already established searches the operator's own account. The earlier statement that nothing
   blocked the switch still does not hold. What remains, each of them work rather than a decision:
   - operational credentials must be rotated or revoked before visibility changes (item 5). No
     rotation evidence exists, so nothing may record that it happened;
   - no public-facing document may carry the internal register, infrastructure identifiers, or a
     reference to a file that is not published, and the commits that enforce this must be on
     `main` before visibility changes. Written and reviewed is not the condition; being an
     ancestor of `main` at the moment of the switch is.
   `gh repo view` still reports `PRIVATE`, and no tag or Release exists for `0.4.0`;
   `python scripts/check_release_state.py` is what reads those three facts, and it reports a fact
   it could not establish as unknown rather than as a negative.
4. **Git history.** A platform API key was once committed and has since been rotated. History was
   rewritten on 09/09 and every ref force-pushed, so the value is unreachable from any ref;
   `git rev-list --all` carries no full-length key. Whether the remote has finished garbage
   collecting the unreachable objects has not been verified from this side, so treat that as
   unknown rather than complete.
5. **Superseded on 14/09: the deferral of credential rotation no longer applies.** On 10/09 three
   operational credentials reached a session transcript, and rotation was deferred on the express
   condition that it be revisited if anyone outside the current users gained access. Publishing
   the repository is that condition. The deferral is therefore withdrawn, and rotation is an open
   blocker ahead of any visibility change.

   The values are absent from git history, verified across `git rev-list --all`. One constraint
   shapes the work: the current release has no dual-key decryption path, so replacing the
   encryption key makes existing ciphertext unreadable and each connector must be re-authenticated
   afterwards. That is a sequencing problem, not a reason to skip rotation.

   No rotation evidence exists yet, so `BACKLOG.md` carries this as an open item. It must not be
   marked done, and nothing may claim rotation has happened, until the operator confirms it.
6. **The local config chores are done for three of four clients; Claude Desktop remains stale.**
   Re-checked 13/09: its entry still has the four credential keys, while the workspace `.mcp.json`
   has only `IGNIS_ENV_FILE`. `./scripts/bootstrap.sh` was run on 10/09;
   `.mcp.json`, Antigravity's config and `~/.codex/config.toml` now carry only `IGNIS_ENV_FILE`.
   `claude_desktop_config.json` was rewritten too, and verified — then **reverted**.

   An external review flagged the old four-key `env` block still present. Re-checked: the entry
   is byte-identical to the pre-bootstrap backup, the file's only other difference from that
   backup is a list of app-managed `local_*` preference UUIDs, and its mtime is roughly an hour
   after the last bootstrap write. **Claude Desktop holds its own copy of that file and writes it
   back from memory, discarding external edits made while it runs.** The restored block carries
   the *revoked* YouTube key, not the current one, which is why MCP YouTube calls failed while the
   same code succeeded from a shell.

   The order therefore matters and is not what a reviewer would guess: quit Claude Desktop
   **first**, then run `./scripts/bootstrap.sh`, then start it. Running bootstrap while the app is
   open changes nothing durable. Claude Desktop and Cowork share this file — it carries
   `coworkUserFilesPath` alongside `mcpServers` — so it is the one that matters for both.

   The previous snapshot listed a duplicate `fn-ignis` registration as the likely cause of
   `Connection closed`; there is one registration per client file, so that hypothesis was wrong
   and the cause is still unknown. The durable order is: quit Claude Desktop, run bootstrap, then
   reopen it.

## 8. Failure modes this project has actually exhibited

A reviewer will find these faster if told where to look. Each was diagnosed here, more than once.

**Two copies of one truth.** It has appeared seven times in four days: the architecture existed
as both a hand-authored SVG and a mermaid block labelled as its source, and they drifted; the
non-topic domain list existed in `vocabulary_loader` and `ingest_trends`; the YouTube key
existed in `.env`, `.mcp.json` and Claude Desktop's config, and the stale copy silently won
because a host's `env` overrides an env file; the label-quality defect had two BACKLOG entries
and the fix closed only one. Then on 10/09, three more: the ingress cadence existed as `8640` in
`ignis.config` and `env.example` and as `900` in the `.env` template the provisioner writes and
in four dead parameter defaults in `scheduler.py`; `~/.codex/config.toml` accumulated a second
`[mcp_servers.fn-ignis.env]` table on every run, so the old secrets outlived the migration meant
to remove them; and the lexicon count read as "338 across 14 taxonomies" when the 338 and the 14
come from different tables. When reviewing, ask of every value: how many places hold it, and
which one wins.

**A configuration value that overrides the value documented next to it.** `env.example` set
`SYNC_INTERVAL_MINUTES=60` on the line above `SCHEDULER_INTERVAL_SECONDS=8640`. Any value above
0 wins over the seconds field, so copying the file — the usual first step after a clone — gave a
60-minute tick, 24 passes a day against a budget that fits 10, while the line right below looked
correct. Both lines were individually defensible; only reading them together revealed the fault.
The test that now guards it does not compare either line to anything — it feeds both through
`resolve_ingress_interval()` and asserts what a copied file actually schedules. **When a
setting can be overridden, test the resolved value, not the file.**

**A status message that reports work it did not do.** The provisioner gated its write on
comparing rejoined lines against the original text. Those differ by the trailing newline almost
every editor leaves, so a run that generated nothing rewrote the file and printed `Updated
existing .env with generated IGNIS_ENCRYPTION_KEY`. Rotating that key strands every credential
encrypted under the old one, so the message sent the reader to verify a key fingerprint before
daring to continue. It printed on two consecutive runs while the key was provably unchanged.

**A masked value is only masked where someone remembered to mask it.** pytest prints `repr()` of
every object in a failing assertion's frame. With `str`-typed settings, one failing test in any
function holding a `Settings` reference dumped the database password, the Fernet key and the
platform keys into the log — which on a public repository would be world-readable. This was
observed, not theorised: a failing scheduler test in that session printed an operational database
password into pytest output. `verify_connectors_health` independently echoed a full proxy URI,
credentials included, into tool output. Both are fixed; the general lesson is that a secret leaks through whatever generic
machinery touches it, not through the code that was written to handle it.

**A gate with an allowlist stops being a gate.** `test_repo_conventions.py` tracked hardcoded
vocabulary on an allowlist, and two of its entries named constants that did not exist in the
codebase under those names — so those entries covered nothing while reading as covered. Its
name-matching regex also missed `BLACKLIST` and `WORDS`, which is how the real constants stayed
invisible. Check that each allowlist entry still matches something real.

**A green check that measures the wrong thing.** Two connector health probes returned a literal
`True`; `verify_connectors_health` reported them HEALTHY on a host with no browser at all. Four
of six were real. When a check is all green, ask what would make it red.

**Verification from the nearest surface rather than the real one.** Reported figures in this
repo have come from a CLI that ran 2 of 6 connectors, from `pytest tests/unit/` while CI runs
`pytest tests/`, from a local venv sharing the host's browser cache, and from a Postgres
`EXTRACT(microsecond)` that returns seconds×10⁶ plus microseconds and so made almost every row
look sub-second. Ask what command produced a number before trusting it.

**A diagnosis that describes the code instead of explaining the symptom.** The TikTok metric
loss took four attempts. The first named a "positional parse" -- an accurate description of the
parser that was not the cause. The second claimed the cards had not rendered, measured with a
probe that read `card` while the parser reads its parent element. The third declared `views=0`
inherent to the search path, contradicted by the stored rows: 255 of the 259 TikTok signals
captured before 10/09 carry a metric. Only the fourth found it: the code waited a fixed 3500ms
for a JSON payload, then fell through to a DOM path that carries no view counts. The fix polls
to a 12s ceiling and logs when it gives up; loss over three runs before and after went
68.8% -> 2.1%. **A diagnosis that does not predict a measurement is a description.** The same
pattern produced a claim that `search_across_all` requires a session; it does not --
`AUTH_REQUIRED` comes from `strategic_reasoner`'s `auth_status` map, while `search_signals`
passes `storage_state=None`.

**A test double that satisfies a check without satisfying the contract.** `hasattr` is true for
any `Mock` or `AsyncMock`, so a capability probe written with it passed on a double and put an
`AsyncMock` into a JSON payload, breaking two unrelated tests. The health branch now accepts
only a non-empty string. `synthetic_probe` still duck-types the same way (§6).

## 9. Suggested review angles

1. **Treat production cutover as the remaining data-model activation blocker, not automatically as
   the only release blocker.** Review the fresh snapshot baseline, four digests and `VERIFIED`
   result; do not accept the tracked rehearsal JSON as the production reference. Separately decide
   whether the inherited but unmet SC-001 latency benchmark and SC-004 coverage threshold block
   merge or are explicitly re-scoped; a mergeable PR and green CI do not settle either criterion.
2. **Review citation identity next.** Storage now knows the exact mission observation, but
   `CitationEvidence` has no `observation_id` and the citation registry keys on platform plus
   URL-or-title. That is a second source-identity policy and can disagree with the canonical
   resolver.
3. **Read `BACKLOG.md` closed entries first.** They carry the reasoning and the measurements;
   the code shows only the outcome.
4. **Question the Opportunity Index.** It compares demand velocity against localised supply
   volume on a corpus that is 93% one platform, most of that a timestamp artefact. Is the
   formula sound, and is the input good enough for it to mean anything yet? §4 gives the first
   real evidence to argue with: the same keyword moved from `+9.8` to `−62.0` purely because
   supply was being counted correctly, which says the formula responds to input quality exactly
   as designed and that every earlier reading was optimistic.
5. **Question whether freshness should penalise a larger corpus.** In §4, confidence fell from
   80.7 `HIGH` to 75.5 `MEDIUM` while signals rose 115 → 156, entirely because the added Threads
   signals were older. `SCORECARD_WEIGHT_FRESHNESS` is 0.30, the largest of the four weights. A
   reviewer should ask whether freshness belongs in a *confidence* score at all: it measures how
   recent the evidence is, not how much of it there is or how well it was verified. Recency may
   belong as a reported dimension rather than a term that can downgrade a wider corpus.
6. **Ask what the product question is.** Two days before this snapshot the work was foundation
   repair driven by a self-generated backlog, and the owner stopped it to ask whether any of it
   advanced the product. The honest answer was no. §4 exists because of that intervention. A
   reviewer is better placed than the codebase to say which current open entries actually move a
   user decision and which are tidiness. Count the live set from `BACKLOG.md`; do not copy a count
   into another document.
7. **Question the harness boundary.** The MCP layer is supposed not to dictate workflow
   (`CLAUDE.md` Checklist B), yet `run_autonomous_research_mission` and
   `trigger_autonomous_discovery` are end-to-end pipelines. Is that a contradiction worth
   resolving, or two legitimate levels of abstraction?
8. **Question the fail-open / fail-closed choices.** They are deliberate and inconsistent on
   purpose: the TikTok notification guard fails closed because it protects the operator's inbox;
   the clusterer, the probe templates and the language detector fail open with a warning because
   failing closed would empty the corpus. Are they drawn in the right places?
9. **Look for the next duplicated value.** Given the pattern above, assume there is one.

## 10. Running it

```bash
./scripts/bootstrap.sh              # venv, .env, schema, seeds, MCP registration, self-test
.venv/bin/pytest tests/             # what CI runs
.venv/bin/pytest tests/unit/test_repo_conventions.py   # the language and vocabulary gates
python -m ignis.interfaces.cli.setup_bundle --json      # re-register MCP, rewrite configs
```

Migration tooling is intentionally explicit and fail closed:

```bash
python scripts/migration_reconciliation_audit.py --help
python scripts/backfill_observations.py --help
python scripts/post_migration_verification.py --help
```

SQLite is the zero-config default and needs no Docker. `DATABASE_URL=postgresql://…` switches to
the Postgres/Timescale repository; `sql/001` enables the Timescale extension when present and
falls back to native Postgres indexes when not. The vocabulary seeds `sql/012`–`sql/014` are re-applied
on every SQLite bootstrap, because the domains they seed are system-owned and no tool writes
them; on Postgres they are run once by hand. `sql/015` adds a column instead of seeding rows, so
SQLite applies it through an `ALTER TABLE` in `_ensure_schema`.
