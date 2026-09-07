# fnIgnis 🔥 — Setup, Configuration & Manual Usage Guide (User Guide)

This document provides a comprehensive, step-by-step guide for developers, data analysts, and product strategists who wish to install, configure environment variables, and use `fn-ignis` manually without requiring an AI Agent.

---

## 📑 Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Manual Installation Modes](#2-manual-installation-modes)
   - [Mode 1: Zero-Docker Local Mode (SQLite)](#mode-1-zero-docker-local-mode-sqlite)
   - [Mode 2: Production Self-Hosted Stack (Docker Compose)](#mode-2-production-self-hosted-stack-docker-compose)
   - [Mode 3: Manual MCP Server Configuration for IDE / Desktop Apps](#mode-3-manual-mcp-server-configuration-for-ide--desktop-apps)
3. [Environment Variables & Configuration Reference](#3-environment-variables--configuration-reference)
4. [Manual Usage via Command Line (CLI)](#4-manual-usage-via-command-line-cli)
5. [Manual Usage via Python Scripting](#5-manual-usage-via-python-scripting)
6. [Report Management & Nginx Report Portal](#6-report-management--nginx-report-portal)
7. [Troubleshooting & Common Issues](#7-troubleshooting--common-issues)
8. [Catalog of 39 FastMCP Tools & Comprehensive Research Capabilities](#8-catalog-of-39-fastmcp-tools--comprehensive-research-capabilities)

---

## 1. Architecture Overview

`fn-ignis` is architected around a **Dual-Track Engine**:

```
                         ┌────────────────────────────────────────────────────────┐
                         │                     Data Ingress                       │
                         │   Google Trends • YouTube • TikTok • Threads • Reels   │
                         └───────────────────────────┬────────────────────────────┘
                                                     │
                                                     ▼
┌──────────────────────────────────────┐     ┌────────────────────────────────────┐
│ Track 1: Always-On Autonomous Radar  │     │ Track 2: On-Demand Deep Probes     │
│ - Continuous surveillance worker     │     │ - Triggered by user or agent       │
│ - Ingests hourly macro data          │     │ - Search suggestions, live grids   │
│ - Daily digests at 07:00 AM          │     │ - Raw comment & VoC extraction     │
└──────────────────┬───────────────────┘     └─────────────────┬──────────────────┘
                   │                                           │
                   └─────────────────────┬─────────────────────┘
                                         │
                                         ▼
                     ┌───────────────────────────────────────┐
                     │ Persistence: SQLite / PostgreSQL      │
                     │ Encryption: Fernet 256-bit (Tokens)   │
                     └───────────────────┬───────────────────┘
                                         │
                                         ▼
                     ┌───────────────────────────────────────┐
                     │ Strategic Reasoner & Opportunity Math │
                     │ Multi-Source Gap Analysis & Artifacts │
                     └───────────────────────────────────────┘
```

---

## 2. Manual Installation Modes

### Mode 1: Zero-Docker Local Mode (SQLite)

Ideal for quick evaluation, local research, and single-user workflows with zero infrastructure dependencies.

```bash
# 1. Clone repository
git clone https://github.com/fioenix/fn-ignis.git
cd fn-ignis

# 2. Run automated bootstrap
./scripts/bootstrap.sh
```

The bootstrap script will automatically:
- Create the Python virtual environment (`.venv`).
- Generate `.env` with SQLite defaults (`sqlite:///ignis.db`).
- Generate a persistent Fernet (AES-128-CBC + HMAC-SHA256, 256-bit key) encryption key.
- Initialize database schemas and load 84+ domain lexicons and noise filters.
- Register the FastMCP server in all supported agent environments.

To activate the environment manually:
```bash
source .venv/bin/activate
ignis --help
```

---

### Mode 2: Production Self-Hosted Stack (Docker Compose)

Designed for continuous 24/7 autonomous monitoring with PostgreSQL, Redis, and an automated Nginx reporting dashboard.

```bash
# 1. Prepare environment configuration
cp env.example .env
# Edit .env and configure DATABASE_URL, REDIS_URL, API keys, and credentials

# 2. Launch production containers
docker compose -f docker-compose.prod.yml up -d --build

# 3. Verify services
docker compose -f docker-compose.prod.yml ps
```

Services started:
- `fn-ignis-db`: PostgreSQL database.
- `fn-ignis-redis`: Redis message queue and caching.
- `fn-ignis-worker`: Always-On continuous radar ingestion daemon.
- `fn-ignis-nginx`: Static HTML report server on port 8080.

---

### Mode 3: Manual MCP Server Configuration for IDE / Desktop Apps

If you want to manually connect `fn-ignis` to your MCP client without using `bootstrap.sh`:

#### Claude Desktop (`~/Library/Application Support/Claude/claude_desktop_config.json`)
```json
{
  "mcpServers": {
    "fn-ignis": {
      "command": "/ABSOLUTE/PATH/TO/fn-ignis/.venv/bin/python",
      "args": ["-m", "ignis.interfaces.mcp.server"],
      "cwd": "/ABSOLUTE/PATH/TO/fn-ignis",
      "env": {
        "PYTHONPATH": "/ABSOLUTE/PATH/TO/fn-ignis/src"
      }
    }
  }
}
```

#### Google Antigravity / Claude Code (`.mcp.json` in workspace root)
```json
{
  "mcpServers": {
    "fn-ignis": {
      "command": ".venv/bin/python",
      "args": ["-m", "ignis.interfaces.mcp.server"],
      "env": {
        "PYTHONPATH": "src"
      }
    }
  }
}
```

---

## 3. Environment Variables & Configuration Reference

All settings can be placed in `.env` at the project root:

| Variable | Type | Default | Description |
|---|---|---|---|
| `DATABASE_URL` | String | `sqlite:///ignis.db` | Connection string (`sqlite:///...` or `postgresql://user:pass@host:5432/db`) |
| `IGNIS_ENCRYPTION_KEY` | String | Auto-generated | 32-byte url-safe Fernet key for encrypting social platform credentials |
| `YOUTUBE_API_KEY` | String | Optional | Official YouTube Data API v3 key |
| `TIKTOK_SESSION_ID` | String | Optional | TikTok session cookie for deep video & comment scraping |
| `THREADS_APP_ID` | String | Optional | Meta Developer App ID for official Threads Graph API |
| `THREADS_APP_SECRET`| String | Optional | Meta Developer App Secret |
| `INSTAGRAM_APP_ID` | String | Optional | Meta Developer App ID for Instagram Graph API |
| `INSTAGRAM_APP_SECRET`| String | Optional | Meta Developer App Secret |
| `IGNIS_ENVIRONMENT`| String | `development` | Runtime environment (`development`, `production`, `testing`) |
| `LOG_LEVEL` | String | `INFO` | Logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |

---

## 4. Manual Usage via Command Line (CLI)

`fn-ignis` provides a rich command-line interface:

```bash
# Execute macro ingestion radar across channels
ignis run-pipeline --geo VN --timeframe 7d

# Execute targeted research mission for a specific topic
ignis mission create --title "AI Customer Service Agents" --query "ai customer service" --geo VN
ignis mission ingress --id <mission_id>
ignis mission analyze --id <mission_id>
ignis mission export --id <mission_id> --output reports/

# System health diagnostics
ignis doctor
```

---

## 5. Manual Usage via Python Scripting

You can import `fn-ignis` services directly into custom scripts:

```python
import asyncio
from ignis.application.services.research_mission_service import ResearchMissionService
from ignis.infrastructure.persistence.sqlite_repository import SqliteRepository

async def main():
    repo = SqliteRepository("sqlite:///ignis.db")
    service = ResearchMissionService(repository=repo)
    
    # 1. Create strategic mission
    mission = await service.create_mission(
        title="B2B SaaS Automation in Vietnam",
        query="phan mem quan ly ban hang",
        geo="VN"
    )
    print(f"Created mission: {mission.id}")
    
    # 2. Execute ingress & strategic analysis
    await service.execute_ingress(mission.id)
    analysis = await service.analyze_mission(mission.id)
    print(f"Opportunity Index: {analysis.opportunity_index}")

if __name__ == "__main__":
    asyncio.run(main())
```

---

## 6. Report Management & Nginx Report Portal

When running in Docker mode, generated artifacts are saved in `reports/` and served via Nginx:
- Open `http://localhost:8080/` in your browser.
- Interactive dashboards display radar maturity, opportunity matrices, customer pain points, and full source citation pills.

---

## 7. Troubleshooting & Common Issues

### Issue 1: SQLite Database Locked
- **Cause**: Concurrent write access across multiple processes.
- **Fix**: Upgrade to PostgreSQL via Docker Compose or ensure single-process execution.

### Issue 2: PII Text Filter Triggered
- **Behavior**: Sensitive user info (emails, phone numbers, account tokens) is masked as `[REDACTED_PII]`.
- **Note**: This is an intentional security safeguard enforced at both ingress and presentation layers.

### Issue 3: Rate Limiting on Social Channels
- **Fix**: Add official API credentials (`YOUTUBE_API_KEY`, Meta Developer Apps) or use authenticated session cookies for TikTok.

---

## 8. Catalog of 39 FastMCP Tools & Comprehensive Research Capabilities

The `fn-ignis` FastMCP server exposes **39 atomic and strategic tools**:

### 1. Research Mission Orchestration & Analysis (8 Tools)
- `create_research_mission`: Initialize a new targeted research campaign.
- `execute_mission_ingress`: Deploy active multi-channel data harvesting.
- `get_mission_analysis`: Calculate Opportunity Index, Demand vs Supply matrix, and White Spaces.
- `generate_mission_artifact`: Render an interactive, standalone HTML Infographic Dashboard.
- `list_research_missions`: List all missions with filters for status, query, and date range.
- `get_current_session_mission`: Retrieve or auto-link active mission for current agent session.
- `run_autonomous_research_mission`: Execute complete 6-step campaign in a single automated step.
- `evaluate_mission_quality`: Audit data ingress health, signal coverage, and source diversity.

### 2. Macro Trend Surveillance & Exploration (4 Tools)
- `get_trending_topics`: Retrieve breakout topics scored by composite momentum.
- `get_topic_detail`: Retrieve deep multi-channel telemetry for a specific topic.
- `generate_trend_artifact`: Export interactive trend card artifact.
- `trigger_ingress_refresh`: Manually trigger macro pipeline scan.

### 3. TikTok Live Probes & Pain Point Mining (5 Tools)
- `get_tiktok_search_suggestions`: Query autocomplete suggestions for slang & long-tail intent.
- `get_tiktok_creative_center_trends`: Discover top surging hashtags and industry verticals.
- `get_tiktok_video_comments`: Scrape raw user comments for sentiment and objections.
- `extract_customer_pain_points`: Analyze friction, price resistance, and competitor shortcomings.
- `authenticate_tiktok`: Authenticate TikTok session credentials with Fernet encryption (AES-128-CBC + HMAC-SHA256).

### 4. Threads Social Listening & Graph API (5 Tools)
- `get_threads_trending_topics`: Extract trending public discussion topics.
- `get_threads_search_suggestions`: Uncover colloquial search intent and phrases.
- `authenticate_threads`: Complete OAuth 2.0 flow or set access tokens.
- `get_threads_auth_status`: Check health, expiration, and token validity.
- `clear_threads_auth`: Revoke and wipe stored Threads credentials.

### 5. Instagram Reels Intelligence (3 Tools)
- `authenticate_instagram`: Authenticate Instagram Graph API credentials.
- `get_instagram_auth_status`: Verify connection and token health.
- `clear_instagram_auth`: Revoke and wipe Instagram credentials.

### 6. Dynamic Configuration & System Health (6 Tools)
- `diagnose_system_health`: Full synthetic diagnostics of database, connectors, and encryption.
- `get_system_logs`: View recent application runtime logs.
- `get_platform_auth_status`: Unified status overview across all social platforms.
- `clear_platform_auth`: Generic credential reset tool.
- `get_runtime_config`: Inspect live operational thresholds and timeouts.
- `update_runtime_config`: Adjust thresholds (quality gate, limits, timeouts) dynamically without restart.

### 7. Domain Knowledge & Lexicon Governance (4 Tools)
- `register_domain_lexicon`: Register specialized vertical terminology dynamically.
- `register_noise_blacklist`: Register noise filters to exclude irrelevant signals.
- `list_domain_lexicons`: Inspect active lexicons and filters.
- `verify_connectors_health`: Health check across all external platform connectors.

### 8. Autonomous Discovery & Opportunity Hunting (4 Tools)
- `discover_market_opportunities`: Cross-source market gap discovery.
- `trigger_autonomous_discovery`: Trigger unguided exploration for whitespace opportunities.
- `get_latest_daily_discovery`: Inspect latest automated daily digest.
- `refresh_runtime_config_cache`: Invalidate and refresh in-memory runtime config cache.
