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
8. [Research Workspaces & the Two Surfaces](#8-research-workspaces--the-two-surfaces)
9. [Catalog of 45 FastMCP Tools & Comprehensive Research Capabilities](#9-catalog-of-45-fastmcp-tools--comprehensive-research-capabilities)

---

## 1. Architecture Overview

`fn-ignis` is architected around a **Dual-Track Engine**:

The persistence box contains three distinct records on both backends:

- `sources`: one row per external object, keyed by `(platform, external_id)`.
- `observations`: one immutable collection event, including the observed payload, cluster
  membership, identity-resolution route, and clock provenance.
- `mission_evidence`: the exact observations a mission used.

A research workspace adds scope around those three records rather than a store of its own. The
workspace identity, the Market Brief revisions, the writer claims and the run journals are rows in
the same configured database; `.ignis/research/<slug>/` holds the manifest, the run journals and
exported artifacts, and no database of its own. Section 8 describes that boundary.

Repeated polling therefore creates another observation, not another source. A source can support
multiple missions and can appear in multiple clusters through different observations. Runtime code
never writes the legacy `trend_signals` and `signal_metrics` tables; the only runtime read left is
the cluster pruner's guard, which treats a cluster the legacy corpus still references as non-empty
so that pruning before the backfill cannot cascade away the rows the backfill needs.

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
│ - Scheduled HTTP-capable ingress     │     │ - Search suggestions, live grids   │
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
- Create the Python virtual environment (`.venv`) and install the exact solution recorded in the
  committed `uv.lock` via `uv sync --locked --inexact`. `--locked` fails rather than re-resolving
  when the lock and `pyproject.toml` disagree; without `uv` the script falls back to `pip` and says
  plainly that the fallback is best-effort and not reproducible.
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

For a fresh database, the `db` container runs every file in `sql/` in filename order on its first
start and only then reports healthy; this is verified through `021` on
`timescale/timescaledb-ha:pg16`. Every table the chain creates in `public` has row-level security
on. On a server that has the Supabase roles `anon` and `authenticated`, `006` adds their read-only
policies on `market_lexicons` and `industry_taxonomies`, and `021` revokes every other privilege
they hold on the chain's tables; no migration creates a role. The init scripts run only while the
data volume is empty, so a database initialised before `021` must apply
`sql/021_public_schema_rls_coverage.sql` once, connected as the table owner; running it again
changes nothing. For an existing PostgreSQL corpus, do not start the new worker immediately after
deploying its artifact. Follow the canonical
[source/observation production cutover](migrations/2026-09-10-source-observation-baseline.md#production-cutover-runbook):
quiesce the old runtime, snapshot, generate a baseline from that exact snapshot, apply `sql/016`,
backfill, require `VERIFIED`, then start the new runtime and reopen ingress.

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
      "env": {
        "IGNIS_ENV_FILE": "/ABSOLUTE/PATH/TO/fn-ignis/.env"
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
      "command": "/ABSOLUTE/PATH/TO/fn-ignis/.venv/bin/python",
      "args": ["-m", "ignis.interfaces.mcp.server"],
      "env": {
        "IGNIS_ENV_FILE": "/ABSOLUTE/PATH/TO/fn-ignis/.env"
      }
    }
  }
}
```

`IGNIS_ENV_FILE` is the only variable an MCP config needs, and it is a path rather than a
credential. The server reads `.env` itself, so the database URL, the Fernet key and the API keys
live in exactly one file. Copying them into a client config puts secrets in plaintext in several
places and, because a host's `env` overrides the env file, a stale copy silently wins: rotating
the YouTube key in `.env` while Claude Desktop still held the old one made every YouTube call
through MCP fail with "API key expired" while the same code run from a shell succeeded.

#### Two client behaviours that look like failures

**Claude Code may ask you to approve the workspace server.** A `.mcp.json` in the workspace root is
project-scoped, so Claude Code lists it as pending approval until you accept it once. Until then
`claude mcp list` shows the entry but reports it as unapproved rather than connected, and no tool
is callable. Run `claude` in that directory and approve the server; a user-scoped registration
(`claude mcp add-json`) does not need this step.

**Quit Claude Desktop before running bootstrap, then reopen it.** Claude Desktop keeps its
configuration in memory and rewrites the file when it exits, so a registration written while the
app is running is overwritten on quit. The order that sticks is: quit the app, run
`./scripts/bootstrap.sh` (or `python -m ignis.interfaces.cli.setup_bundle`), then start it again.

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

## 8. Research Workspaces & the Two Surfaces

### 8.1 Where a research lives

A research is proposed at `<host-workspace>/.ignis/research/<research-slug>/`:

```text
<host-workspace>/
└── .ignis/
    └── research/
        └── ai-customer-service/
            ├── workspace.json        # manifest: research identity and format version
            └── journals/             # one exclusive record per run
                └── run-20260921-103000-001.json
```

The proposal is read-only. `propose_research_workspace(host_workspace, research_name)` reports the
path it would use, whether the folder exists, whether it already holds a manifest, and whether
adoption would be needed — and creates no directory, no manifest, no database record and no
journal. Only `confirm_research_workspace(proposed_path, confirmation=true)` creates anything.

Three outcomes follow from what is already at the path:

| State of the folder | Result |
|---|---|
| Absent or empty | Created, with a fresh manifest |
| Holds a matching manifest | Reused as-is; the manifest is not rewritten |
| Non-empty, no manifest | Refused until `adopt=true`; adoption preserves every unrelated file |
| Manifest from a newer format | Reported `INCOMPATIBLE` rather than half-read |

**A research folder contains no database.** All research workspaces share the one configured Ignis
database, selected by `DATABASE_URL`: SQLite-local by default, PostgreSQL as an optional equivalent
backend. That is what makes a research reopenable — `list_research_workspaces()` returns the
research held in that database, so a second Agent host on the same database finds it without the
chat that created it.

### 8.2 `ATTENTION` and `MARKET`

A mission answers one of two questions and keeps that surface for its whole life.

| | `ATTENTION` | `MARKET` |
|---|---|---|
| Question | What is gaining attention? | Is this a market opportunity? |
| Entry point | `create_attention_mission` | `confirm_market_brief` |
| Hypothesis required | No | Yes |
| Opportunity Index | Never emitted | Emitted |
| Evidence role in analysis | `ATTENTION_CONTEXT` | `MARKET_EVIDENCE` |

`ATTENTION` is for a requester who does not yet know which topic is worth investigating. It returns
ranked topics with momentum, freshness, source coverage and observation-addressable citations, and
it makes no commercial claim.

`MARKET` requires a requester-confirmed Brief. All seven fields are mandatory:

| Field | Meaning |
|---|---|
| `decision` | The decision this research has to inform |
| `target_user` | The user or customer under investigation |
| `problem` | The pain or job being investigated |
| `geo` | Geographic scope |
| `timeframe` | Evidence window |
| `hypothesis` | The falsifiable proposition |
| `falsifiers` | At least one condition that would disconfirm it |

An incomplete Brief is refused before any probe runs, and the refusal names the missing fields. A
`MARKET` mission whose Brief cannot be read is blocked rather than run — execution, analysis and
artifact export all return the same `BLOCKED` result, because an Opportunity Index derived from
evidence nobody framed a question for is a quieter failure than refusing to probe.

The framing conversation belongs to the host Agent: it asks at most seven questions, one at a time,
skips what is already answered, shows the draft for editing, and asks for an explicit confirmation.
**fn-ignis receives no transcript and has no draft-persistence operation.** A requester who
abandons the framing leaves nothing behind, because nothing was ever sent.

### 8.3 Handoff and revision

Selecting an Attention topic for a Market investigation creates a new mission, not a relabelled
one:

```text
confirm_market_brief(
    workspace_id=...,
    parent_attention_mission_id=<attention mission>,   # optional lineage
    parent_cluster_id=<selected cluster>,              # optional, must be one that mission saw
    decision=..., target_user=..., problem=...,
    geo=..., timeframe=..., hypothesis=..., falsifiers=[...],
    confirmed_by=...,
)
```

Lineage is context. The Attention observations it points at are reported under
`attention_context` with the role `ATTENTION_CONTEXT`, and they cannot satisfy a Market
opportunity or a supporting citation — the new mission collects its own `MARKET_EVIDENCE`.

Changing a confirmed Brief creates a new revision rather than editing the old one. Passing
`previous_mission_id` opens a new Market mission bound to a new immutable `MarketBriefRevision`,
numbered with the next revision number in that research line, with `revises_mission_id` pointing
back at the mission it revises. The earlier mission, its Brief and its evidence are unchanged, and
a revision inherits the Attention origin of the mission it revises: a payload naming a different
origin is refused rather than silently applied.

### 8.4 Concurrent runs, journals, and recovery

Two missions of one research run at the same time; the writer claim is per mission and never
serializes a whole research.

- **One active writer per mission.** A second run against the same mission returns a `CONFLICT`
  result naming the run holding the slot and since when. It reaches no connector and writes
  nothing.
- **One exclusive journal per run.** Each run takes its own file under `journals/`, created
  exclusively, so two runs starting inside the same second still get distinct names. A run that
  finished reports `COMPLETED` or `FAILED` with a completion time; a run that never reported back
  keeps `STARTED` with no completion time, because "this run ended" and "nobody ever heard from it
  again" are different facts.
- **Recovery is explicit.** A claim is released only by the run that holds it. There is no expiry
  and no force release: handing the slot to a second writer on a timer while the first may still
  be running is the failure the slot exists to prevent. When a run is known to have died,
  `release_mission_writer(mission_id, run_id)` recovers the mission and requires exactly the
  `run_id` the conflict result reported. A wrong `run_id` refuses and changes nothing.

Missions created outside a research workspace — every mission written before this feature — take
no writer claim and write no journal, and run exactly as they did before.

---

## 9. Catalog of 45 FastMCP Tools & Comprehensive Research Capabilities

The `fn-ignis` FastMCP server exposes **45 atomic and strategic tools**:

### 0. Research Workspaces & Dual-Surface Missions (6 Tools)
- `propose_research_workspace`: Report where a research would live. Read-only; creates nothing.
- `confirm_research_workspace`: Create, reuse or adopt the proposed workspace after confirmation.
- `list_research_workspaces`: List the research workspaces held in the configured database.
- `create_attention_mission`: Start an `ATTENTION` mission — no hypothesis, no Opportunity Index.
- `confirm_market_brief`: Persist a confirmed Brief and open the `MARKET` mission it authorizes; also the Attention handoff and the Brief revision entry point.
- `release_mission_writer`: Recover a mission whose run died holding its single writer slot, by naming that exact run.

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
- No channel requires an approval process. Google Trends needs nothing, YouTube needs a self-serve API key, and TikTok, Threads and Instagram use a one-click browser login on your own machine. The Meta Graph API tiers are optional: `threads_keyword_search`, which is what would let the Graph tier search public posts, is granted only through Meta App Review, and without it that endpoint silently searches your own posts instead — `authenticate_threads()` reports this as `keyword_search_access`.
- Ingress is public-market by default: the operator's own connected accounts (Threads, Instagram) are never read, so their posts cannot be counted as market demand. Pass `scope="own_profile"` to `trigger_ingress_refresh` only when the request is explicitly about the user's own profile, and set the `self_accounts` runtime config when no API reports the account handle.
- All HTML artifacts render in the FINOLABS design system (Anton / Space Grotesk / JetBrains Mono, Lab Ink neutrals, mint-and-violet brand palette).
- `generate_trend_artifact`: Export a standalone HTML artifact — the trend dashboard, a single topic card (`topic_id`), or an interactive force-directed trend graph (`format="graph"`). The graph is navigable down to the cluster level; signals are aggregated into density halos around their cluster, so a day with tens of thousands of rows still renders smoothly.
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
- `clear_threads_auth`: Delete stored Threads credentials from local encrypted storage. Does not revoke the token at Meta; do that separately in Meta account security settings.

### 5. Instagram Reels Intelligence (3 Tools)
- `authenticate_instagram`: Authenticate Instagram Graph API credentials.
- `get_instagram_auth_status`: Verify connection and token health.
- `clear_instagram_auth`: Delete stored Instagram credentials from local encrypted storage. Does not revoke the token at Meta; do that separately in Meta account security settings.

### 6. Dynamic Configuration & System Health (6 Tools)
- `diagnose_system_health`: Full synthetic diagnostics of database, connectors, and encryption.
- `get_system_logs`: View recent application runtime logs.
- `get_platform_auth_status`: Unified status overview across all social platforms, including expiry warnings (< 7 days) and a staggered `refresh_plan` that keeps two Tier-1 sessions from being refreshed on the same day.
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
