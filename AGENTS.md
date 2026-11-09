# fn-ignis Agent Operating Guidelines & Interface Protocol 🤖

This document defines the operational protocol, architectural guidelines, and tool selection principles for AI Agents (**Claude Desktop, Claude Code, Antigravity, OpenAI Codex, OpenClaw, Hermes, and Pi Agent**) interacting with `fn-ignis`.

## ⚡ 0. Zero-Touch Agent Bootstrap Protocol (Automated Setup)

Advisory (agent judgment): when given this repository link (`https://github.com/fioenix/fn-ignis`) or asked to set up `fn-ignis`, run `./scripts/bootstrap.sh`. It needs no user input or external database; it reports readiness per component, and external connectors stay unavailable or degraded until the operator supplies credentials.

Owner-approved exception (2026-10-04): `./scripts/bootstrap.sh --client codex --env-file /absolute/path/to/uat/.env` configures only Codex and isolates UAT storage. The default remains all clients.

## Commands

```bash
uv sync --locked --extra dev --extra browser   # install
uv run ruff check src/ tests/                  # lint
uv run pytest tests/                           # complete suite, as CI runs it
uv run pytest tests/unit/test_repo_conventions.py::test_agent_guidance_routes_only_explicit_mission_bound_work  # one test
uv build                                       # build the package
python -m ignis.interfaces.cli.setup_bundle --json  # auto-provision
ignis-mcp                                      # FastMCP server over stdio
```

Run requested missions through the current MCP mission operations; do not start a worker.

## 🏛️ 1. Architecture: Mission-Bound Evidence Grounding

Ignis starts only after a person or host agent assigns an explicit bounded task. Ignis holds no
worker, scheduler, daily discovery, or idle collection. A user may ask their own agent to run one
watchlist on the host's native scheduler; each firing is a separate explicit run (constitution
Principle I). Inside a confirmed Mission Manifest, the agent may autonomously select in-scope
probes; it stops at a terminal state or an authority boundary.

Ignis keeps no author identity at rest: handles, account ids, display names and profile links are
removed before an observation is stored, distinct voices are counted only through per-mission
markers, and the only identities kept are accounts a requester declares for one mission
(constitution Principle VII, Spec 015).

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
analysts, consultants, and small teams. This is a validation audience, not proof of market fit. `specs/011-evidence-grounded-product-reset/` is the governing contract for this model.

## 🧭 2. Operating Modes

### Tactical collection

Use an atomic connector operation for a bounded user question. Return observations, provenance,
channel state, and limitations. It does not create a mission, schedule follow-up work, or produce a
strategic Market verdict. Requested collection preserves source languages for downstream
qualification.

Strategic Market research follows the mission and evidence steps in `docs/agents/research-reporting.md`; read it before a strategic mission. It is an analytical reference, not a pipeline for tactical calls.

### Connector access boundary

Threads Graph keyword search may return only the authenticated account's posts unless Meta grants
the capability. Treat `SELF_ONLY` and `NOT_PERMITTED` as unavailable for market listening; use a
user-authorized browser session only when the mission permits it. Never present an own-account
timeline as market evidence. Browser, token, and paid-quota authority must be confirmed before use.

## 🎨 3. Presentation & Evidence Attribution Standards

Read `docs/agents/research-reporting.md` before rendering a strategic dossier or HTML artifact: it holds the campaign banner, the FINOLABS design system, attribution rules, and the recommended report structure.

### 🌐 Language Boundary Protocol

The language of an artifact is decided by **where the artifact lives**, never by the language the user
is speaking in the current conversation. Agents reason internally in English.

| Artifact | Language | Notes |
|---|---|---|
| Chat responses to the user | User's language | The only place conversational language applies |
| `reports/`, `README.vi.md`, `docs/*.vi.md` | Target market language | Regional deliverables |
| HTML report copy rendered for a regional audience | Target market language | Template body text, not template identifiers |
| `src/**` — code, identifiers, docstrings, comments | **English** | Enforcer: `tests/unit/test_repo_conventions.py` |
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

## 🏷️ 4. Release Versioning Principles & SemVer Guardrails

Versions use `MAJOR.MINOR.PATCH`. During `0.x`, the bump follows user-visible product impact, and a bump happens only during formal release preparation. Read `docs/agents/release-gates.md` before any bump: it holds the criteria and the six release-controlled files.

## 🗑️ 5. Ephemeral Agent Handoff & Review Protocol

> Advisory (agent judgment). Any interim review notes, audit summaries, handoff memos, or scratchpads exchanged between AI agents (Claude Code, Antigravity, OpenAI Codex) belong in `.handoff/` (or named `*.handoff.md` / `*.ephemeral.md`).
>
> - **DO NOT** create temporary audit or review files directly inside `docs/` or project root.
> - `docs/` is reserved **strictly for permanent product documentation** (e.g. `USER_GUIDE.md`, architecture manuals).
> - `.handoff/` is 100% ignored by Git and will be purged periodically without affecting repository history.

## 🛡️ 6. Pre-Flight & Operational Release Checklists

Before completing a change, `.venv/bin/pytest tests/unit/test_repo_conventions.py` passes. Read `docs/agents/release-gates.md` for Checklists A, B, and C before cutting a release.

- [ ] **Atomic Independence**: Ensure all 53 FastMCP tools are independently callable within their authority and evidence contracts.

## 📁 7. Artifact Output vs. Committed Samples

- `reports/` is **local runtime output only** and is fully gitignored (except `.gitkeep`). Every artifact a tool generates at runtime lands here, and nothing in it is ever committed.
- `examples/case-studies/` holds the **curated sample dossiers** that documentation links to. `scripts/generate_sample_case_studies.py` writes there on purpose.
- HTML **templates** live in `src/ignis/infrastructure/templates/html/` and are the only report source committed as code.

## ⚖️ 8. Decision Boundaries & Decision Records

These boundaries hold for every contributor. Where the `noulmes` skill is installed, an agent applies them with its decision check (`jev.py check`) before acting and its gate (`jev.py gate`) before asking the owner.

**The owner decides these; an agent asks before acting:**
- An agent asks the owner before a migration transforms persisted evidence (Constitution VI).
- An agent asks the owner before a version bump, a tag, or a release (Section 4).
- An agent asks the owner before changing or removing an MCP tool's signature.
- An agent asks the owner before moving a connector between the HTTP and browser tiers.
- An agent asks the owner before using a real TikTok, Threads, or Instagram session or token.

**The agent decides these alone and records the decision:** vocabulary seeded in `sql/`, test fixtures, internal refactors that keep every contract, `.handoff/` notes, and thresholds in a local SQLite `runtime_configs`.

**An agent checks a choice before acting** when it falls within the constitution (`.specify/memory/constitution.md`, Principles I–VII) or an ADR in `docs/decisions/`, such as adding a dependency or a migration.

**Where a decision is recorded:**
- A decision that belongs to a spec is recorded in that spec's `## Clarifications`, under `### Session YYYY-MM-DD`, as `- Q: … → A: … (agent decided; basis: …)`.
- An agent records a decision in a spec's `## Clarifications` only when the task belongs to that spec, even when `.specify/feature.json` names that spec; `feature.json` can still name a finished spec.
- A decision that belongs to no spec is recorded as a dated note tagged `fn-ignis` in the first folder of `NOULMES_DECISIONS` when it is set, and is otherwise reported as unrecorded.
- `docs/decisions/` holds architecture and product ADRs. An agent drafts an ADR as `Proposed`, and the owner sets its status.

## 9. Delivery Practices

Read `docs/agents/delivery-practices.md` before substantial implementation, a TypeSafe judgment, or a material status report.

Session naming: when starting or switching a task, rename the session with the host's title tool. Titles start with `IGN`: `IGN <task ID> — <short description>`, or `IGN <concise action-oriented description>` without a task ID. Advisory (agent judgment).

## Agent skills

This repository uses the finolabs-vibecode skills. Routing on: use `fnl-coding-router`. Use Spec Kit. Pull requests follow `fnl-review-gate` "Pull requests"; reviewers may post code/security reviews. Help: `/fnl-ask`.

Review relay approval (owner, chat, 9 November 2026): on `fioenix/fn-ignis` pull requests, when an independent Codex reviewer returns its finished comment with `cannot-post: no-network`, the coordinator may relay that comment once per review run through `post_review.py`, unchanged from its first-line marker, with a second line naming the reviewer, the coordinator and this approval. This covers code and security reviews; it grants no merge, deploy or other authority.
