---
name: fn-ignis-harness
description: Autonomous Trend Intelligence & Market Opportunity Agent Harness for deep multi-platform listening, white-space analysis, human-friendly mission tracking, and cross-agent session mapping.
---

# fn-ignis Trend Intelligence & Market Opportunity Agent Harness 🚀

This skill equips AI agents with an autonomous trend intelligence harness following the **6-Step Standard Operating Procedure (SOP)**:

---

## 🧭 Standard Operating Procedure (6-Step SOP)

### 1. Step 1: Clarify Research Objectives & Core Hypothesis
- Clarify business model (SaaS, Retail, Agency, Content), target audience (B2B/B2C), target geography (supports any ISO-3166 code e.g. `VN`, `US`, `JP`, `GB`, `DE`, `GLOBAL`), and timeframe.
- Establish the **Core Hypothesis** to validate (e.g., *"There is strong market demand for localized AI customer service agents, but existing solutions are overly complex and costly"*).
- **Dynamic Lexicon & Noise Customization**:
  - Call `register_domain_lexicon(domain="...", terms=[...])` so the Quality Gate recognizes domain terminology.
  - Call `register_noise_blacklist(terms=[...])` to eliminate topic-specific entertainment noise or irrelevant outliers dynamically.

### 2. Step 2: Macro Scan & Real-World Keyword Expansion
- Call `get_tiktok_creative_center_trends(geo, period, limit, industry)` with vertical filter.
- Call `get_tiktok_search_suggestions` to uncover actual industry rankings, slang, and authentic search queries.
- Expand keywords to include user colloquialisms, specific tool names, and sub-niches before deep ingestion.

### 3. Step 3: Deep Multi-Platform Ingress & Quality Gate
- Call `execute_mission_ingress` for deep multi-platform ingestion across registered connectors (Google Trends, YouTube, TikTok videos, TikTok comments, and extensible platforms like Reddit/Threads/Reels).
- Automated filters eliminate live streams, noise, and duplicate URLs. Evaluate `QualityScorecard` (Coverage, Precision, Freshness, Creator Diversity). Ensure Confidence Score $\ge 70\%$.

### 4. Step 4: Single-Source 4-Lens Breakdown
- **Google Lens:** Macro search demand velocity and search volume growth via localized multi-probing.
- **YouTube Lens:** Long-form supply, case study and tutorial depth of competitors.
- **TikTok Search Lens:** Micro short-form intent and trending sub-hashtags.
- **Voice of Customer Lens:** Authentic objections, pricing questions, unmet needs from comments via `extract_customer_pain_points(keywords, geo, inquiry_patterns=...)`.

### 5. Step 5: Cross-Source Synthesis & White Space Discovery
- Correlate Demand vs. Supply, compute `Opportunity Index` (+100 to -100), identify `HIGH_DEMAND_LOW_SUPPLY` golden opportunities, and determine Trend Maturity Stage (`EMERGING`, `GROWTH`, `SATURATED`).

### 6. Step 6: Strategic Verdict, Entry Risks & Fast MVP Validation
- Synthesize 3-5 grounded market truths (Key Takeaways).
- Evaluate entry barriers and competitive moats (Why hasn't this been built? What if big tech enters?).
- Formulate a 3-7 day fast low-cost MVP validation plan.
- Render and export the complete interactive Infographic HTML Dashboard (`generate_mission_artifact`).

---

## 🎨 Mandatory Presentation Guidelines

### 1. Research Campaign Identification Banner
When reporting mission status or analysis, **ALWAYS display the identification banner**:

> **🎯 Campaign:** `[VN-AI-AGENT-90D]` — *AI Agents & Automation in Vietnam*  
> **Shortcode:** `VN-AI-AGENT-90D` *(or `fb16c5ee`)*  
> **Session ID:** `codex://threads/01a05666...` *(if available)*

### 2. Artifact Presentation Protocol (Native Artifacts First) 🌟
- **DEFAULT IN-CHAT PRESENTATION:** Call `get_mission_analysis(mission_id)` and **render the findings directly as a Claude Native Artifact** in the chat window.
- **LOCAL FILE EXPORT:** Call `generate_mission_artifact` ONLY when the user explicitly asks to export or save a standalone HTML report file to local disk (`reports/` folder).

---

## 🛠️ FastMCP Tool Reference

1. **`get_current_session_mission(session_id)`**: Restore active mission linked to current chat thread.
2. **`create_research_mission(title, keywords, geo, timeframe, agent, session_id, platforms)`**: Initialize a targeted strategic research campaign.
3. **`get_tiktok_creative_center_trends(geo, period, limit, industry)`**: Scan macro industry trends and hashtag benchmarks (Step 2).
4. **`get_tiktok_search_suggestions(keywords, geo)`**: Fetch authentic user autocomplete search queries (Step 2).
5. **`execute_mission_ingress(mission_id)`**: Execute deep multi-platform ingestion with quality filtering (Step 3).
6. **`get_tiktok_video_comments(video_url, limit)`**: Read detailed public comments for a specific video (Step 4).
7. **`extract_customer_pain_points(keywords, geo, max_videos, inquiry_patterns)`**: Extract customer inquiries, pricing objections, and unmet needs across target geography (Step 4).
8. **`get_mission_analysis(mission_id)`**: Retrieve full cross-platform synthesized strategic analysis (Steps 5 & 6).
9. **`generate_mission_artifact(mission_id)`**: Export interactive Infographic HTML Dashboard report (Step 6).
10. **`trigger_autonomous_discovery(geo)`**: Trigger an on-demand full 6-step autonomous discovery cycle.
11. **`get_latest_daily_discovery(geo)`**: Retrieve the latest daily automated market discovery digest and opportunity rankings.
12. **`register_domain_lexicon(domain, terms, category)`**: Dynamically register new niche vocabulary/slang in database.
13. **`register_noise_blacklist(terms)`**: Dynamically register custom negative keywords to filter noise for specific research verticals.
14. **`list_domain_lexicons(domain)`**: Query active domain vocabularies and industry mappings.


