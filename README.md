# fn-ignis 🔥
**Unified Self-Hosted Autonomous Trend Intelligence & Market Opportunity Platform with FastMCP**

`fn-ignis` is a self-hosted market intelligence and trend analysis platform that empowers AI Agents (Claude Desktop, Claude Code, Antigravity, Codex) and human strategists to discover high-value market white spaces across Google Trends, YouTube, TikTok, Threads, and Instagram Reels with **$0 token ingress costs**, deterministic mathematical scoring (Opportunity Index), real-world Voice of Customer extraction, and pixel-perfect interactive HTML Dashboard artifacts.

---

## 🏛️ Dual-Track Architecture

`fn-ignis` operates on a dual-track architectural model that balances continuous passive surveillance with active, hypothesis-driven deep dives:

```mermaid
flowchart TD
    subgraph Track1["Track 1: ALWAYS-ON RADAR (Passive & Automated 24/7)"]
        W["fn-ignis Worker Daemon (Docker)"] -->|Every 15m| E1["Multi-Platform Ingress & Semantic Clustering"]
        W -->|Every 12h| E2["Autonomous Discovery: Creative Center + White Space Synthesis"]
        E1 & E2 --> DB[("Postgres / TimescaleDB (Data Baseline)")]
    end

    subgraph Track2["Track 2: ON-DEMAND DEEP RESEARCH (Targeted & Active Probes)"]
        User["User / Strategist"] <--> Claude["Claude Desktop / CLI (MCP)"]
        Claude -->|Step 1: Clarify & Formulate Hypothesis| S1["Scope & Core Questions"]
        Claude -->|Step 2-4: Active On-Demand Probes| S2["Search Suggestions, Video Grid & Comment Pain Points"]
        Claude -->|Step 5-6: Opportunity Matrix & Synthesis| S3["Opportunity Index, Moats & 3-7d MVP Blueprint"]
        S2 -->|Enrich & Write Back| DB
        Claude --> S4["Interactive Infographic HTML Dashboard"]
    end

    DB -.->|Provides Continuous Baseline| Claude
```

### 1. Track 1: Always-On Autonomous Radar (Continuous Surveillance)
- Runs 24/7 as a background container worker (`fn-ignis-worker`).
- Periodically ingests macro trends from Google Trends RSS and TikTok Creative Center.
- Performs zero-token semantic clustering and stores historical interest trajectories.
- Runs scheduled autonomous discovery cycles to generate persistent daily white space digests (`reports/daily_discovery_vn_YYYY-MM-DD.html`).

### 2. Track 2: On-Demand Targeted Deep Research (Active Strategic Probes)
- Interactively coordinates with AI Agents via FastMCP tools and prompts.
- Does not just consume cached data: **actively deploys targeted ingestion probes** for specific niche topics.
- Extracts authentic user search intent (Autocomplete suggestions) and customer objections (public comment scraping).
- Calculates the `Opportunity Index` (+100 to -100) and exports interactive HTML dossiers with actionable 3-7 day MVP validation roadmaps.

---

## 🧭 6-Step Standard Operating Procedure (SOP)

Every research mission follows a deterministic 6-step pipeline:

```
Step 1: Clarify Research Objectives & Core Hypothesis
   ↓
Step 2: Macro Scan & Real-World Keyword Expansion (Creative Center & Autocomplete Suggestions)
   ↓ (Feedback Loop: Expand scope with authentic user slang and sub-niches)
Step 3: Deep Multi-Platform Ingress & Quality Gate (Spam rejection, Confidence >= 70%)
   ↓
Step 4: Single-Source 4-Lens Breakdown (Demand, Supply, Intent, Voice of Customer)
   ↓
Step 5: Cross-Source Synthesis & Opportunity Index Matrix (Identify White Spaces)
   ↓
Step 6: Strategic Verdict, Entry Risks & Fast MVP Validation (3-7 day test plan + HTML Dashboard)
```

---

## 🛠️ FastMCP Tool & Prompt Catalog

### 1. Market Research & Strategic Execution
- `create_research_mission(title, keywords, geo, timeframe, hypothesis)`: Initialize a new targeted research campaign.
- `execute_mission_ingress(mission_id)`: Execute deep multi-platform ingestion for an existing mission.
- `get_mission_analysis(mission_id)`: Retrieve synthesized scorecard, white spaces, and action plans in token-optimized JSON.
- `generate_mission_artifact(mission_id)`: Export a standalone, pixel-perfect single-file HTML Dashboard report to `reports/`.
- `trigger_autonomous_discovery(geo)`: Trigger an on-demand end-to-end autonomous discovery cycle.
- `get_latest_daily_discovery(geo)`: Retrieve the latest automated daily discovery digest.

### 2. TikTok Radar & Voice of Customer
- `get_tiktok_creative_center_trends(geo, period, limit)`: Fetch official nationwide industry ranking benchmarks and hashtags.
- `get_tiktok_search_suggestions(keywords, geo)`: Fetch live autocomplete search queries and trending sub-hashtags.
- `get_tiktok_video_comments(video_url, limit)`: Scrape raw public comments for a specific video.
- `extract_customer_pain_points(keywords, geo, max_videos)`: Extract customer objections, pricing inquiries, and unmet needs.

### 3. General Intelligence & Diagnostics
- `get_current_session_mission(session_id)`: Restore active mission context for a chat thread.
- `list_research_missions(limit)`: List recent research missions.
- `get_trending_topics(geo, limit)`: Query top multi-platform topic clusters.
- `generate_trend_artifact(topic_id, geo)`: Render general trend overview dashboard.

### 4. Native Prompts & Resources
- **Prompts**: `market_research_pipeline`, `voice_of_customer_audit`.
- **Resources**: `fn-ignis://sop/market-research`, `fn-ignis://methodology/opportunity-index`.

---

## ⚡ 1-Click Installation & Setup

### 1. Automated Installation
Run the bundle installer from the repository root:
```bash
./bundle/install.sh
```
Or via Python CLI:
```bash
uv pip install -e .
uv run python -m ignis.interfaces.cli.setup_bundle
docker compose up -d --build
```

### 2. Claude Desktop Integration
The installer automatically configures `claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "fn-ignis": {
      "command": "/Users/fioenix/Projects/fn-ignis/.venv/bin/python",
      "args": ["-m", "ignis.interfaces.mcp.server"],
      "env": {
        "DATABASE_URL": "postgresql://postgres.xxx:yyy@aws-0-ap-southeast-1.pooler.supabase.com:5432/postgres",
        "DEFAULT_GEO": "VN",
        "YOUTUBE_API_KEY": "AIzaSy..."
      }
    }
  }
}
```

---

## 🧪 Testing

Run the full pytest suite (100% async coverage):
```bash
uv run pytest
```

---

## 📄 License
MIT License. Built for advanced autonomous market intelligence and white-space discovery.
