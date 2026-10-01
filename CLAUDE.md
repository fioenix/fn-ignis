# CLAUDE.md — Instructions for Claude Code & Claude Desktop

Welcome to **fnIgnis** (`fn-ignis`) — mission-bound social market research by FINOLABS.

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

## Architecture: Mission-Bound Research

Ignis starts collection only for a user-requested mission or explicit atomic probe. There is no
always-on worker, daily discovery, or background baseline. Its two capability families are source
connectors for collecting inspectable social evidence and an analysis skill for testing a market
hypothesis against that evidence. A raw signal or score is not a market verdict. Persist claims,
counterevidence, evidence gaps, and provenance before returning a strategic conclusion. See
`AGENTS.md` and `specs/011-evidence-grounded-product-reset/` for the governing contract.

---

## Operational Boundary

Atomic connector tools remain independently callable. A strategic market verdict requires a
mission, qualified evidence, a persisted claim ledger, explicit contrary evidence and unresolved
gaps. The agent may autonomously pursue the specified mission, but cannot silently broaden the
research question or launch recurring collection. See the `ignis-collect` and `ignis-analyze`
skills for the separate workflows.

---

## 🛠️ Essential Development & Verification Commands

```bash
# Run the complete suite the way CI does -- tests/, not tests/unit/, which is 4 integration tests short
.venv/bin/pytest tests/

# Run auto-provisioner with JSON output
python -m ignis.interfaces.cli.setup_bundle --json

# Run FastMCP server directly via stdio
ignis-mcp

# Run a requested mission through the current MCP mission operations; do not start a worker.
```

---

## ⚖️ Decision Boundaries

Before asking the owner a question, recording a decision, or touching a migration, a release, an MCP tool signature, or a connector's runtime tier, read `AGENTS.md` Section 8: it says who decides and where the decision is recorded.

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
- [ ] All 41 tools remain callable according to their independent contracts.
- [ ] Output formatting is adapted to conversational context, not forced into rigid report templates.

### Checklist C: Pre-Release & Version Bump Gate
- [ ] Run `.venv/bin/pytest tests/unit/` with 100% pass rate.
- [ ] Verify `docs/` (specs, manuals) and catalogs (`README.md`, `README.vi.md`) are synced with new tools/parameters.
- [ ] Verify clean git status: no stray files in `docs/`, no uncommitted credentials or SQLite files.
- [ ] Ensure working branch is fully merged into `main` before tagging.
- [ ] Run distribution packaging verification (`python -m build` or `uv build`).
- [ ] Atomic Version Synchronization: verify one identical version across all six release-controlled files in a single commit, then tag — `pyproject.toml`, `openclaw.json`, `server.json` (both occurrences), `CITATION.cff` (including `date-released`), `.openclaw/config.yaml`, and the `BACKLOG.md` version banner — plus git tag `vX.Y.Z`. See `AGENTS.md` Section 4 and Checklist C; the obsolete three-file wording is wrong.
- [ ] Regenerate `uv.lock` with `uv lock` in the same commit as the version bump — the lock carries
      the project's own version, so skipping it makes `uv sync --locked` fail on a clean checkout.
      Confirm with `uv lock --check`; never hand-edit the file.
- [ ] Tag release commit (`git tag -a vX.Y.Z -m "Release vX.Y.Z" && git push origin vX.Y.Z`) and publish GitHub Release.
