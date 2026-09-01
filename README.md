# fnIgnis 🔥 *(Code Name: fn-ignis)*

[![FINOLABS Project](https://img.shields.io/badge/FINOLABS-Open%20Source-orange.svg)](https://finolabs.io)
[![CI](https://github.com/fioenix/fn-ignis/actions/workflows/ci.yml/badge.svg)](https://github.com/fioenix/fn-ignis/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%20%7C%203.12-blue.svg)](https://www.python.org/downloads/)
[![MCP](https://img.shields.io/badge/MCP-Standard%20FastMCP-purple.svg)](https://modelcontextprotocol.io/)
[![Docker Ready](https://img.shields.io/badge/Docker-Worker%20Daemon-2496ED.svg)](https://www.docker.com/)

> **fnIgnis — Unified Self-Hosted Autonomous Trend Intelligence & Market Opportunity Platform by FINOLABS**

`fnIgnis` (`fn-ignis`) is a high-performance, self-hosted market listening and strategic research engine developed by **FINOLABS**. It empowers AI Agents (**Claude Desktop, Claude Code, Cursor, Windsurf, Antigravity, OpenAI Codex, OpenClaw, and Nous Hermes**) and human strategists to discover high-value market white spaces across Google Trends, YouTube, TikTok Creative Center, TikTok Search Suggestions, and raw Voice-of-Customer comments with **$0 token ingress costs**, deterministic mathematical scoring (**Opportunity Index**), autonomous lexicon expansion, and pixel-perfect interactive HTML Dashboard artifacts.


---

## 🌟 Key Highlights

- **⚡ Zero-Token Local Ingress**: Collects, filters, and normalizes high-volume signals locally using deterministic Python parsers without burning expensive LLM API tokens on raw scraping.
- **🏛️ Dual-Track Architecture**: Combines a continuous 24/7 background radar daemon (`fn-ignis-worker`) with interactive, hypothesis-driven strategic deep dives on-demand.
- **📊 Mathematical Opportunity Index**: Quantifies market white spaces (+100 to -100) by mathematically comparing macro search demand velocity against localized content supply volume.
- **🗣️ Voice of Customer Ingress**: Scrapes and synthesizes real customer pain points, pricing inquiries, and unmet objections directly from public video comment sections.
- **🧠 Autonomous Dynamic Lexicon Engine**: Persistent PostgreSQL registry allowing agents to dynamically register niche slang, brand names, and vernacular on-the-fly without modifying source code.
- **🤖 Universal Agent Ecosystem**: Native out-of-the-box support for Claude, Cursor, Windsurf, Antigravity, Codex, OpenClaw, and Hermes.

---

## 🏛️ Architecture: The Dual-Track Model

```mermaid
flowchart TD
    subgraph Track1["Track 1: ALWAYS-ON RADAR (Continuous Surveillance 24/7)"]
        W["fn-ignis Worker Daemon (Docker)"] -->|Every 15m| E1["Multi-Platform Ingress & Semantic Clustering"]
        W -->|Every 12h| E2["Autonomous Discovery: Creative Center + White Space Synthesis"]
        E1 & E2 --> DB[("PostgreSQL / TimescaleDB (Shared Baseline)")]
    end

    subgraph Track2["Track 2: ON-DEMAND DEEP RESEARCH (Active Strategic Probes)"]
        User["User / Strategist"] <--> Agent["AI Agent (Claude, Cursor, Codex, OpenClaw)"]
        Agent -->|Step 1: Clarify & Register Lexicon| S1["Scope, Hypothesis & Domain Vernacular"]
        Agent -->|Step 2-4: Deploy Active Probes| S2["Search Autocomplete, Video Grid & Comment Pain Points"]
        Agent -->|Step 5-6: Strategic Synthesis| S3["Opportunity Index, Moats & 3-7d MVP Plan"]
        S2 -->|Enrich & Write Back| DB
        Agent --> S4["Interactive Infographic HTML Dossier"]
    end

    DB -.->|Provides Continuous Historical Baseline| Agent
```

---

## 🧭 6-Step Standard Operating Procedure (SOP)

Every targeted research mission follows a deterministic 6-step workflow:

```
Step 1: Clarify Research Objectives & Core Hypothesis
   ↓ (Autonomous Lexicon Registration: Register vertical slang in DB)
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

## 🤖 Universal Multi-Agent Compatibility

`fn-ignis` is built from the ground up to integrate seamlessly with any modern AI agent orchestrator:

| AI Agent / Client | Configuration & Standards | Capabilities Supported |
|---|---|---|
| **Claude Desktop** | [`bundle/claude_desktop_config.json`](bundle/claude_desktop_config.json) | 15 FastMCP Tools, Prompts, Resources, Automatic SOP Injection |
| **Claude Code** | [`.agents/skills/fn-ignis-harness/SKILL.md`](.agents/skills/fn-ignis-harness/SKILL.md) | Agent Skills Standard, Native In-Chat Artifacts |
| **Cursor IDE** | [`.cursor/rules/fn-ignis.mdc`](.cursor/rules/fn-ignis.mdc), [`.cursorrules`](.cursorrules) | Context-Aware Multi-Platform Market Intelligence |
| **Windsurf IDE** | [`.windsurfrules`](.windsurfrules) | Cascade Step-by-Step Research Rule Protocol |
| **Antigravity / Gemini Code** | [`AGENTS.md`](AGENTS.md) + Agent Skills | Dual-Track Continuous Radar & Dynamic Lexicon Ingress |
| **OpenAI Codex** | [`.codex/instructions.md`](.codex/instructions.md), [`.codexrules`](.codexrules) | Thread Session Continuity (`codex://threads/...`), Structured Tools |
| **OpenClaw** | [`openclaw.json`](openclaw.json), [`.openclaw/config.yaml`](.openclaw/config.yaml) | OpenClaw Plugin v1 Schema with Lifecycle Hooks |
| **Nous Hermes** | [`.hermes/tools.json`](.hermes/tools.json), [`hermes_manifest.json`](hermes_manifest.json) | Native Structured Function-Calling JSON Schema |

---

## 🛠️ FastMCP Tool & Resource Catalog

### 1. Market Research & Strategic Synthesis
- **`create_research_mission(title, keywords, geo, timeframe, hypothesis)`**: Initialize a new targeted research campaign.
- **`execute_mission_ingress(mission_id)`**: Execute deep multi-platform data collection with automated quality gate evaluation.
- **`get_mission_analysis(mission_id)`**: Retrieve full synthesized strategic analysis (Opportunity Index, white spaces, action plan).
- **`generate_mission_artifact(mission_id)`**: Export a standalone, high-contrast interactive Infographic HTML Dashboard to `reports/`.
- **`trigger_autonomous_discovery(geo)`**: Trigger an on-demand full autonomous discovery cycle.
- **`get_latest_daily_discovery(geo)`**: Retrieve the latest automated daily discovery digest.

### 2. Social Listening & Voice of Customer
- **`get_tiktok_creative_center_trends(geo, period, limit, industry)`**: Fetch official nationwide industry ranking benchmarks with optional vertical filtering.
- **`get_tiktok_search_suggestions(keywords, geo)`**: Fetch live autocomplete search suggestions and trending hashtags.
- **`get_tiktok_video_comments(video_url, limit)`**: Scrape raw public comments for a specific video.
- **`extract_customer_pain_points(keywords, geo, max_videos)`**: Extract customer objections, pricing inquiries, and unmet needs from comments.

### 3. Dynamic Lexicon Registry
- **`register_domain_lexicon(domain, terms, category)`**: Dynamically register new niche vocabulary/slang into PostgreSQL.
- **`list_domain_lexicons(domain)`**: Query active domain vocabularies and industry mappings.

### 4. FastMCP Native Resources & Prompts
- **Resources**: `fn-ignis://sop/market-research`, `fn-ignis://methodology/opportunity-index`
- **Prompts**: `market_research_pipeline`, `voice_of_customer_audit`

---

## ⚡ Quickstart & Installation

### Prerequisites
- **Python 3.11+** or [`uv`](https://github.com/astral-sh/uv)
- **Docker & Docker Compose** (for PostgreSQL/TimescaleDB and background worker)
- **Google Cloud YouTube Data API Key** (Free tier)

### 1. 1-Command Automated Bundle Setup
Clone the repository and run the automated installer:
```bash
git clone https://github.com/fioenix/fn-ignis.git
cd fn-ignis

# Run bundle installer (Sets up venv, installs dependencies, configures Claude Desktop & starts Docker worker)
./bundle/install.sh
```

### 2. Manual Setup
```bash
# 1. Create and activate virtual environment
uv venv .venv
source .venv/bin/activate

# 2. Install dependencies with all extras
uv pip install -e ".[dev,browser,ai]"

# 3. Configure environment
cp .env.example .env
# Edit .env with your PostgreSQL credentials and YouTube API Key

# 4. Start Docker background infrastructure
docker compose up -d --build
```

---

## ⚙️ Environment Variables

| Variable | Description | Default | Required |
|---|---|---|:---:|
| `DATABASE_URL` | PostgreSQL/TimescaleDB connection string | `postgresql://postgres:postgres@localhost:5432/ignis_trends` | **Yes** |
| `YOUTUBE_API_KEY` | Google Cloud YouTube Data API v3 Key | `""` | **Yes** |
| `DEFAULT_GEO` | Default ISO country code for trend intelligence | `VN` | No |
| `SYNC_INTERVAL_MINUTES` | Frequency of background multi-platform synchronization | `60` | No |
| `IGNIS_ENCRYPTION_KEY` | AES-256 Fernet key for session cookie encryption | *(Auto-generated)* | No |

---

## 🧪 Verification & Testing

Run the test suite with 100% async coverage:
```bash
uv run pytest
```

---

## 🛡️ Security & Privacy

- **Zero Data Leakage**: Raw scraping data is parsed and evaluated locally. No third-party LLM sees raw proprietary inputs unless explicitly directed by the agent.
- **AES-256 Encryption**: Browser session states and credentials are encrypted at rest using AES-256-GCM / Fernet.
- **Parameterized SQL**: All database operations use strict parameterized queries (`%s`) to prevent SQL injection.
- For vulnerability reports, please consult our [Security Policy](SECURITY.md).

---

## 🤝 Contributing

Contributions from the open-source community are welcome! Please review our [Contributing Guidelines](CONTRIBUTING.md) and [Code of Conduct](CODE_OF_CONDUCT.md) before submitting pull requests.

---

## 📄 License

Distributed under the **MIT License**. See [`LICENSE`](LICENSE) for more information.
