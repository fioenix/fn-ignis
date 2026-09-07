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
> 2. Creates `.env` with SQLite default (`DATABASE_URL=sqlite:///ignis.db`) and generates a persistent Fernet AES-256 key.
> 3. Bootstraps SQLite database schemas and loads 84+ seed domain lexicons & noise filters.
> 4. Auto-configures FastMCP server in all supported agent environments (`.mcp.json`, `claude_desktop_config.json`, Google Antigravity, OpenAI Codex `config.toml`).
> 5. Runs synthetic diagnostics and outputs structured readiness confirmation.
>
> *No user input or external database installation is required.*

---

## 🏛️ 1. Architecture: The Dual-Track Model

Agents must understand the dual-track design of `fn-ignis`:

1. **Track 1: Always-On Autonomous Radar (Continuous Surveillance)**
   - Operated by the Docker daemon (`fn-ignis-worker`).
   - Maintains continuous baseline data across Google Trends, YouTube, and TikTok.
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

### 🌐 Language & Localization Protocol
- **Internal Reasoning**: Agents may reason internally in English for speed and token precision.
- **Target Audience Alignment**: Deliverables presented to users (chat responses, roadmaps, and HTML reports in `reports/`) should strictly match the user's conversational language (e.g., Vietnamese when researching the Vietnam market or conversing in Vietnamese).
- **International Open-Source Standard**: Source code, docstrings, developer guides, and commit messages follow standard English conventions to ensure accessibility for global open-source contributors. Regional documentations (e.g., `README.vi.md`) are maintained alongside the canonical English docs.

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
3. **Atomic Triple Synchronization**: When a version bump is performed, the Agent **MUST synchronously update all 3 files in a single atomic commit**:
   - [`pyproject.toml`](pyproject.toml) $\rightarrow$ `version = "X.Y.Z"`
   - [`openclaw.json`](openclaw.json) $\rightarrow$ `"version": "X.Y.Z"`
   - Git Tag on `main` $\rightarrow$ `vX.Y.Z`
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
- [ ] **Global Codebase Convention**: All source code (`src/`), test suites (`tests/`), variable/function names, docstrings, and inline comments follow standard English for global open-source contributors.
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
- [ ] **Atomic Triple Synchronization**: Synchronously update version strings across all 3 files in a single atomic commit:
  - `pyproject.toml` (`version = "X.Y.Z"`)
  - `openclaw.json` (`"version": "X.Y.Z"`)
  - Git Tag (`vX.Y.Z`) on `main`
- [ ] **GitHub Release Tagging**: Tag and push release commit (`git tag -a vX.Y.Z -m "Release vX.Y.Z" && git push origin vX.Y.Z`) and publish the GitHub Release note.
- [ ] **SemVer Guardrail**: Increment strictly by `+1` (`PATCH`, `MINOR`, `MAJOR`) according to Section 4 criteria. Never jump versions arbitrarily.



