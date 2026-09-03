# CLAUDE.md — Instructions for Claude Code & Claude Desktop 🤖

Welcome to **fnIgnis** (`fn-ignis`) — Unified Self-Hosted Autonomous Trend Intelligence & Market Opportunity Platform by FINOLABS.

---

## ⚡ 1-Step Zero-Touch Autonomous Setup (Setup Tự Động)

If the user gives you this repository link or asks you to set up `fn-ignis`, execute this single command immediately in the terminal:

```bash
./scripts/bootstrap.sh
```

### What this command does automatically:
1. Detects Python $\ge 3.11$ and creates isolated virtual environment (`.venv`).
2. Installs `fn-ignis` with all dependencies.
3. Automatically generates `.env` with secure Fernet AES-256 key and default Zero-Docker SQLite configuration (`DATABASE_URL=sqlite:///ignis.db`).
4. Bootstraps SQLite database schemas and loads 84+ seed domain lexicons & noise filters.
5. Registers the `fn-ignis` FastMCP server into Claude Desktop (`claude_desktop_config.json`), Cursor (`.cursor/mcp.json`), VS Code (`.vscode/mcp.json`), Cline, Roo Code, and workspace `.mcp.json`.
6. Executes synthetic diagnostic self-tests to ensure 100% operational readiness.

*Zero external Docker or PostgreSQL setup is required for on-demand research missions.*

---

## 🏛️ Architecture: The Dual-Track Model

1. **Track 1: Always-On Autonomous Radar (Continuous 24/7 Surveillance)**
   - Operated by Docker daemon (`fn-ignis-worker`).
   - Ingests Google Trends, YouTube, and TikTok signals every 15 minutes.
2. **Track 2: On-Demand Targeted Deep Research (Active Strategic Probes)**
   - Deployed directly by you (the Agent) upon user prompt.
   - Deploys active probes: Google search trends, TikTok autocomplete suggestions, video grid supply, and raw customer comment pain points.
   - Synthesizes mathematical **Opportunity Index** (+100 to -100) and exports interactive HTML dossiers.

---

## 🧭 6-Step Standard Operating Procedure (SOP)

When a user asks to research a market, niche, or trend:

```
Step 1: Clarify Research Objectives & Formulate Core Hypothesis
   ↓ (Call register_domain_lexicon(domain="...", terms=[...]) to expand Quality Gate)
Step 2: Macro Scan & Real-World Keyword Expansion (Creative Center & Autocomplete Suggestions)
   ↓
Step 3: Deep Multi-Platform Ingress & Quality Gate (Spam rejection, Confidence >= 70%)
   ↓
Step 4: Single-Source 4-Lens Breakdown (Demand, Supply, Intent, Voice of Customer)
   ↓
Step 5: Cross-Source Synthesis & Opportunity Index Matrix (Identify White Spaces)
   ↓
Step 6: Strategic Verdict, Entry Risks & Fast MVP Validation (3-7 day test plan + HTML Dashboard)
```

---

## 🛠️ Essential Development & Verification Commands

```bash
# Run complete test suite (96+ tests, 100% async coverage)
uv run pytest

# Run auto-provisioner with JSON output
uv run python -m ignis.interfaces.cli.setup_bundle --json

# Run FastMCP server directly via stdio
ignis-mcp

# Run single ingress pass via CLI
ignis --geo VN --timeframe 24h
```

---

## 🗑️ Ephemeral Handoff & Review Protocol

- **Temporary Working Notes**: When generating interim reviews, architecture audits, or handoff notes meant for 1-time session exchange, **ALWAYS write them to `.handoff/` (or name them `*.handoff.md`)**.
- **Do not clutter `docs/`**: `docs/` is strictly for permanent end-user and developer documentation (`USER_GUIDE.md`).

