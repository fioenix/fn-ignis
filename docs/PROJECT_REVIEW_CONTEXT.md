# fn-ignis — Review Context

Written for an engineer or agent asked to review this project and recommend what to do next.
It states what the system is, what has actually been measured, what has not, and where the
reasoning is thin. It is in English because it describes `src/` and is read alongside
`AGENTS.md`; regional documentation lives in the `*.vi.md` files.

**Snapshot re-taken 10/09/2026 at 08:10 UTC, after the day's fixes landed.** Every figure below
was read from the running system at that moment, not from a changelog — corpus counts came from
the live Postgres, test counts from `pytest tests/`, CI status from `gh run list`. Re-read them
before relying on them; `git log docs/PROJECT_REVIEW_CONTEXT.md` shows when this file was last
brought up to date.

The day this snapshot covers was spent on repair, not features, and that shows in §8: four
defects in the setup and config path were found by writing tests for them rather than by using
the product. §4 now carries the first end-to-end product measurement the project has, and §7
records what the owner has decided since the previous snapshot.

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

**Convention, decided 10/09/2026: this repository does not use mermaid.** Diagrams are authored
as HTML, exported to SVG and PNG, and the image is what goes into a document. The reason is the
first failure mode in §8: a mermaid block was labelled as the source of a hand-authored SVG, the
two drifted, and the label was the thing that lied. Do not add mermaid blocks when recommending
changes here.

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

**Verified.** 573 tests pass; CI runs Ruff then `pytest tests/` then `uv build` then a
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
| Signals | 55 | 115 | 156 |
| tiktok | 0 `AUTH_REQUIRED` | 48 | 60 |
| threads | 0 `EMPTY_NO_DATA` | 10 | 39 |
| coverage | 40.0 | 100.0 | 100.0 |
| freshness | 100.0 | 90.4 | 77.6 |
| language precision | 34.5 | 40.9 | 38.5 |
| overall confidence | 67.0 `MEDIUM` | 80.7 `HIGH` | 75.5 `MEDIUM` |

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
   open product question, not a defect — see §9.

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

`BACKLOG.md` is the decision log, not a task list: 57 closed entries, each with the measurement
that settled it, and 22 open. Read the closed ones — several record a conclusion that was
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
3. **Whether to make the repository public.** Every blocker identified in the 09/09 readiness
   audit is closed and re-verified on 10/09: CI green, no `.env` or database file tracked, no
   full-length API key anywhere in `git rev-list --all` (the four commits still matching
   `AIzaSy` carry the placeholder `AIzaSy...`), and `LICENSE`, `CONTRIBUTING.md`,
   `CODE_OF_CONDUCT.md`, `SECURITY.md` and `.github/` all present with the version triple
   synchronised at 0.3.5. `gh repo view` still reports `PRIVATE`. Nothing is blocking the switch;
   nobody has thrown it. This is the project's longest-standing open item and it is a decision,
   not work.
4. **Git history.** A YouTube API key was committed in `.mcp.json` across 18 commits and has
   been rotated. History was rewritten on 09/09 and every ref force-pushed, but GitHub still
   serves unreachable objects by SHA until its own gc runs.
5. **Decided 10/09: three secrets that reached a session transcript will not be rotated.** A
   Supabase password, the Fernet key and a YouTube key appeared in plaintext in the 10/09
   transcript while diagnosing `~/.codex/config.toml`. Rotation was recommended and the owner
   declined, on the grounds that `ignis` is internal-only and the material is not sensitive
   enough to justify the cost — rotating `IGNIS_ENCRYPTION_KEY` in particular strands every
   credential already encrypted under it, requiring a fresh login on all three browser
   platforms. **Scope of that decision:** the transcript values only. Those secrets are absent
   from git history, verified across `git rev-list --all`. It would need revisiting if anyone
   outside the current users gains access, or if transcripts are shared. Recorded in
   `BACKLOG.md` as an open item so it stays visible rather than being treated as settled.
6. **The local config chores are done.** `./scripts/bootstrap.sh` was run on 10/09 and all four
   MCP configs now carry only `IGNIS_ENV_FILE`; `grep` for `AIzaSy`, `IGNIS_ENCRYPTION_KEY` and
   `DATABASE_URL` across `claude_desktop_config.json`, `~/.codex/config.toml`,
   `~/.gemini/config/mcp_config.json` and `.mcp.json` returns nothing. The previous snapshot
   listed a duplicate `fn-ignis` registration as the likely cause of `Connection closed`; there
   is one registration per client file, so that hypothesis was wrong and the cause is unknown.
   Claude Desktop and Cowork share `claude_desktop_config.json` — it carries
   `coworkUserFilesPath` alongside `mcpServers` — so registering once covers both.

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
YouTube key into the log — which on a public repository is world-readable. This was observed,
not theorised: a failing scheduler test in this session printed the live Supabase password.
`verify_connectors_health` independently echoed the full proxy URI, credentials included, into
tool output. Both are fixed; the general lesson is that a secret leaks through whatever generic
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

1. **Read `BACKLOG.md` closed entries first.** They carry the reasoning and the measurements;
   the code shows only the outcome.
2. **Question the Opportunity Index.** It compares demand velocity against localised supply
   volume on a corpus that is 93% one platform, most of that a timestamp artefact. Is the
   formula sound, and is the input good enough for it to mean anything yet? §4 gives the first
   real evidence to argue with: the same keyword moved from `+9.8` to `−62.0` purely because
   supply was being counted correctly, which says the formula responds to input quality exactly
   as designed and that every earlier reading was optimistic.
3. **Question whether freshness should penalise a larger corpus.** In §4, confidence fell from
   80.7 `HIGH` to 75.5 `MEDIUM` while signals rose 115 → 156, entirely because the added Threads
   signals were older. `SCORECARD_WEIGHT_FRESHNESS` is 0.30, the largest of the four weights. A
   reviewer should ask whether freshness belongs in a *confidence* score at all: it measures how
   recent the evidence is, not how much of it there is or how well it was verified. Recency may
   belong as a reported dimension rather than a term that can downgrade a wider corpus.
4. **Ask what the product question is.** Two days before this snapshot the work was foundation
   repair driven by a self-generated backlog, and the owner stopped it to ask whether any of it
   advanced the product. The honest answer was no. §4 exists because of that intervention. A
   reviewer is better placed than the codebase to say which of the 22 open items actually move a
   user decision and which are tidiness.
5. **Question the harness boundary.** The MCP layer is supposed not to dictate workflow
   (`CLAUDE.md` Checklist B), yet `run_autonomous_research_mission` and
   `trigger_autonomous_discovery` are end-to-end pipelines. Is that a contradiction worth
   resolving, or two legitimate levels of abstraction?
6. **Question the fail-open / fail-closed choices.** They are deliberate and inconsistent on
   purpose: the TikTok notification guard fails closed because it protects the operator's inbox;
   the clusterer, the probe templates and the language detector fail open with a warning because
   failing closed would empty the corpus. Are they drawn in the right places?
7. **Look for the next duplicated value.** Given the pattern above, assume there is one.

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
