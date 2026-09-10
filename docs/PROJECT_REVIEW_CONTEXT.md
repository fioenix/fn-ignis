# fn-ignis — Review Context

Written for an engineer or agent asked to review this project and recommend what to do next.
It states what the system is, what has actually been measured, what has not, and where the
reasoning is thin. It is in English because it describes `src/` and is read alongside
`AGENTS.md`; regional documentation lives in the `*.vi.md` files.

**Snapshot taken 10/09/2026, on the tree this file was added to.** Every figure below was read
from the running system on that date, not from a changelog — including the corpus counts, which
came from the live Postgres. Re-read them before relying on them; `git log docs/` shows when this
file was last brought up to date.

---

## 1. What this is

A self-hosted social-listening and market-opportunity harness. It is an **agent harness**, not
a pipeline: it exposes 39 FastMCP tools and expects the calling agent to compose them. The
6-step research framework in `CLAUDE.md` is a recipe on offer, not a flow the code enforces.

Two ways in, and they differ in what they are allowed to filter:

| | Track 1 — worker | Track 2 — agent |
|---|---|---|
| Runs | Docker daemon, optional | On demand, per tool call |
| Connectors | Google Trends RSS, YouTube Data API | all six, browser included |
| Cadence | `SCHEDULER_INTERVAL_SECONDS=8640` (~2.4h) | when asked |
| Off-locale content | filtered by a script guard | kept, in any language |

The cadence is derived, not chosen: one pass probes up to 10 keywords, a YouTube `search.list`
costs 100 quota units, and the default daily quota is 10,000, so ten passes a day is the
ceiling. Changing `MAX_TOPIC_KEYWORDS` changes the safe cadence.

The trigger distinction is deliberate and lives in `IngressTrigger`: a scheduled pass filters
by script because nobody asked for it, a requested pass keeps what it found because somebody
did. See `AGENTS.md` § "Ingress Filtering Depends on Who Asked".

## 2. Reading the architecture

Two diagrams, both verified against code on the date in their footers:

- `docs/assets/architecture.{png,svg,html}` — the dual-track model and the two-stage ingress.
- `docs/diagrams/ignis-social-listening-trace.html` — the tool-by-tool trace of one real
  question, with the gaps that question exposes.

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

Read from the live Postgres on 10/09/2026.

| | |
|---|---|
| Signals | 15,771 |
| Clusters | 1,114 |
| Lexicon terms | 338 across 14 taxonomies |
| Missions | 30 |
| `published_at` populated | 15,400 / 15,771 |

Signals by platform: `youtube 14,813 · threads 486 · tiktok 259 · google 184 · reels 29`.

**YouTube is 94% of the corpus, and most of that is an artefact rather than a collection
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
| Multi-platform clusters, all history | 44 / 1,113 — **4.0%** |
| Multi-platform clusters, the one full 6-connector pass | 8 / 31 — 25.8% |
| Clusters at BREAKOUT (`cross_platform_score >= 80`) | 5 |
| `unclassified` | 872 / 1,114 — 78% |

The gap between 4.0% and 25.8% is the point: most stored clusters predate the two-stage
ingress, so the lifetime figure describes history and the per-pass figure describes current
behaviour. Neither has been measured on a second full pass.

## 4. What is verified, and what is not

**Verified.** 518 tests pass; CI runs Ruff then `pytest tests/` then `uv build` then a
quickstart install from a clean state, and is green. Dual-backend parity is exercised: a fresh
SQLite file, a pre-migration SQLite file upgraded in place, and the live Postgres. One full
6-connector pass completed in 171.6s on 09/09/2026 and stored 173 signals into 31 clusters with
nothing filtered out.

**Not verified.** The numbers the README sells — Opportunity Index, Quality Gate confidence —
have never been measured on a corpus collected entirely under the current ingress. The one full
pass that exists was run while every probe seed was a Vietnamese function word (see §6), so its
stage-1 signals are sound and its keyword fan-out results are not. A second full pass with
clean seeds is the single highest-value thing a reviewer could ask for; it costs 1,000 YouTube
quota units, a tenth of a day.

**Environment traps that have already produced wrong conclusions here.** CI installs the
Playwright module through the `browser` extra but never runs `playwright install`, so there is
no browser in CI and any test asserting a live browser-dependent result fails there and passes
locally. A local venv built the way CI builds it still shares this machine's Playwright browser
cache, so it is not CI-shaped in that dimension. `pytest tests/unit/` is four integration tests
short of what CI runs.

## 5. Where the design decisions are recorded

`BACKLOG.md` is the decision log, not a task list: 50 closed entries, each with the measurement
that settled it, and 20 open. Read the closed ones — several record a conclusion that was
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
4. **`_is_private_or_notification` matches raw substrings.** `"live "` matches inside
   `"olive oil review"`, so a genuine video is dropped as a notification. Predates the move of
   that vocabulary into the database. Fixing it by word boundary is a behaviour change.
5. **`_contiguous_phrase` only reads `canonical_name`.** When the phrase worth labelling lives
   in a sibling signal's title, the label falls back to a dot-joined token list.
6. **Five files stay on the non-ASCII allowlist**, each with a stated reason: character classes
   that are the algorithm, and third-party UI selectors that must match verbatim.

## 7. Open decisions, waiting on the owner

These are not tasks. They are calls nobody has made, and code should not be written past them.

1. **Scope.** Should a market-opportunity harness track football, weather and celebrities? The
   owner has said yes in principle ("to understand the market you have to understand every
   other field too"), which implies widening the taxonomy into a general Vietnamese classifier —
   a much harder thing to keep accurate. The alternative is to rank by cross-platform momentum
   and treat category as an optional tag, which makes `unclassified` harmless.
2. **How an open question should be answered.** `trigger_ingress_refresh` seeds from the lexicon,
   so "what is everyone discussing" is answered as "what is happening around terms we already
   seeded". A two-pass shape — discovery first, then the agent picks what to probe — is what the
   two-stage ingress was built for, and nothing currently does the picking.
3. **Git history.** A YouTube API key was committed in `.mcp.json` across 18 commits and has
   been rotated. History was rewritten on 09/09 and every ref force-pushed, but GitHub still
   serves unreachable objects by SHA until its own gc runs. The repo is private.
4. **Two local config chores** are the owner's, not a reviewer's: `claude_desktop_config.json`
   still holds a revoked key and three secrets (running `./scripts/bootstrap.sh` rewrites it),
   and `fn-ignis` is registered twice, in both `.mcp.json` and the Claude Desktop config, which
   is the likeliest cause of the `Connection closed` errors seen in Claude Code sessions.

## 8. Failure modes this project has actually exhibited

A reviewer will find these faster if told where to look. Each was diagnosed here, more than once.

**Two copies of one truth.** It has appeared four times in three days: the architecture existed
as both a hand-authored SVG and a mermaid block labelled as its source, and they drifted; the
non-topic domain list existed in `vocabulary_loader` and `ingest_trends`; the YouTube key
existed in `.env`, `.mcp.json` and Claude Desktop's config, and the stale copy silently won
because a host's `env` overrides an env file; the label-quality defect had two BACKLOG entries
and the fix closed only one. When reviewing, ask of every value: how many places hold it, and
which one wins.

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

## 9. Suggested review angles

1. **Read `BACKLOG.md` closed entries first.** They carry the reasoning and the measurements;
   the code shows only the outcome.
2. **Question the Opportunity Index.** It compares demand velocity against localised supply
   volume on a corpus that is 94% one platform, most of that a timestamp artefact. Is the
   formula sound, and is the input good enough for it to mean anything yet?
3. **Question the harness boundary.** The MCP layer is supposed not to dictate workflow
   (`CLAUDE.md` Checklist B), yet `run_autonomous_research_mission` and
   `trigger_autonomous_discovery` are end-to-end pipelines. Is that a contradiction worth
   resolving, or two legitimate levels of abstraction?
4. **Question the fail-open / fail-closed choices.** They are deliberate and inconsistent on
   purpose: the TikTok notification guard fails closed because it protects the operator's inbox;
   the clusterer, the probe templates and the language detector fail open with a warning because
   failing closed would empty the corpus. Are they drawn in the right places?
5. **Look for the next duplicated value.** Given the pattern above, assume there is one.

## 10. Running it

```bash
./scripts/bootstrap.sh              # venv, .env, schema, seeds, MCP registration, self-test
.venv/bin/pytest tests/             # what CI runs; tests/unit/ is 4 integration tests short
.venv/bin/pytest tests/unit/test_repo_conventions.py   # the language and vocabulary gates
python -m ignis.interfaces.cli.setup_bundle --json      # re-register MCP, rewrite configs
```

SQLite is the zero-config default and needs no Docker. `DATABASE_URL=postgresql://…` switches to
the Postgres/Timescale repository; `sql/001` enables the Timescale extension when present and
falls back to native Postgres indexes when not. The vocabulary seeds `sql/012`–`sql/014` are re-applied
on every SQLite bootstrap, because the domains they seed are system-owned and no tool writes
them; on Postgres they are run once by hand. `sql/015` adds a column instead of seeding rows, so
SQLite applies it through an `ALTER TABLE` in `_ensure_schema`.
