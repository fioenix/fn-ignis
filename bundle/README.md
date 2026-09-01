# fn-ignis Trend Intelligence & Market Opportunity Bundle 🚀

Autonomous Trend Intelligence & Market Opportunity (White Space) engine seamlessly integrated for **Claude Desktop (App)** and **Claude Code / Agent CLI**.

---

## ⚡ 1-Click Installation & Setup

Run a single command from the project root:
```bash
./bundle/install.sh
```
Or via Python CLI:
```bash
uv run python -m ignis.interfaces.cli.setup_bundle
```

---

## 🧭 6-Step Standard Operating Procedure (SOP)

The system executes market research through a deterministic 6-step pipeline:
1. **Step 1: Clarify Research Objectives & Formulate Core Hypothesis**: Establish business model (SaaS, Retail, Agency, Content), target audience (B2B/B2C), target geography, timeframe, and the key hypothesis to test.
2. **Step 2: Macro Scan & Real-World Keyword Expansion**: Use TikTok Creative Center & Autocomplete Search Suggestions to uncover real slang, tool names, and sub-niches before deep crawling.
3. **Step 3: Deep Multi-Platform Ingress & Quality Gate**: Ingest from Google Trends, YouTube, TikTok videos, and TikTok comments with automated spam/noise filtering (Confidence Scorecard $\ge 70\%$).
4. **Step 4: Single-Source 4-Lens Breakdown**: Evaluate Macro Search Demand, Long-form Tutorial Depth, Micro Search Intent, and Real Voice of Customer (Objections & Pain Points).
5. **Step 5: Cross-Source Synthesis & White Space Discovery**: Compute `Opportunity Index` (+100 to -100) to pinpoint `HIGH_DEMAND_LOW_SUPPLY` golden opportunities and determine Market Maturity Stage.
6. **Step 6: Strategic Verdict, Entry Risks & Fast MVP Validation**: Identify moats and technical barriers, formulate a 3-7 day low-cost MVP validation plan, and export an Infographic HTML Dashboard Artifact.

---

## 🛠️ FastMCP Tool Reference

### 1. Market Research & Workflow
- `create_research_mission(title, keywords, geo, timeframe, hypothesis)`: Initialize a new research campaign.
- `execute_mission_ingress(mission_id)`: Trigger deep multi-platform ingestion.
- `get_mission_analysis(mission_id)`: Retrieve full synthesized analysis in token-optimized JSON format.
- `generate_mission_artifact(mission_id)`: Render and export interactive Infographic HTML Dashboard report.
- `trigger_autonomous_discovery(geo)`: Trigger an on-demand end-to-end autonomous discovery cycle.
- `get_latest_daily_discovery(geo)`: Retrieve the latest daily automated market discovery digest and opportunity rankings.

### 2. Specialized TikTok Radar & Voice of Customer
- `get_tiktok_creative_center_trends(geo, period, limit)`: Industry ranking benchmarks and macro hashtags.
- `get_tiktok_search_suggestions(keywords, geo)`: Real-time user autocomplete search queries and trending sub-hashtags.
- `get_tiktok_video_comments(video_url, limit)`: Scrape raw public comments from a specific video.
- `extract_customer_pain_points(keywords, geo, max_videos)`: Extract customer objections, pricing questions, and unmet needs.

### 3. MCP Prompts & Resources
- **Prompts:** `market_research_pipeline`, `voice_of_customer_audit`.
- **Resources:** `fn-ignis://sop/market-research`, `fn-ignis://methodology/opportunity-index`.

