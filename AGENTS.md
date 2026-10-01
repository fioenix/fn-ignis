# fn-ignis Agent Operating Guidelines & Interface Protocol 🤖

This document defines the operational protocol, architectural guidelines, and tool selection principles for AI Agents (**Claude Desktop, Claude Code, Antigravity, OpenAI Codex, OpenClaw, Hermes, and Pi Agent**) interacting with `fn-ignis`.

---

## ⚡ 0. Zero-Touch Agent Bootstrap Protocol (Automated Setup)

> **MANDATORY INSTRUCTION FOR ALL AI AGENTS:**  
> When given this repository link (`https://github.com/fioenix/fn-ignis`) or instructed to set up `fn-ignis` for the user, execute this command immediately:
>
> ```bash
> ./scripts/bootstrap.sh
> ```
>
> **Autonomous Actions Performed:**
> 1. Provisions virtual environment (`.venv`) and installs `fn-ignis` in editable mode.
> 2. Creates `.env` with SQLite default (`DATABASE_URL=sqlite:///ignis.db`) and generates a persistent Fernet (256-bit key: AES-128-CBC + HMAC-SHA256) key.
> 3. Bootstraps SQLite database schemas and loads 84+ seed domain lexicons & noise filters.
> 4. Auto-configures FastMCP server in all supported agent environments (`.mcp.json`, `claude_desktop_config.json`, Google Antigravity, OpenAI Codex `config.toml`).
> 5. Runs synthetic diagnostics and outputs structured readiness confirmation.
>
> *No user input or external database installation is required.*

---

## 🏛️ 1. Architecture: Mission-Bound Evidence Grounding

Ignis starts only after a person or host agent assigns an explicit bounded task. There is no
worker, scheduler, daily discovery, or idle collection. Inside a confirmed Mission Manifest,
the agent may autonomously select in-scope probes; it stops at a terminal state or an authority
boundary.

The product has two independent capability families:

1. **Collection**: integrated connectors and skills pull source observations for an explicit
   tactical probe or mission. The result retains source identity, query, collection time, channel
   outcome, and access limitations. Collected data is not yet a Market conclusion.
2. **Senior Market Analytics**: the analysis skill and report templates work on an eligible Ignis
   evidence frame. A confirmed Market Brief includes alternatives, a null hypothesis, falsifiers,
   kill criteria, and a revision rule. Counterevidence and missingness must be reported.

Both families share the evidence control plane: Mission Manifest, source/observation lineage,
channel outcomes, qualification, strategic sufficiency, and the current-frame Claim Ledger.
Market verdicts render only from persisted permitted claims. When evidence is insufficient,
return a typed Gap Report; no Opportunity Index or recommendation is inferred from raw metrics.
Attention observations remain context and never silently become Market support.

The beachhead pilot is Vietnamese consumer-market research for founders, operators, independent
analysts, consultants, and small teams. This is a validation audience, not proof of market fit.

## 🧭 2. Operating Modes

### Tactical collection

Use an atomic connector operation for a bounded user question. Return observations, provenance,
channel state, and limitations. It does not create a mission, schedule follow-up work, or produce a
strategic Market verdict. Requested collection preserves source languages for downstream
qualification.

### Strategic Market research

1. Frame the decision backwards from the outcome. Confirm a Mission Manifest, allowed sources,
   authority boundary, cost, output, stop conditions, and retention policy.
2. Confirm the Market Brief: target user, problem, hypothesis, at least two alternatives, null
   hypothesis, falsifiers, kill criteria, and revision rule.
3. Plan and run only authorized probes. Preserve every channel's measured outcome, including
   auth failure, rate limit, degradation, and healthy emptiness.
4. Qualify each observation against the current Brief and collection-plan frame, including
   support, contradiction, and context. Do not promote external files or earlier Attention
   observations to primary evidence without mission-scoped verification.
5. Submit typed candidate claims against the current evidence-frame digest. Read the current
   Claim Ledger. Render permitted claims with citations, contradiction, limitations, and decision
   conditions; otherwise render the Gap Report and next-best probe.
6. Stop at completion, insufficient evidence, cancellation, failure, or missing authority.

This is an analytical reference, not an unskippable pipeline for tactical calls. Outcome thinking
defines the decision, design thinking locates the user and method, and critical thinking actively
tests the initial belief.

### Connector access boundary

Threads Graph keyword search may return only the authenticated account's posts unless Meta grants
the capability. Treat `SELF_ONLY` and `NOT_PERMITTED` as unavailable for market listening; use a
user-authorized browser session only when the mission permits it. Never present an own-account
timeline as market evidence. Browser, token, and paid-quota authority must be confirmed before use.

---
## 🎨 3. Presentation & Evidence Attribution Standards

### Campaign Identification Banner
When executing a formal Strategic Research Campaign, prefix the analysis with the campaign identifier banner:

> **🎯 Campaign:** `[VN-AI-AGENT-90D]` — *AI Agents & Automation in Vietnam*  
> **Shortcode:** `VN-AI-AGENT-90D` *(or `fb16c5ee`)*  
> **Session ID:** `codex://threads/01a05666...` *(if available)*

### Native Artifacts First
- Render source coverage, permitted claims, or a Gap Report directly in chat at the level of detail the user requested.
- Export standalone HTML files to `reports/` via `generate_mission_artifact` when the user requests a persistent local dossier.

### 🎨 FINOLABS Design System

Every HTML artifact renders in the FINOLABS design system. The tokens are vendored into
`src/ignis/infrastructure/templates/html/_fino_theme.html` from the "Finolabs Design System"
project on claude.ai/design (`theme.css`); update that partial when the source moves, and keep the
values byte-identical rather than eyeballing new ones.

Rules that apply to artifacts specifically:
- Artifacts are **product surfaces**: `<body class="product-mode">`, density and data-viz tokens,
  never the marketing register on the same page.
- **Type**: Anton for display caps, Space Grotesk for UI and body, JetBrains Mono for numbers and
  machine labels. Numbers use `font-variant-numeric: tabular-nums`.
- **Colour**: never hard-code hex. Chrome reads the role tokens (`--color-foreground`,
  `--color-border`), series read the data-viz slots (`--color-chart-1..12`), labels read the tag
  pairs. Mint is the everyday brand colour; violet is reserved for a single high-stakes accent.
- **No emoji.** `→ ↗ • — ◆ ◇` are the allowed glyphs; `→` is the canonical action glyph.
- **Radius** `--radius-lg` for cards, `--radius-full` for chips; shadows only `xs`, `md`, `xl`.
- Artifacts may fetch the FINOLABS webfonts, and nothing else external beyond the CDN libraries a
  template already declares. The trend graph renders its canvas and force layout inline so the
  export stays usable offline.

### 📊 Evidence Attribution Standards
When presenting strategic conclusions, agents must maintain evidentiary integrity:
1. **Data Ingress Summary Table**:
   - Explicitly list every requested channel, including those that did not run or could not be measured.
   - Display counts and exact channel state from the current evidence frame; never equate missingness with zero.
2. **Inline Evidence Citations**:
   - Render only current-frame `PERMITTED` Claim Ledger entries with their observation bindings.
   - Disclose contradiction, sample limitations, denominator/timeframe for measurements, and conditions that would change the decision.

### 🧾 Recommended Full Strategic Report Structure
When compiling a Comprehensive Strategic Dossier, the following standard structure is recommended:
1. **Campaign Identification Banner**
2. **Data Ingress Summary Table** (from `channel_summaries`)
3. **Quality Scorecard**
4. **Single-Source 4-Lens Breakdown** (with source citations)
5. **Current-frame Claim Ledger and counterevidence** (only permitted claims)
6. **Decision conditions or Gap Report** (never invent a verdict when evidence fails)

*(For ad-hoc queries, agents should adjust output format flexibly to match the user's specific conversational need).*

### 🌐 Language Boundary Protocol

The language of an artifact is decided by **where the artifact lives**, never by the language the user
is speaking in the current conversation. Agents reason internally in English.

| Artifact | Language | Notes |
|---|---|---|
| Chat responses to the user | User's language | The only place conversational language applies |
| `reports/`, `README.vi.md`, `docs/*.vi.md` | Target market language | Regional deliverables |
| HTML report copy rendered for a regional audience | Target market language | Template body text, not template identifiers |
| `src/**` — code, identifiers, docstrings, comments | **English** | No exceptions |
| `src/**` — log lines, exception messages, strings the code emits (`summary_text`, fallback names, status labels) | **English** | These are machine-facing output, not conversation |
| `tests/**` — docstrings, comments, assert messages, test names | **English** | A failing assertion is developer output |
| `tests/**` — fixture data (titles, comments, keywords under test) | Any language | Vietnamese fixtures are required to test Vietnamese behaviour |
| `sql/**` seeds, migration comments | **English** identifiers; vocabulary rows may be any language | The row *is* the data |
| Git commits, PR descriptions, branch names | **English**, imperative | `Add`, `Fix`, `Refactor`, `Update` |
| `AGENTS.md`, `CLAUDE.md`, skills, specs | **English** | Developer meta-guidance |

> **The trap this rule exists to close:** "match the user's language" applies to the conversation only.
> An assert message, a log line, or a string the engine returns is *not* a chat response, even when a
> Vietnamese user eventually reads it. When an agent is unsure which side a string falls on, it is English.

> **Diacritics:** never write Vietnamese without its diacritics as a compromise ("Chu de tong hop").
> That satisfies neither convention. Write correct English, or correct Vietnamese where Vietnamese belongs.

### 🗄️ Data-Driven Vocabulary Protocol

Domain knowledge belongs in the database, not in Python. The tables exist precisely so that vocabulary
can be extended at runtime without a release:

- `market_lexicons` — domain terms, slang, synonyms (grouped by `domain` + `category`), foreign stopwords, noise blacklist.
- `industry_taxonomies` — category keywords used to classify clusters.
- `runtime_configs` — thresholds and connector parameters.

**Do NOT** introduce a Python `list`/`dict`/`set` of domain terms, synonyms, brand names, intent
keywords, noise phrases, or category keywords inside `src/`. Seed them in `sql/` and read them through
the existing `register_*` / `get_domain_lexicons` / `get_industry_taxonomies` paths. If a new engine
needs vocabulary, it grows a `register_*` method and a sync call — it does not grow a constant.

Two narrow exceptions, both of which must carry an inline comment stating why:
1. **Locale-dependent selectors** that must match a third-party UI verbatim (`'button:has-text("Xem thêm")'`).
2. **Character-class regexes** used for script/language detection, where the characters *are* the algorithm.

A hardcoded vocabulary is a band-aid even when it makes a test pass: it ships domain knowledge that only
a code release can change, and it silently diverges from the database other components read.

**Store vocabulary in the language as it is written.** Vietnamese terms keep their tone marks, in
`market_lexicons` and `industry_taxonomies` alike. Stripping tones to "canonicalise" destroys the word:
`vàng` (gold) and `vang` (resonant) fold to one string, as do `tóc`/`tốc` and `chính phủ`/`chinh phục`.
That folding produced a run of wrong categories — a bolero playlist under finance, an esports bracket
under beauty — and four separate rules were added to compensate before the premise itself was accepted.
Lexicon terms are also handed to connectors as search queries, so a tone-stripped term asks the platform
a question no Vietnamese user would type. Matching folds only when the *input* carries no tones, which is
common and legitimate; the ambiguity then belongs to the input rather than to the system. Never fold both
sides by default, and never match a multi-word term as a raw substring — anchor on word boundaries, or
`ô tô` fires inside `cho tôi`.

---

### 🚦 Requested Ingress Boundary

Every ingress pass is explicitly requested. The registry refuses any other trigger before a
connector probe or quota reservation. Source language is retained; relevance and claim support
are judged downstream. The historical YouTube `scheduled_used` column remains read-only audit
data, not a reason to schedule work or reserve quota.

---
## 🏷️ 4. Release Versioning Principles & SemVer Guardrails

All agents (**Claude Desktop, Claude Code, Antigravity, OpenAI Codex, OpenClaw, Hermes, Pi Agent**) must strictly adhere to **Semantic Versioning 2.0.0 (`MAJOR.MINOR.PATCH`)**:

```
v MAJOR . MINOR . PATCH
    ↑       ↑       ↑
Breaking Feature   Bugfix / Optimization
```

### Version Bump Criteria

| Increment Level | When to Bump | Example Transition | Reset Rule |
|---|---|---|---|
| **`PATCH`** (`+0.0.1`) | Backward-compatible bug fixes, minor connector tweaks, test suite additions, documentation updates, or internal performance tuning. | `0.1.0` $\rightarrow$ `0.1.1` | None |
| **`MINOR`** (`+0.1.0`) | New platform connectors (e.g. Threads comments, Xiaohongshu), new FastMCP tools/prompts, new database migrations, or significant new analytical models. | `0.1.5` $\rightarrow$ `0.2.0` | `PATCH` resets to `0` |
| **`MAJOR`** (`+1.0.0`) | Breaking architectural overhauls, incompatible database schema drops, or breaking FastMCP tool signature deprecations. | `0.9.4` $\rightarrow$ `1.0.0` | `MINOR` & `PATCH` reset to `0` |

### ⛔ Strict Agent Guardrails

1. **NO Speculative or Arbitrary Bumps**: Do NOT bump version numbers for routine single-file bug fixes or daily development tasks. Versions are bumped **ONLY during formal release preparation** on `release/*` or `main`.
2. **NO Number Skipping**: Never jump versions arbitrarily (e.g. from `0.1.0` directly to `0.5.0` or `1.0.0`). Always increment by strictly `+1` at the appropriate level.
3. **Atomic Version Synchronization**: Six files carry the version string, not three. When a version bump is performed, the Agent **MUST update every one of them in a single atomic commit**, then tag:
   - [`pyproject.toml`](pyproject.toml) $\rightarrow$ `version = "X.Y.Z"`
   - [`openclaw.json`](openclaw.json) $\rightarrow$ `"version": "X.Y.Z"`
   - [`server.json`](server.json) $\rightarrow$ twice: the manifest version and the package version
   - [`CITATION.cff`](CITATION.cff) $\rightarrow$ `version: X.Y.Z` and `date-released`
   - [`.openclaw/config.yaml`](.openclaw/config.yaml) $\rightarrow$ `version: X.Y.Z`
   - [`BACKLOG.md`](BACKLOG.md) $\rightarrow$ the version banner
   - Git Tag on `main` $\rightarrow$ `vX.Y.Z`

   The identical list is enforced in Checklist C below. Do not reintroduce the obsolete three-file wording.
4. **Beta Phase Principle (`0.X.Y`)**: While in initial beta stages (`0.X.Y`), prioritize `PATCH` and `MINOR` increments. Do NOT rush to `1.0.0` until enterprise multi-tenancy and production stability milestones are reached.

---

## 🗑️ 5. Ephemeral Agent Handoff & Review Protocol

> **MANDATORY RULE FOR TEMPORARY WORKING ARTIFACTS:**
> Any interim review notes, audit summaries, handoff memos, or scratchpads exchanged between AI agents (Claude Code, Antigravity, OpenAI Codex) **MUST be written exclusively into `.handoff/` (or named `*.handoff.md` / `*.ephemeral.md`)**.
>
> - **DO NOT** create temporary audit or review files directly inside `docs/` or project root.
> - `docs/` is reserved **strictly for permanent product documentation** (e.g. `USER_GUIDE.md`, architecture manuals).
> - `.handoff/` is 100% ignored by Git and will be purged periodically without affecting repository history.

---

## 🛡️ 6. Pre-Flight & Operational Release Checklists

Every AI Agent modifying this repository or preparing a release must verify compliance against these three mandatory checklists:

### Checklist A: Open-Source Codebase & Documentation Standards
- [ ] **Global Codebase Convention**: All source code (`src/`), test suites (`tests/`), variable/function names, docstrings, inline comments, assert messages, log lines, and strings emitted by the code follow standard English (see the Language Boundary Protocol table in Section 3).
- [ ] **No Hardcoded Vocabulary**: No new domain terms, synonyms, intent keywords, noise phrases, or category keywords added as Python constants in `src/` (see the Data-Driven Vocabulary Protocol in Section 3).
- [ ] **Convention Gate**: `.venv/bin/pytest tests/unit/test_repo_conventions.py` passes.
- [ ] **Developer Meta-Guidance**: Core developer instructions (`AGENTS.md`, `CLAUDE.md`, skills) are maintained in English.
- [ ] **Git Commits & Branching**: 100% English imperative commit messages (e.g., `Add`, `Fix`, `Refactor`, `Update`).
- [ ] **Regional Documentation**: Dedicated localized documentation (such as `README.vi.md`) and market dossiers in `reports/` are accurately maintained for regional audiences.

### Checklist B: Harness Autonomy & Non-Prescriptive Decoupling
- [ ] **Non-Prescriptive Instructions**: Verify FastMCP server instructions and tool docstrings do NOT coerce agents into forced pipelines (no "MUST STRICTLY FOLLOW").
- [ ] **Atomic Independence**: Ensure all 41 FastMCP tools are independently callable within their authority and evidence contracts.
- [ ] **Framework Separation**: The strategic research recipe is a reference, never a forced pipeline for tactical collection.
- [ ] **Contextual Deliverables**: Deliverables match user intent (concise text, cards, tables, or full HTML dashboards) without forcing boilerplate templates for trivial queries.

### Checklist C: Formal Release & Version Bump Gate
- [ ] **Automated Test Gate**: Run `.venv/bin/pytest tests/unit/` (or `uv run pytest`) with 100% pass rate before committing release changes.
- [ ] **Docs & Specs Sync**: Verify `docs/` (e.g., `USER_GUIDE.md`, architecture specs) and tool catalogs (`README.md`, `README.vi.md`) are fully updated with newly introduced tools, parameters, or schemas.
- [ ] **Clean Working Tree**: Verify no uncommitted scratchpads, no leaked credentials/`.env`, and no temporary audit notes placed in `docs/` (strictly `.handoff/`).
- [ ] **Branch Merge to Main**: Ensure the feature or maintenance branch is fully merged into `main` before tagging.
- [ ] **Packaging Verification**: Run distribution build check (`python -m build` or `uv build`) to verify clean package artifacts without missing assets.
- [ ] **Atomic Version Synchronization**: Six files carry the version string, not three. Update every one of them in a single atomic commit, then tag:
  - `pyproject.toml` (`version = "X.Y.Z"`)
  - `openclaw.json` (`"version": "X.Y.Z"`)
  - `server.json` (twice: the manifest version and the package version)
  - `CITATION.cff` (`version: X.Y.Z`)
  - `.openclaw/config.yaml` (`version: X.Y.Z`)
  - `BACKLOG.md` (the version banner)
  - Git Tag (`vX.Y.Z`) on `main`
  - Verify with `grep -rn "<previous version>" --include="*.toml" --include="*.json" --include="*.yaml" --include="*.cff" --include="*.md" .` returning nothing
- [ ] **Regenerate `uv.lock` in that same commit.** The lock records the project's own version,
  so bumping `pyproject.toml` without running `uv lock` makes `uv sync --locked` fail on a clean
  checkout and takes CI down with it. Run `uv lock`; never hand-edit the file. Confirm with
  `uv lock --check`.
- [ ] **GitHub Release Tagging**: Tag and push release commit (`git tag -a vX.Y.Z -m "Release vX.Y.Z" && git push origin vX.Y.Z`) and publish the GitHub Release note.
- [ ] **SemVer Guardrail**: Increment strictly by `+1` (`PATCH`, `MINOR`, `MAJOR`) according to Section 4 criteria. Never jump versions arbitrarily.




---

## 📁 7. Artifact Output vs. Committed Samples

- `reports/` is **local runtime output only** and is fully gitignored (except `.gitkeep`). Every artifact a tool generates at runtime lands here, and nothing in it is ever committed.
- `examples/case-studies/` holds the **curated sample dossiers** that documentation links to. `scripts/generate_sample_case_studies.py` writes there on purpose.
- HTML **templates** live in `src/ignis/infrastructure/templates/html/` and are the only report source committed as code.

---

## ⚖️ 8. Decision Boundaries & Decision Records

These boundaries hold for every contributor. Where the `noulmes` skill is installed, an agent applies them with its decision check (`jev.py check`) before acting and its gate (`jev.py gate`) before asking the owner.

**The owner decides these; an agent asks before acting:**
- An agent asks the owner before writing or applying a migration in `sql/` that transforms persisted evidence (Constitution VI).
- An agent asks the owner before a version bump, a tag, or a release (Section 4).
- An agent asks the owner before changing or removing an MCP tool's signature.
- An agent asks the owner before moving a connector between the HTTP and browser tiers.
- An agent asks the owner before writing to the Supabase development database; reading it needs no question.
- An agent asks the owner before using a real TikTok, Threads, or Instagram session or token.

**The agent decides these alone and records the decision:** vocabulary seeded in `sql/`, test fixtures, internal refactors that keep every contract, `.handoff/` notes, and thresholds in a local SQLite `runtime_configs`.

**An agent checks a choice before acting** when it falls within the constitution (`.specify/memory/constitution.md`, Principles I–VI) or an ADR in `docs/decisions/`, such as adding a dependency or a migration.

**Where a decision is recorded:**
- A decision that belongs to a spec is recorded in that spec's `## Clarifications`, under `### Session YYYY-MM-DD`, as `- Q: … → A: … (agent decided; basis: …)`.
- An agent records a decision in a spec's `## Clarifications` only when the task belongs to that spec, even when `.specify/feature.json` names that spec; `feature.json` can still name a finished spec.
- A decision that belongs to no spec is recorded as a dated note tagged `fn-ignis` in the first folder of `NOULMES_DECISIONS` when it is set, and is otherwise reported as unrecorded.
- `docs/decisions/` holds architecture and product ADRs. An agent drafts an ADR as `Proposed`, and the owner sets its status.
