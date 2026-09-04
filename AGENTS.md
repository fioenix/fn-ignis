# fn-ignis Agent Operating Guidelines & Interface Protocol 🤖

This document defines the operational protocol, architectural guidelines, and tool selection principles for AI Agents (**Claude Desktop, Claude Code, Cursor, Windsurf, Antigravity, OpenAI Codex, OpenClaw, and Hermes**) interacting with `fn-ignis`.

---

## ⚡ 0. Zero-Touch Agent Bootstrap Protocol (Setup Tự Động)

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
> 4. Auto-configures FastMCP server in all detected agent environments (`claude_desktop_config.json`, `.cursor/mcp.json`, `.vscode/mcp.json`, Cline, Roo Code, `.mcp.json`).
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

## 🧭 2. Standard Operating Procedure (6-Step SOP)

When a user requests a market research, trend analysis, or white-space evaluation task, agents **MUST STRICTLY FOLLOW** this 6-step SOP:

### Step 1: Clarify Research Objectives & Formulate Core Hypothesis
- Clarify business model (SaaS, Retail, Agency, Content), target audience (B2B/B2C), geography, and timeframe.
- Establish a clear, falsifiable **Core Hypothesis** (e.g., *"Market demand for customer service AI agents is accelerating, but businesses are blocked by setup complexity and high monthly SaaS fees"*).
- **Autonomous Lexicon Registration**: If the target topic belongs to a specific vertical (e.g., Fashion, Crypto, Healthcare, Logistics), call `register_domain_lexicon(domain="...", terms=[...])` to ensure the Quality Gate recognizes niche vernacular dynamically.

### Step 2: Macro Scan & Real-World Keyword Expansion
- Call `get_tiktok_creative_center_trends(geo, period, limit, industry)` with vertical filter.
- Call `get_tiktok_search_suggestions` on seed keywords to capture authentic user slang, tool names, and sub-niches.
- *Feedback Loop*: Update research keywords and register newly discovered slang via `register_domain_lexicon` before deep crawling.

### Step 3: Deep Multi-Platform Ingress & Quality Gate
- Call `create_research_mission` and `execute_mission_ingress`.
- Verify the `QualityScorecard` (Coverage, Precision, Freshness, Diversity) has confidence $\ge 70\%$.

### Step 4: Single-Source 4-Lens Breakdown
- **Google Lens**: Macro search demand velocity and search volume growth.
- **YouTube Lens**: Long-form supply, case study and tutorial depth of competitors.
- **TikTok Search Lens**: Micro short-form intent and trending sub-hashtags.
- **Voice of Customer Lens**: Real objections, pricing questions, and unmet needs from comments via `extract_customer_pain_points`.

### Step 5: Cross-Source Synthesis & Opportunity Index Matrix
- Call `get_mission_analysis(mission_id)`.
- Correlate Demand vs. Supply, evaluate `Opportunity Index` (+100 to -100), identify `HIGH_DEMAND_LOW_SUPPLY` golden opportunities, and determine Trend Maturity Stage.

### Step 6: Strategic Verdict, Entry Risks & Fast MVP Validation
- Synthesize 3-5 grounded market truths (Key Takeaways).
- Evaluate entry barriers and competitive moats (Why hasn't this been built? What if big tech enters?).
- Formulate a 3-7 day fast low-cost MVP validation plan.
- Call `generate_mission_artifact(mission_id)` to render and export the interactive Infographic HTML Dashboard.

---

## 🎨 3. Presentation Standards

### Campaign Identification Banner
Always prefix analysis outputs with the campaign identification banner:

> **🎯 Campaign:** `[VN-AI-AGENT-90D]` — *AI Agents & Automation in Vietnam*  
> **Shortcode:** `VN-AI-AGENT-90D` *(or `fb16c5ee`)*  
> **Session ID:** `codex://threads/01a05666...` *(if available)*

### Native Artifacts First
- Render summaries, scorecards, white space matrices, and actionable roadmaps directly in the chat interface using high-contrast Light Mode markdown tables and cards.
- Export standalone HTML files to `reports/` via `generate_mission_artifact` for permanent local storage.

### 📊 Mandatory Data Ingress & Evidence Attribution Standards
Every strategic research analysis presented to the user **MUST STRICTLY INCLUDE**:
1. **Data Ingress & Channel Health Summary Table** placed right after the campaign banner:
   - Must disclose every platform checked (Google Trends, YouTube, TikTok Video Grid, TikTok Comments, Threads, Instagram Reels).
   - Must disclose signals count, status (`HEALTHY`, `EMPTY_NO_DATA`, `AUTH_REQUIRED`, `RATE_LIMITED`), and top citation reference.
   - If a channel captured 0 signals, explicitly state why so users know whether a channel was skipped/failed.
2. **Inline Evidence Citations**:
   - Every market truth, consumer friction, or strategic takeaway MUST cite concrete source evidence (e.g. `[YouTube: "Build AI Agent" (45K views)]`, `[TikTok Comments: 35/84 comments on @creator video]`, `[Google Trends: +180% velocity]`).
   - Strictly prohibit vague, unsupported statements without provenance attribution.

---

## 🏷️ 4. Release Versioning Principles & SemVer Guardrails

All agents (**Claude Desktop, Claude Code, Cursor, Windsurf, Antigravity, Codex, OpenClaw, Hermes**) must strictly adhere to **Semantic Versioning 2.0.0 (`MAJOR.MINOR.PATCH`)**:

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

## 🗑️ 5. Ephemeral Agent Handoff & Review Protocol (Giao Ban Tạm Thời)

> **MANDATORY RULE FOR TEMPORARY WORKING ARTIFACTS:**
> Any interim review notes, audit summaries, handoff memos, or scratchpads exchanged between AI agents (Claude Code, Antigravity, Cursor, Codex) **MUST be written exclusively into `.handoff/` (or named `*.handoff.md` / `*.ephemeral.md`)**.
>
> - **DO NOT** create temporary audit or review files directly inside `docs/` or project root.
> - `docs/` is reserved **strictly for permanent product documentation** (e.g. `USER_GUIDE.md`, architecture manuals).
> - `.handoff/` is 100% ignored by Git and will be purged periodically without affecting repository history.


