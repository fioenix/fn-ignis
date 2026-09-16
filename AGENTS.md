# fn-ignis Agent Operating Guidelines & Interface Protocol 🤖

This document defines the operational protocol, architectural guidelines, and tool selection principles for AI Agents (**Claude Desktop, Claude Code, Antigravity, OpenAI Codex, OpenClaw, Hermes, and Pi Agent**) interacting with `fn-ignis`.

---

## ⚡ 0. Zero-Touch Agent Bootstrap Protocol (Automated Setup)

> **MANDATORY INSTRUCTION FOR ALL AI AGENTS:**  
> When given this repository link (`https://github.com/fioenix/fn-ignis`) or instructed to set up `fn-ignis` for the user, execute this command immediately:
>
> ```bash
> ./scripts/bootstrap.sh
> ```
>
> **Autonomous Actions Performed:**
> 1. Provisions virtual environment (`.venv`) and installs `fn-ignis` in editable mode.
> 2. Creates `.env` with SQLite default (`DATABASE_URL=sqlite:///ignis.db`) and generates a persistent Fernet (256-bit key: AES-128-CBC + HMAC-SHA256) key.
> 3. Bootstraps SQLite database schemas and loads 84+ seed domain lexicons & noise filters.
> 4. Auto-configures FastMCP server in all supported agent environments (`.mcp.json`, `claude_desktop_config.json`, Google Antigravity, OpenAI Codex `config.toml`).
> 5. Runs synthetic diagnostics and outputs structured readiness confirmation.
>
> *No user input or external database installation is required.*

---

## 🏛️ 1. Architecture: The Dual-Track Model

Agents must understand the dual-track design of `fn-ignis`:

1. **Track 1: Always-On Autonomous Radar (Optional Continuous Baseline)**
   - Operated by the Docker daemon (`fn-ignis-worker`). **Optional** — every on-demand capability works without it.
   - Maintains baseline data through **official HTTP APIs only**: Google Trends RSS and the YouTube Data API.
   - The image carries no browser runtime on purpose (Playwright plus Chromium would take it from ~90MB to ~500MB, and an unattended scraper on a 15-minute loop is what gets an IP blocked). `build_connector_registry()` asks each connector for its `resolve_ingest_runtime()` and registers only the ones that can pull over HTTP; the rest are reported at startup and belong to Track 2, where Playwright runs on the operator's own machine with their own session.
   - A dual-tier connector crosses over on its own: Threads and Instagram Reels join the radar as soon as a Graph API token is configured, because that tier is plain HTTP.
   - **Do not tell an operator to obtain `threads_keyword_search`.** Meta grants it only through App Review, which a self-hosted install cannot be expected to pass, and until it is granted the endpoint answers HTTP 200 while searching the authenticated account's own posts only — an install that trusts it listens to itself. `authenticate_threads()` probes this and returns `keyword_search_access`; on `SELF_ONLY` or `NOT_PERMITTED`, direct the operator to `authenticate_threads(browser_login=True)` instead. The verdict is persisted rather than recomputed, and the routing reads it: a token known to search only its own posts loses to a browser session in `resolve_auth_tier()`, and when it is the last path left `search_signals()` refuses instead of returning the install's own timeline as market evidence. Accessibility is a design constraint of this project: no capability may require an approval process to be useful.
   - Generates automated daily discovery digests (`reports/daily_discovery_vn_YYYY-MM-DD.html`).
   - *Agent Action*: Query `get_latest_daily_discovery()` or `get_trending_topics()` to inspect current macro dynamics.

2. **Track 2: On-Demand Targeted Deep Research (Active Strategic Probes)**
   - Driven directly by the Agent upon user request.
   - Does not merely read existing baseline data: **deploys active on-demand probes** to pull live search suggestions, video grids, and raw customer comments for specific niche topics.
   - Enriches the shared database while generating comprehensive business viability dossiers.

---

## 🧭 2. Frameworks & Operational Modes

`fn-ignis` is a modular Agent Harness providing tools, mathematical methodologies, domain knowledge, and reporting scaffolds. The harness **does NOT enforce rigid workflows or dictate agent deliverables**. Agents have full autonomy to select operational modes based on user intent:

### A. Tactical & Ad-Hoc Probes (Fast & Unbundled Mode)
Agents can independently invoke any atomic FastMCP tool without initializing a research mission:
- **Instant Trend Spotting**: Call `get_threads_trending_topics` or `get_tiktok_creative_center_trends` to capture breakout daily topics.
- **Voice of Customer (VoC) Extraction**: Call `extract_customer_pain_points` or `get_tiktok_video_comments` to dissect customer objections, pricing inquiries, and unmet needs.
- **Keyword & Slang Expansion**: Call `get_tiktok_search_suggestions` or `get_threads_search_suggestions` to uncover colloquial phrasing and long-tail search intent.
- **Dynamic Configuration & Diagnostics**: Call `get_runtime_config`, `update_runtime_config`, `diagnose_system_health`.

Agents are free to synthesize and present responses as concise summaries, tables, or charts matching user conversational context.

### B. Strategic Research Reference Framework (6-Step Blueprint)
When users request a **comprehensive research campaign, market white-space analysis, or commercial viability dossier**, agents are recommended to follow the 6-Step analytical blueprint:

#### Step 1: Clarify Objectives & Establish Core Hypothesis
- Clarify business model (SaaS, Retail, Agency, Content), target audience (B2B/B2C), geography, and timeframe.
- Establish a falsifiable **Core Hypothesis** (e.g., *"Market demand for customer service AI agents is accelerating, but adoption is blocked by setup complexity and high SaaS fees"*).
- **Dynamic Lexicon Ingestion**: For specialized verticals, call `register_domain_lexicon(domain="...", terms=[...])` so the Quality Gate recognizes domain vernacular dynamically.

#### Step 2: Macro Scan & Real-World Keyword Expansion
- Call `get_tiktok_creative_center_trends` or `get_threads_trending_topics` to establish macro benchmarks.
- Call `get_tiktok_search_suggestions` and `get_threads_search_suggestions` on root keywords to discover authentic user slang, competitor tool names, and sub-niches.
- Register newly discovered terminology via `register_domain_lexicon` prior to deep crawling.

#### Step 3: Multi-Platform Ingestion & Quality Gate
- Call `create_research_mission` and `execute_mission_ingress`.
- Verify `QualityScorecard` (Coverage, Precision, Freshness, Creator Diversity) achieves Confidence Score $\ge 70\%$.

#### Step 4: Single-Source 4-Lens Breakdown
- **Google Lens**: Macro search demand velocity and search volume growth.
- **YouTube Lens**: Long-form supply depth, case studies, and tutorial maturity of competitors.
- **TikTok / Threads Lens**: Micro short-form intent, trending hashtags, and real-time public conversations.
- **Voice of Customer Lens**: Real purchase friction, pricing objections, and unmet needs via `extract_customer_pain_points`.

#### Step 5: Cross-Source Synthesis & Opportunity Index Matrix
- Call `get_mission_analysis(mission_id)`.
- Correlate Demand vs. Supply, calculate `Opportunity Index` (+100 to -100), identify `HIGH_DEMAND_LOW_SUPPLY` white spaces, and determine Trend Maturity Stage.

#### Step 6: Strategic Verdict, Entry Risks & Fast MVP Validation
- Synthesize 3-5 grounded market truths (Key Takeaways).
- Assess entry barriers and economic moats (Why hasn't the market solved this? What if Big Tech enters?).
- Formulate a 3-7 day fast low-cost MVP validation plan.
- Call `generate_mission_artifact(mission_id)` to render and export an interactive Infographic HTML Dashboard.

---

## 🎨 3. Presentation & Evidence Attribution Standards

### Campaign Identification Banner
When executing a formal Strategic Research Campaign, prefix the analysis with the campaign identifier banner:

> **🎯 Campaign:** `[VN-AI-AGENT-90D]` — *AI Agents & Automation in Vietnam*  
> **Shortcode:** `VN-AI-AGENT-90D` *(or `fb16c5ee`)*  
> **Session ID:** `codex://threads/01a05666...` *(if available)*

### Native Artifacts First
- Render summaries, scorecards, and white-space matrices directly inside the chat interface (using markdown tables and cards).
- Export standalone HTML files to `reports/` via `generate_mission_artifact` when the user requests a persistent local dossier.

### 🎨 FINOLABS Design System

Every HTML artifact renders in the FINOLABS design system. The tokens are vendored into
`src/ignis/infrastructure/templates/html/_fino_theme.html` from the "Finolabs Design System"
project on claude.ai/design (`theme.css`); update that partial when the source moves, and keep the
values byte-identical rather than eyeballing new ones.

Rules that apply to artifacts specifically:
- Artifacts are **product surfaces**: `<body class="product-mode">`, density and data-viz tokens,
  never the marketing register on the same page.
- **Type**: Anton for display caps, Space Grotesk for UI and body, JetBrains Mono for numbers and
  machine labels. Numbers use `font-variant-numeric: tabular-nums`.
- **Colour**: never hard-code hex. Chrome reads the role tokens (`--color-foreground`,
  `--color-border`), series read the data-viz slots (`--color-chart-1..12`), labels read the tag
  pairs. Mint is the everyday brand colour; violet is reserved for a single high-stakes accent.
- **No emoji.** `→ ↗ • — ◆ ◇` are the allowed glyphs; `→` is the canonical action glyph.
- **Radius** `--radius-lg` for cards, `--radius-full` for chips; shadows only `xs`, `md`, `xl`.
- Artifacts may fetch the FINOLABS webfonts, and nothing else external beyond the CDN libraries a
  template already declares. The trend graph renders its canvas and force layout inline so the
  export stays usable offline.

### 📊 Evidence Attribution Standards
When presenting strategic conclusions, agents must maintain evidentiary integrity:
1. **Data Ingress Summary Table**:
   - Explicitly list all probed channels (Google Trends, YouTube, TikTok Video, TikTok Comments, Threads, Instagram Reels).
   - Display signal counts and channel status (`HEALTHY`, `EMPTY_NO_DATA`, `AUTH_REQUIRED`, `RATE_LIMITED`, `DEGRADED`) from `channel_summaries` returned by `get_mission_analysis`.
2. **Inline Evidence Citations**:
   - Every market claim and friction point MUST be backed by concrete citations (e.g. `[YouTube: "Build AI Agent" (45K views)]`, `[TikTok Comments: 35/84 comments on @creator video]`, `[Google Trends: +180% velocity]`).
   - Disallow vague, unsourced generalizations without origin attribution.

### 🧾 Recommended Full Strategic Report Structure
When compiling a Comprehensive Strategic Dossier, the following standard structure is recommended:
1. **Campaign Identification Banner**
2. **Data Ingress Summary Table** (from `channel_summaries`)
3. **Quality Scorecard**
4. **Single-Source 4-Lens Breakdown** (with source citations)
5. **Market Opportunities & Demand vs. Supply Matrix** (with numeric evidence)
6. **Fast MVP Action Plan**

*(For ad-hoc queries, agents should adjust output format flexibly to match the user's specific conversational need).*

### 🌐 Language Boundary Protocol

The language of an artifact is decided by **where the artifact lives**, never by the language the user
is speaking in the current conversation. Agents reason internally in English.

| Artifact | Language | Notes |
|---|---|---|
| Chat responses to the user | User's language | The only place conversational language applies |
| `reports/`, `README.vi.md`, `docs/*.vi.md` | Target market language | Regional deliverables |
| HTML report copy rendered for a regional audience | Target market language | Template body text, not template identifiers |
| `src/**` — code, identifiers, docstrings, comments | **English** | No exceptions |
| `src/**` — log lines, exception messages, strings the code emits (`summary_text`, fallback names, status labels) | **English** | These are machine-facing output, not conversation |
| `tests/**` — docstrings, comments, assert messages, test names | **English** | A failing assertion is developer output |
| `tests/**` — fixture data (titles, comments, keywords under test) | Any language | Vietnamese fixtures are required to test Vietnamese behaviour |
| `sql/**` seeds, migration comments | **English** identifiers; vocabulary rows may be any language | The row *is* the data |
| Git commits, PR descriptions, branch names | **English**, imperative | `Add`, `Fix`, `Refactor`, `Update` |
| `AGENTS.md`, `CLAUDE.md`, skills, specs | **English** | Developer meta-guidance |

> **The trap this rule exists to close:** "match the user's language" applies to the conversation only.
> An assert message, a log line, or a string the engine returns is *not* a chat response, even when a
> Vietnamese user eventually reads it. When an agent is unsure which side a string falls on, it is English.

> **Diacritics:** never write Vietnamese without its diacritics as a compromise ("Chu de tong hop").
> That satisfies neither convention. Write correct English, or correct Vietnamese where Vietnamese belongs.

### 🗄️ Data-Driven Vocabulary Protocol

Domain knowledge belongs in the database, not in Python. The tables exist precisely so that vocabulary
can be extended at runtime without a release:

- `market_lexicons` — domain terms, slang, synonyms (grouped by `domain` + `category`), foreign stopwords, noise blacklist.
- `industry_taxonomies` — category keywords used to classify clusters.
- `runtime_configs` — thresholds and connector parameters.

**Do NOT** introduce a Python `list`/`dict`/`set` of domain terms, synonyms, brand names, intent
keywords, noise phrases, or category keywords inside `src/`. Seed them in `sql/` and read them through
the existing `register_*` / `get_domain_lexicons` / `get_industry_taxonomies` paths. If a new engine
needs vocabulary, it grows a `register_*` method and a sync call — it does not grow a constant.

Two narrow exceptions, both of which must carry an inline comment stating why:
1. **Locale-dependent selectors** that must match a third-party UI verbatim (`'button:has-text("Xem thêm")'`).
2. **Character-class regexes** used for script/language detection, where the characters *are* the algorithm.

A hardcoded vocabulary is a band-aid even when it makes a test pass: it ships domain knowledge that only
a code release can change, and it silently diverges from the database other components read.

**Store vocabulary in the language as it is written.** Vietnamese terms keep their tone marks, in
`market_lexicons` and `industry_taxonomies` alike. Stripping tones to "canonicalise" destroys the word:
`vàng` (gold) and `vang` (resonant) fold to one string, as do `tóc`/`tốc` and `chính phủ`/`chinh phục`.
That folding produced a run of wrong categories — a bolero playlist under finance, an esports bracket
under beauty — and four separate rules were added to compensate before the premise itself was accepted.
Lexicon terms are also handed to connectors as search queries, so a tone-stripped term asks the platform
a question no Vietnamese user would type. Matching folds only when the *input* carries no tones, which is
common and legitimate; the ambiguity then belongs to the input rather than to the system. Never fold both
sides by default, and never match a multi-word term as a raw substring — anchor on word boundaries, or
`ô tô` fires inside `cho tôi`.

---

### 🚦 Ingress Filtering Depends on Who Asked

Content filtering at ingress keys on the requester, not on the code path.

| Trigger | Path | Script-gated |
|---|---|---|
| `IngressTrigger.SCHEDULED` — unattended worker sweep | `fetch_from_all` | **Yes** |
| `IngressTrigger.REQUESTED` — `trigger_ingress_refresh` | `fetch_from_all` | No |
| Agent keyword probe — missions, discovery, refinement | `search_across_all` | No |

A scheduled sweep accumulates a corpus nobody reviews, so a title in a script the region does not use is
noise it carries forever. Anything a person or an agent asked for keeps what it found: social listening
means hearing what is actually said, and a market question can legitimately be answered in another
language. **Latin script always passes**, so the English that runs through Vietnamese social content is
never filtered — the gate only ever excludes Hangul, Cyrillic, Arabic, CJK, Thai and similar in a
Vietnam pass.

Relevance is never judged at ingress. `QualityEvaluator` holds the domain vocabulary and decides
relevance downstream, because judging it at ingress meant the radar could only ever store topics
somebody had already seeded — the opposite of a trend radar's job.

---

## 🏷️ 4. Release Versioning Principles & SemVer Guardrails

All agents (**Claude Desktop, Claude Code, Antigravity, OpenAI Codex, OpenClaw, Hermes, Pi Agent**) must strictly adhere to **Semantic Versioning 2.0.0 (`MAJOR.MINOR.PATCH`)**:

```
v MAJOR . MINOR . PATCH
    ↑       ↑       ↑
Breaking Feature   Bugfix / Optimization
```

### Version Bump Criteria

| Increment Level | When to Bump | Example Transition | Reset Rule |
|---|---|---|---|
| **`PATCH`** (`+0.0.1`) | Backward-compatible bug fixes, minor connector tweaks, test suite additions, documentation updates, or internal performance tuning. | `0.1.0` $\rightarrow$ `0.1.1` | None |
| **`MINOR`** (`+0.1.0`) | New platform connectors (e.g. Threads comments, Xiaohongshu), new FastMCP tools/prompts, new database migrations, or significant new analytical models. | `0.1.5` $\rightarrow$ `0.2.0` | `PATCH` resets to `0` |
| **`MAJOR`** (`+1.0.0`) | Breaking architectural overhauls, incompatible database schema drops, or breaking FastMCP tool signature deprecations. | `0.9.4` $\rightarrow$ `1.0.0` | `MINOR` & `PATCH` reset to `0` |

### ⛔ Strict Agent Guardrails

1. **NO Speculative or Arbitrary Bumps**: Do NOT bump version numbers for routine single-file bug fixes or daily development tasks. Versions are bumped **ONLY during formal release preparation** on `release/*` or `main`.
2. **NO Number Skipping**: Never jump versions arbitrarily (e.g. from `0.1.0` directly to `0.5.0` or `1.0.0`). Always increment by strictly `+1` at the appropriate level.
3. **Atomic Version Synchronization**: Six files carry the version string, not three. When a version bump is performed, the Agent **MUST update every one of them in a single atomic commit**, then tag:
   - [`pyproject.toml`](pyproject.toml) $\rightarrow$ `version = "X.Y.Z"`
   - [`openclaw.json`](openclaw.json) $\rightarrow$ `"version": "X.Y.Z"`
   - [`server.json`](server.json) $\rightarrow$ twice: the manifest version and the package version
   - [`CITATION.cff`](CITATION.cff) $\rightarrow$ `version: X.Y.Z` and `date-released`
   - [`.openclaw/config.yaml`](.openclaw/config.yaml) $\rightarrow$ `version: X.Y.Z`
   - [`BACKLOG.md`](BACKLOG.md) $\rightarrow$ the version banner
   - Git Tag on `main` $\rightarrow$ `vX.Y.Z`

   The identical list is enforced in Checklist C below. Do not reintroduce the obsolete three-file wording.
4. **Beta Phase Principle (`0.X.Y`)**: While in initial beta stages (`0.X.Y`), prioritize `PATCH` and `MINOR` increments. Do NOT rush to `1.0.0` until enterprise multi-tenancy and production stability milestones are reached.

---

## 🗑️ 5. Ephemeral Agent Handoff & Review Protocol

> **MANDATORY RULE FOR TEMPORARY WORKING ARTIFACTS:**
> Any interim review notes, audit summaries, handoff memos, or scratchpads exchanged between AI agents (Claude Code, Antigravity, OpenAI Codex) **MUST be written exclusively into `.handoff/` (or named `*.handoff.md` / `*.ephemeral.md`)**.
>
> - **DO NOT** create temporary audit or review files directly inside `docs/` or project root.
> - `docs/` is reserved **strictly for permanent product documentation** (e.g. `USER_GUIDE.md`, architecture manuals).
> - `.handoff/` is 100% ignored by Git and will be purged periodically without affecting repository history.

---

## 🛡️ 6. Pre-Flight & Operational Release Checklists

Every AI Agent modifying this repository or preparing a release must verify compliance against these three mandatory checklists:

### Checklist A: Open-Source Codebase & Documentation Standards
- [ ] **Global Codebase Convention**: All source code (`src/`), test suites (`tests/`), variable/function names, docstrings, inline comments, assert messages, log lines, and strings emitted by the code follow standard English (see the Language Boundary Protocol table in Section 3).
- [ ] **No Hardcoded Vocabulary**: No new domain terms, synonyms, intent keywords, noise phrases, or category keywords added as Python constants in `src/` (see the Data-Driven Vocabulary Protocol in Section 3).
- [ ] **Convention Gate**: `.venv/bin/pytest tests/unit/test_repo_conventions.py` passes.
- [ ] **Developer Meta-Guidance**: Core developer instructions (`AGENTS.md`, `CLAUDE.md`, skills) are maintained in English.
- [ ] **Git Commits & Branching**: 100% English imperative commit messages (e.g., `Add`, `Fix`, `Refactor`, `Update`).
- [ ] **Regional Documentation**: Dedicated localized documentation (such as `README.vi.md`) and market dossiers in `reports/` are accurately maintained for regional audiences.

### Checklist B: Harness Autonomy & Non-Prescriptive Decoupling
- [ ] **Non-Prescriptive Instructions**: Verify FastMCP server instructions and tool docstrings do NOT coerce agents into forced pipelines (no "MUST STRICTLY FOLLOW").
- [ ] **Atomic Independence**: Ensure all 39 FastMCP tools remain callable independently for ad-hoc tactical operations.
- [ ] **Framework Separation**: The 6-Step SOP is exposed as an analytical reference recipe (via resources/prompts), never as an unskippable constraint.
- [ ] **Contextual Deliverables**: Deliverables match user intent (concise text, cards, tables, or full HTML dashboards) without forcing boilerplate templates for trivial queries.

### Checklist C: Formal Release & Version Bump Gate
- [ ] **Automated Test Gate**: Run `.venv/bin/pytest tests/unit/` (or `uv run pytest`) with 100% pass rate before committing release changes.
- [ ] **Docs & Specs Sync**: Verify `docs/` (e.g., `USER_GUIDE.md`, architecture specs) and tool catalogs (`README.md`, `README.vi.md`) are fully updated with newly introduced tools, parameters, or schemas.
- [ ] **Clean Working Tree**: Verify no uncommitted scratchpads, no leaked credentials/`.env`, and no temporary audit notes placed in `docs/` (strictly `.handoff/`).
- [ ] **Branch Merge to Main**: Ensure the feature or maintenance branch is fully merged into `main` before tagging.
- [ ] **Packaging Verification**: Run distribution build check (`python -m build` or `uv build`) to verify clean package artifacts without missing assets.
- [ ] **Atomic Version Synchronization**: Six files carry the version string, not three. Update every one of them in a single atomic commit, then tag:
  - `pyproject.toml` (`version = "X.Y.Z"`)
  - `openclaw.json` (`"version": "X.Y.Z"`)
  - `server.json` (twice: the manifest version and the package version)
  - `CITATION.cff` (`version: X.Y.Z`)
  - `.openclaw/config.yaml` (`version: X.Y.Z`)
  - `BACKLOG.md` (the version banner)
  - Git Tag (`vX.Y.Z`) on `main`
  - Verify with `grep -rn "<previous version>" --include="*.toml" --include="*.json" --include="*.yaml" --include="*.cff" --include="*.md" .` returning nothing
- [ ] **Regenerate `uv.lock` in that same commit.** The lock records the project's own version,
  so bumping `pyproject.toml` without running `uv lock` makes `uv sync --locked` fail on a clean
  checkout and takes CI down with it. Run `uv lock`; never hand-edit the file. Confirm with
  `uv lock --check`.
- [ ] **GitHub Release Tagging**: Tag and push release commit (`git tag -a vX.Y.Z -m "Release vX.Y.Z" && git push origin vX.Y.Z`) and publish the GitHub Release note.
- [ ] **SemVer Guardrail**: Increment strictly by `+1` (`PATCH`, `MINOR`, `MAJOR`) according to Section 4 criteria. Never jump versions arbitrarily.




---

## 📁 7. Artifact Output vs. Committed Samples

- `reports/` is **local runtime output only** and is fully gitignored (except `.gitkeep`). Every artifact a tool generates at runtime lands here, and nothing in it is ever committed.
- `examples/case-studies/` holds the **curated sample dossiers** that documentation links to. `scripts/generate_sample_case_studies.py` writes there on purpose.
- HTML **templates** live in `src/ignis/infrastructure/templates/html/` and are the only report source committed as code.
