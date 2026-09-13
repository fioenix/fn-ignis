# CLAUDE.md — Instructions for Claude Code & Claude Desktop 🤖

Welcome to **fnIgnis** (`fn-ignis`) — Unified Self-Hosted Autonomous Trend Intelligence & Market Opportunity Platform by FINOLABS.

---

## 🚦 Two Rules That Are Violated Most Often — Read Before Editing Any File

These are not release-time checks. They apply to every line you write, at the moment you write it.
Full detail lives in `AGENTS.md` Section 3 (Language Boundary Protocol, Data-Driven Vocabulary Protocol).

**1. Language is decided by where the artifact lives, not by the language of the conversation.**
Everything inside `src/` and `tests/` is English — identifiers, docstrings, comments, assert messages,
log lines, exception text, and any string the code emits (`summary_text`, fallback names, status labels).
"Match the user's language" governs chat responses and regional deliverables (`reports/`,
`README.vi.md`, `docs/*.vi.md`) only. A failing assertion read by a Vietnamese developer is still
developer output, so it is English. Test *fixture data* may be Vietnamese — that is the subject under
test, not prose. Never write Vietnamese stripped of its diacritics as a compromise.

**2. Domain vocabulary goes in the database, never in a Python constant.**
Terms, synonyms, brand names, intent keywords, noise phrases, and category keywords belong in
`market_lexicons` / `industry_taxonomies` / `runtime_configs`, seeded from `sql/` and read through the
existing `register_*` and `get_*` paths. Adding a `KEYWORD_SYNONYMS`-style dict to `src/` is a band-aid
even when it turns a test green. The only exceptions are third-party UI selectors that must match
verbatim, and character-class regexes where the characters are the algorithm; both need an inline
comment saying so.

Verify with: `.venv/bin/pytest tests/unit/test_repo_conventions.py`

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
6. Executes synthetic diagnostic self-tests and reports readiness per component. A fresh SQLite
   install is fully usable on its own; external connectors stay unavailable or degraded until the
   operator supplies their own credentials, and the report says so rather than claiming the whole
   system is operational.

*Zero external Docker or PostgreSQL setup is required for on-demand research missions.*

---

## 🏛️ Architecture: The Dual-Track Model

1. **Track 1: Always-On Autonomous Radar (Optional, Continuous Baseline)**
   - Operated by the Docker daemon (`fn-ignis-worker`) — optional, not required. On-demand research works without it.
   - Ingests through **official HTTP APIs only**: Google Trends RSS and the YouTube Data API. The default tick is
     `SCHEDULER_INTERVAL_SECONDS=8640` (~2.4h), not a fixed 15 minutes: one pass probes up to 10 keywords and a
     YouTube `search.list` costs 100 units, so 10 passes a day is what fits inside the 10,000-unit daily quota.
   - The worker image ships no browser runtime, so connectors that can only reach their data by driving a browser (TikTok, and Threads/Instagram without a Graph token) are left out of its registry and handled by Track 2 instead. Each connector decides this itself via `resolve_ingest_runtime()`.
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
# Run the complete suite the way CI does -- tests/, not tests/unit/, which is 4 integration tests short
.venv/bin/pytest tests/

# Run auto-provisioner with JSON output
python -m ignis.interfaces.cli.setup_bundle --json

# Run FastMCP server directly via stdio
ignis-mcp

# Trigger one ingress pass (through the MCP tool, or the worker for the continuous baseline)
#   trigger_ingress_refresh(geo="VN")   -- an ingress pass exists to answer a question; there is
#                                          no standalone "listen to everything once" command.
```

---

## 🗑️ Ephemeral Handoff & Review Protocol

- **Temporary Working Notes**: When generating interim reviews, architecture audits, or handoff notes meant for 1-time session exchange, **ALWAYS write them to `.handoff/` (or name them `*.handoff.md`)**.
- **Do not clutter `docs/`**: `docs/` is strictly for permanent end-user and developer documentation (`USER_GUIDE.md`).

---

## 🛡️ Mandatory Operational & Release Checklists

Before completing changes or cutting a release, verify these three checklist gates:

### Checklist A: Open-Source Codebase & Documentation Standards
- [ ] Source code, tests, docstrings, variable/function names, assert messages, emitted strings, and git commits follow standard English conventions for global open-source contributors.
- [ ] No new domain vocabulary hardcoded as Python constants in `src/` (seed it in `sql/`, read it from the database).
- [ ] `.venv/bin/pytest tests/unit/test_repo_conventions.py` passes.
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
- [ ] Atomic Version Synchronization: verify one identical version across all six release-controlled files in a single commit, then tag — `pyproject.toml`, `openclaw.json`, `server.json` (both occurrences), `CITATION.cff` (including `date-released`), `.openclaw/config.yaml`, and the `BACKLOG.md` version banner — plus git tag `vX.Y.Z`. See `AGENTS.md` Section 4 and Checklist C; the obsolete three-file wording is wrong.
- [ ] Tag release commit (`git tag -a vX.Y.Z -m "Release vX.Y.Z" && git push origin vX.Y.Z`) and publish GitHub Release.


