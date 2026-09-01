# fn-ignis Agent Operating Guidelines & Interface Protocol 🤖

This document defines the operational protocol, architectural guidelines, and tool selection principles for AI Agents (Claude Desktop, Claude Code, Antigravity, Cursor, Codex) interacting with `fn-ignis`.

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
