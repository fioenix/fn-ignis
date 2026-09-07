# CLAUDE.md — Instructions for Claude Code & Claude Desktop 🤖

Welcome to **fnIgnis** (`fn-ignis`) — Unified Self-Hosted Autonomous Trend Intelligence & Market Opportunity Platform by FINOLABS.

---

## ⚡ 1-Step Zero-Touch Autonomous Setup (Automated Setup)

If the user gives you this repository link or asks you to set up `fn-ignis`, execute this single command immediately in the terminal:

```bash
./scripts/bootstrap.sh
```

### What this command does automatically:
1. Detects Python $\ge 3.11$ and creates isolated virtual environment (`.venv`).
2. Installs `fn-ignis` with all dependencies.
3. Automatically generates `.env` with secure Fernet (256-bit key: AES-128-CBC + HMAC-SHA256) key and default Zero-Docker SQLite configuration (`DATABASE_URL=sqlite:///ignis.db`).
4. Bootstraps SQLite database schemas and loads 84+ seed domain lexicons & noise filters.
5. Registers the `fn-ignis` FastMCP server into Claude Desktop (`claude_desktop_config.json`), Google Antigravity, OpenAI Codex (`~/.codex/config.toml`), and workspace `.mcp.json`.
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

## 🧭 Operational Framework & Modes

`fn-ignis` is a modular Agent Harness providing tools, mathematical methodologies, domain knowledge, and reporting scaffolds. It does NOT enforce rigid pipelines:

1. **Tactical Ad-Hoc Mode**: Agents freely invoke atomic FastMCP tools (`get_threads_trending_topics`, `extract_customer_pain_points`, `get_tiktok_search_suggestions`, `get_runtime_config`) to address ad-hoc queries without overhead.
2. **Strategic Research Mode (6-Step Reference Framework)**: When conducting comprehensive market opportunity or white-space discovery, agents are recommended to follow the 6-Step analytical blueprint below:

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
# Run complete test suite (240+ tests, 100% async coverage)
.venv/bin/pytest tests/unit/

# Run auto-provisioner with JSON output
python -m ignis.interfaces.cli.setup_bundle --json

# Run FastMCP server directly via stdio
ignis-mcp

# Run single ingress pass via CLI
ignis --geo VN --timeframe 24h
```

---

## 🗑️ Ephemeral Handoff & Review Protocol

- **Temporary Working Notes**: When generating interim reviews, architecture audits, or handoff notes meant for 1-time session exchange, **ALWAYS write them to `.handoff/` (or name them `*.handoff.md`)**.
- **Do not clutter `docs/`**: `docs/` is strictly for permanent end-user and developer documentation (`USER_GUIDE.md`).

---

## 🛡️ Mandatory Operational & Release Checklists

Before completing changes or cutting a release, verify these three checklist gates:

### Checklist A: Open-Source Codebase & Documentation Standards
- [ ] Source code, tests, docstrings, variable/function names, and git commits follow standard English conventions for global open-source contributors.
- [ ] Meta instructions (`CLAUDE.md`, `AGENTS.md`, `SKILL.md`) are maintained in English.
- [ ] Regional documentations (`README.vi.md`) and localized market reports in `reports/` are maintained for their respective target audiences.

### Checklist B: Harness Autonomy & Decoupling
- [ ] FastMCP server instructions and tool definitions do NOT dictate mandatory agent workflows.
- [ ] All 39 tools are callable independently for ad-hoc queries.
- [ ] Output formatting is adapted to conversational context, not forced into rigid report templates.

### Checklist C: Pre-Release & Version Bump Gate
- [ ] Run `.venv/bin/pytest tests/unit/` with 100% pass rate.
- [ ] Verify `docs/` (specs, manuals) and catalogs (`README.md`, `README.vi.md`) are synced with new tools/parameters.
- [ ] Verify clean git status: no stray files in `docs/`, no uncommitted credentials or SQLite files.
- [ ] Ensure working branch is fully merged into `main` before tagging.
- [ ] Run distribution packaging verification (`python -m build` or `uv build`).
- [ ] Atomic Triple Synchronization: Verify identical version across `pyproject.toml`, `openclaw.json`, and git tag `vX.Y.Z`.
- [ ] Tag release commit (`git tag -a vX.Y.Z -m "Release vX.Y.Z" && git push origin vX.Y.Z`) and publish GitHub Release.


