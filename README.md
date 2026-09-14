# fnIgnis 🔥 *(Code Name: fn-ignis)*

[![FINOLABS Project](https://img.shields.io/badge/FINOLABS-Open%20Source-orange.svg)](https://finolabs.io)
[![CI](https://github.com/fioenix/fn-ignis/actions/workflows/ci.yml/badge.svg)](https://github.com/fioenix/fn-ignis/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%20%7C%203.12-blue.svg)](https://www.python.org/downloads/)
[![MCP](https://img.shields.io/badge/MCP-Standard%20FastMCP-purple.svg)](https://modelcontextprotocol.io/)
[![Docker Ready](https://img.shields.io/badge/Docker-Worker%20Daemon-2496ED.svg)](https://www.docker.com/)

> **fnIgnis — Unified Self-Hosted Autonomous Trend Intelligence & Market Opportunity Platform by FINOLABS**
>
> 🌐 [Tiếng Việt](README.vi.md) · [Comprehensive User Guide](docs/USER_GUIDE.md)

`fnIgnis` (`fn-ignis`) is a high-performance, self-hosted market listening and strategic research engine developed by **FINOLABS**. It empowers AI Agents (**Claude Desktop, Claude Code, Antigravity, OpenAI Codex, OpenClaw, Hermes, and Pi Agent**) and human strategists to discover high-value market white spaces across Google Trends, YouTube, TikTok Creative Center, TikTok Search Suggestions, and raw Voice-of-Customer comments with **$0 token ingress costs**, deterministic mathematical scoring (**Opportunity Index**), autonomous lexicon expansion, and pixel-perfect interactive HTML Dashboard artifacts.


---

## 🌟 Key Highlights

- **⚡ Zero-Token Local Ingress**: Collects, filters, and normalizes high-volume signals locally using deterministic Python parsers without burning expensive LLM API tokens on raw scraping.
- **🏛️ Dual-Track Architecture**: Combines an optional 24/7 background radar daemon (`fn-ignis-worker`, official HTTP APIs only) with interactive, hypothesis-driven strategic deep dives on-demand. Browser-driven channels run in the on-demand track, on your own machine with your own session — the worker image stays lean and needs no Chromium.
- **📊 Mathematical Opportunity Index**: Quantifies market white spaces (+100 to -100) by mathematically comparing macro search demand velocity against localized content supply volume.
- **🧾 Lossless Evidence Ledger**: Stores one canonical external source, every immutable collection
  observation, and the exact mission evidence that used it. Repeated polling cannot inflate source
  diversity, and one source can support multiple missions and clusters without being copied.
- **🗣️ Voice of Customer Ingress**: Scrapes and synthesizes real customer pain points, pricing inquiries, and unmet objections directly from public video comment sections.
- **🧠 Autonomous Dynamic Lexicon Engine**: Persistent PostgreSQL registry allowing agents to dynamically register niche slang, brand names, and vernacular on-the-fly without modifying source code.
- **🤖 Universal Agent Ecosystem**: Native out-of-the-box support for Claude (Desktop & Code), Antigravity, Codex, OpenClaw, Hermes, and Pi Agent.

---

## 🏛️ Architecture: The Dual-Track Model

<p align="center">
  <img src="docs/assets/architecture.png" alt="fn-ignis Dual-Track Architecture" width="100%">
</p>

Runtime persistence has one source of truth on both backends:

| Entity | Owns |
|---|---|
| `sources` | External object identity: exactly `id`, `platform`, `external_id` |
| `observations` | One collection event: title, URL, metrics, metadata, cluster membership, identity route, and clock provenance |
| `mission_evidence` | The exact observations used by each research mission |

`trend_signals` and `signal_metrics` are legacy migration inputs only. Runtime never writes them.
The one runtime read left is the cluster pruner's guard: a cluster the legacy corpus still points at
is not empty, so deleting it before the backfill would cascade away the rows the backfill was going
to read.
<p align="center">
  <small><em>Figure: The Dual-Track Autonomous Trend Intelligence Architecture (<a href="docs/assets/architecture.svg">Vector SVG</a> · <a href="docs/assets/architecture.html">Standalone HTML</a>)</em></small>
</p>

---

## 🧭 6-Step Standard Operating Procedure (SOP)

For comprehensive research missions, the following six steps are a reference workflow. Every
FastMCP tool remains independently callable; the harness does not force this sequence for ad-hoc
questions.

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
| **Claude Desktop** | [`bundle/claude_desktop_config.json`](bundle/claude_desktop_config.json) | 39 FastMCP Tools & Handlers, Prompts, Resources, Automatic SOP Injection |
| **Claude Code** | [`.agents/skills/fn-ignis-harness/SKILL.md`](.agents/skills/fn-ignis-harness/SKILL.md) | Agent Skills Standard, Native In-Chat Artifacts |
| **Antigravity / Gemini Code** | [`AGENTS.md`](AGENTS.md) + Agent Skills | Dual-Track Continuous Radar & Dynamic Lexicon Ingress |
| **OpenAI Codex** | [`.codex/instructions.md`](.codex/instructions.md), [`.codexrules`](.codexrules) | Thread Session Continuity (`codex://threads/...`), Structured Tools |
| **OpenClaw** | [`openclaw.json`](openclaw.json), [`.openclaw/config.yaml`](.openclaw/config.yaml) | OpenClaw Plugin v1 Schema with Lifecycle Hooks |
| **Nous Hermes** | [`.hermes/tools.json`](.hermes/tools.json), [`hermes_manifest.json`](hermes_manifest.json) | Native Structured Function-Calling JSON Schema |
| **Pi Agent** | [`openclaw.json`](openclaw.json), [`hermes_manifest.json`](hermes_manifest.json) | OpenAPI & Tool-Calling Standard via FastMCP or Manifest |

<!-- mcp-name: io.github.fioenix/fn-ignis -->

---

## 📡 Data Sources & Connected Tools Matrix

| Data Source | Signals Captured | Ingress Mechanism | Connected FastMCP Tools |
| :--- | :--- | :--- | :--- |
| **Meta Threads** | • Trending Topics on `threads.net/search`<br>• Autocomplete search suggestions<br>• Text posts, captions & authors<br>• Engagement metrics (likes, replies, reposts, quotes, views) | • **Tier 1 (Default)**: Direct GraphQL via `httpx` with session cookies + Playwright fallback with auto doc_id sniffing<br>• **Tier 2**: Graph API OAuth 2.0 (`/keyword_search`, `/me/threads`) | • `authenticate_threads`<br>• `get_threads_auth_status`<br>• `clear_threads_auth`<br>• `get_threads_trending_topics`<br>• `get_threads_search_suggestions` |
| **TikTok** | • Macro industry rankings (Creative Center)<br>• Search autocomplete suggestions<br>• Video cards (views, likes, shares, hashtags)<br>• Public video comments & feedback | • **Tier 1**: Playwright Chromium (1-click QR session capture)<br>• **Public Probe**: Creative Center API & search endpoints | • `authenticate_tiktok`<br>• `get_platform_auth_status`<br>• `clear_platform_auth`<br>• `get_tiktok_creative_center_trends`<br>• `get_tiktok_search_suggestions`<br>• `get_tiktok_video_comments`<br>• `extract_customer_pain_points` |
| **YouTube** | • In-depth long-form videos (tutorials, case studies)<br>• Competitor supply volume & tutorial depth<br>• Views, likes, and comment counts | • **Official API v3**: Google Cloud API Key with in-memory TTL caching | Triggered in research missions: `create_research_mission`, `execute_mission_ingress`, `trigger_autonomous_discovery` |
| **Google Trends** | • Macro search volume velocity<br>• Breakout rising queries & geographic interest | • **RSS / Atom Ingress**: Zero-token public feed parsing | Triggered in ingress cycles: `trigger_ingress_refresh`, `trigger_autonomous_discovery`, `execute_mission_ingress` |
| **Meta Instagram** | • Short-form Reels (captions, audio, hashtags)<br>• Views, likes, published timestamps | • **Tier 1**: Playwright Chromium session capture<br>• **Tier 2**: Instagram Graph API OAuth 2.0 | • `authenticate_instagram`<br>• `get_instagram_auth_status`<br>• `clear_instagram_auth` |

---

## 🛠️ FastMCP Tool & Resource Catalog (39 Tools)

### 1. Market Research & Strategic Synthesis
- **`run_autonomous_research_mission(topic, keywords, geo, timeframe, min_signals)`**: End-to-end mission creation, multi-platform refinement loop, and white space synthesis.
- **`create_research_mission(title, keywords, geo, timeframe, hypothesis)`**: Initialize a new targeted research campaign.
- **`execute_mission_ingress(mission_id)`**: Execute deep multi-platform data collection with automated quality gate evaluation.
- **`evaluate_mission_quality(mission_id)`**: Re-evaluate multi-dimensional quality scorecard.
- **`discover_market_opportunities(mission_id)`**: Discover unserved content and product white spaces.
- **`get_mission_analysis(mission_id)`**: Retrieve full synthesized strategic analysis (Opportunity Index, white spaces, action plan).
- **`generate_mission_artifact(mission_id)`**: Export a standalone, high-contrast interactive Infographic HTML Dashboard to `reports/`.
- **`list_research_missions(limit)`**: List all historical research campaigns.
- **`get_current_session_mission(session_id)`**: Restore active mission linked to current chat thread.
- **`trigger_autonomous_discovery(geo)`**: Trigger an on-demand full autonomous discovery cycle.
- **`get_latest_daily_discovery(geo)`**: Retrieve the latest automated daily discovery digest.

### 2. Social Listening, Threads & Voice of Customer
- **`get_threads_trending_topics(geo, limit)`**: Fetch real-time Trending Topics from Threads search surface (`threads.net/search`).
- **`get_threads_search_suggestions(keyword, geo, limit)`**: Fetch search autocomplete suggestions and derivative queries from Threads search.
- **`get_tiktok_creative_center_trends(geo, period, limit, industry)`**: Fetch official nationwide industry ranking benchmarks with optional vertical filtering.
- **`get_tiktok_search_suggestions(keywords, geo)`**: Fetch live autocomplete search suggestions and trending hashtags.
- **`get_tiktok_video_comments(video_url, limit)`**: Scrape raw public comments for a specific video.
- **`extract_customer_pain_points(keywords, geo, max_videos, inquiry_patterns)`**: Extract customer objections, pricing inquiries, and unmet needs from comments.

### 3. Dynamic Lexicon, Runtime Config & Infrastructure Diagnostics
- **`get_runtime_config(key, category)`**: Inspect dynamic runtime parameters (`threads_web_client_id`, `threads_graphql_endpoint`, `doc_id`) from DB and RAM cache.
- **`update_runtime_config(key, value, category, description)`**: Allow AI Agents to dynamically update protocol parameters when web clients rotate builds.
- **`refresh_runtime_config_cache()`**: Force invalidate and reload all dynamic runtime configurations from database into active memory cache (~0.01ms).
- **`register_domain_lexicon(domain, terms, category)`**: Dynamically register new niche vocabulary/slang into database.
- **`register_noise_blacklist(terms)`**: Register unwanted viral spam words into the blacklist.
- **`list_domain_lexicons(domain)`**: Query active domain vocabularies and industry mappings.
- **`diagnose_system_health()`**: Query full platform telemetry, circuit breakers, and component status.
- **`get_system_logs(limit, level)`**: Inspect audit event trails.
- **`verify_connectors_health()`**: Run real-time synthetic diagnostics on YouTube quota, Google RSS, TikTok Playwright contexts, database pool, and proxy connectivity.
- **`authenticate_tiktok()`**, **`get_platform_auth_status()`**, **`clear_platform_auth()`**: Managed browser credential lifecycle.
- **`authenticate_threads(auth_code?, client_id?, client_secret?, redirect_uri?, browser_login?)`**: Dual-UX Meta connect (Tier 1 browser session or Tier 2 Graph API OAuth 2.0).
- **`get_threads_auth_status()`**, **`clear_threads_auth()`**: Inspect or revoke Threads credentials and browser sessions.
- **`authenticate_instagram(auth_code?, client_id?, client_secret?, redirect_uri?, browser_login?)`**, **`get_instagram_auth_status()`**, **`clear_instagram_auth()`**: Managed Instagram credentials lifecycle.
- **`get_trending_topics(geo, timeframe, limit)`**, **`get_topic_detail(topic_id)`**, **`generate_trend_artifact(topic_id, geo, format)`**, **`trigger_ingress_refresh(geo, scope)`**: Real-time trend exploration.

### 4. FastMCP Native Resources & Prompts
- **Resources**: `fn-ignis://sop/market-research`, `fn-ignis://methodology/opportunity-index`
- **Prompts**: `market_research_pipeline`, `voice_of_customer_audit`

> [!NOTE]
> **Localization Transparency:** Multi-region linguistic verification (`ILanguageDetector`) is natively supported across VN, US, JP, KR, TH, and BR with subtractive filtering and dynamic domain lexicons.


---

## 📊 Live Reference Case Studies

Explore sample interactive Infographic HTML reports generated directly by `fn-ignis` in [`examples/case-studies/`](examples/case-studies/) — runtime output goes to the local, untracked `reports/` directory instead:

| Campaign / Dossier | Scope & Focus | Highlights & White Spaces Discovered | Live Artifact |
|---|---|---|:---:|
| **`[VN-AI-AGENT-90D]`** | AI Agents & CSKH Automation in Vietnam | High demand for customer service bots; massive white space in enterprise custom integration vs saturated shallow tutorial content. | [View HTML Dossier](examples/case-studies/case_study_ai_agents_vn.html) |
| **`[VN-LINEN-FASHION-30D]`** | Apparel, Linen & Local Brands | Skyrocketing seasonal search intent for minimal office linen apparel; major supply gaps in oversized tailored linen shirts. | [View HTML Dossier](examples/case-studies/case_study_linen_fashion_vn.html) |
| **`[VN-TIKTOK-SHOP-30D]`** | TikTok Shop Tools & Livestream Automation | Strong merchant demand for automated order closing and live stream inventory sync; high voice-of-customer pricing objection density. | [View HTML Dossier](examples/case-studies/case_study_tiktok_shop_automation_vn.html) |

---

## ⚡ Quickstart & Installation

### 🤖 1. Zero-Touch AI Agent Bootstrap (Recommended)
If you are an AI Agent (**Claude Code, Antigravity, OpenAI Codex, OpenClaw, Hermes, Pi Agent**) or setting up locally with 1 command:
```bash
git clone https://github.com/fioenix/fn-ignis.git && cd fn-ignis
./scripts/bootstrap.sh
```
*Automatically sets up Python virtualenv, SQLite database, generates `.env` with encryption keys, registers FastMCP for Claude Desktop, Antigravity, Codex, and verifies all connectors.*

---

### 2. Manual Zero-Docker Local Mode (SQLite)
Run `fn-ignis` with **zero external dependencies** using Python standard library SQLite:
```bash
# 1. Clone repository & initialize virtual environment
git clone https://github.com/fioenix/fn-ignis.git && cd fn-ignis
uv venv && source .venv/bin/activate && uv sync --locked --inexact

# 2. Run FastMCP server directly (Zero-Docker / SQLite auto-provisioned)
ignis-mcp
```

### 3. 1-Click Production Stack (Docker Compose)
Deploy the full enterprise self-hosted stack (TimescaleDB + Autonomous Worker Daemon + Nginx Report Portal):
```bash
# Spin up complete production stack
docker compose -f docker-compose.prod.yml up -d
```

> Existing PostgreSQL installations with a legacy `trend_signals` corpus require the reviewed
> [source/observation production cutover](docs/migrations/2026-09-10-source-observation-baseline.md#production-cutover-runbook).
> Do not start the new runtime after applying `sql/016` until the snapshot-specific baseline,
> backfill, and verifier have returned `VERIFIED`.


---

## 📖 Comprehensive Documentation & User Guide

For detailed manual installation, Python scripting workflows, Docker ops, and troubleshooting, consult the **[Manual User Guide](docs/USER_GUIDE.md)**.

---

## ⚙️ Environment Variables

| Variable | Description | Default | Required |
|---|---|---|:---:|
| `DATABASE_URL` | SQLite (`sqlite:///ignis.db`) or PostgreSQL/TimescaleDB connection string | `sqlite:///ignis.db` | **Yes** |
| `YOUTUBE_API_KEY` | Google Cloud YouTube Data API v3 Key | `""` | Optional |
| `DEFAULT_GEO` | Default ISO country code for trend intelligence | `VN` | No |
| `SCHEDULER_INTERVAL_SECONDS` | Worker ingress tick. The default is derived from YouTube's quota: 10 keyword probes x 100 units leaves room for 10 passes a day | `8640` (~2.4h) | No |
| `DISCOVERY_INTERVAL_HOURS` | Interval between autonomous discovery runs | `24` (daily) | No |
| `SYNC_INTERVAL_MINUTES` | Optional override for ingress sync interval in minutes (0 = use SCHEDULER_INTERVAL_SECONDS) | `0` | No |
| `YOUTUBE_CACHE_TTL_SECONDS` | In-memory LRU+TTL cache duration to preserve YouTube API quota | `86400` (24h) | No |
| `PLAYWRIGHT_PROXY_SERVER` | Optional HTTP/SOCKS proxy server URI for residential scraping | `""` | No |
| `IGNIS_ENCRYPTION_KEY` | Fernet (256-bit key: AES-128-CBC + HMAC-SHA256) for session cookie encryption | *(Auto-generated)* | No |

---

## 🧪 Verification & Testing

Run the test suite with 100% async coverage:
```bash
uv run pytest
```

---

## 🛡️ Security & Privacy

- **Zero Data Leakage**: Raw scraping data is parsed and evaluated locally. No third-party LLM sees raw proprietary inputs unless explicitly directed by the agent.
- **Fernet Encryption**: Browser session states and credentials are encrypted at rest using Fernet (AES-128-CBC + HMAC-SHA256, 256-bit key).
- **Parameterized SQL**: All database operations use strict parameterized queries (`%s`) to prevent SQL injection.
- For vulnerability reports, please consult our [Security Policy](SECURITY.md).

---

## 🤝 Contributing

Contributions from the open-source community are welcome! Please review our [Contributing Guidelines](CONTRIBUTING.md) and [Code of Conduct](CODE_OF_CONDUCT.md) before submitting pull requests.

---

## 📄 License

Distributed under the **MIT License**. See [`LICENSE`](LICENSE) for more information.
