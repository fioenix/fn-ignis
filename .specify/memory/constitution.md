<!--
Sync Impact Report
- Version change: 2.1.0 -> 2.2.0
- Modified principles:
  - I. Mission-Bound Autonomy and Zero-Token Collection: Ignis still holds no scheduler, worker or
    background loop; a user MAY now ask their own agent to run one watchlist on a recurring host
    schedule, each firing a separate explicit task (Spec 016 amendment, Change 1).
  - III. Evidence-First Research and Falsification: the ingestion-clock rule now names collection
    windows and evidence frames, and a listening period places observations by publication time with
    the basis stated (Spec 016 amendment, Change 2).
- Added principles: VII. No Author Identity at Rest (Spec 015, T036). Review of the ratification
  PR added three clarifications that match the shipped Spec 015 contract: declared accounts may be
  shown (FR-002, FR-016), atomic probes count voices with a response-scoped key never stored
  (research R9), and identity stored before Spec 015 is held unchanged pending OG-3 (FR-015).
- Removed sections: the "Proposed Amendment (not ratified)" appendix, now folded into VII
- Bump rationale: MINOR. One new principle and two narrowed or clarified rules for a new use; no
  principle is removed or made incompatible. Owner ratified all three on 2026-10-21.
- Templates checked: .specify/templates/plan-template.md derives its Constitution Check gates from
  this file at plan time ("[Gates determined based on constitution file]"), so it needs no edit;
  spec-template.md, tasks-template.md and checklist-template.md carry no wording on I, III or VII.
- Dependent documents updated: CLAUDE.md (Architecture, Operational Boundary), AGENTS.md section 1,
  docs/decisions/2026-09-29-mission-bound-evidence-grounded-ignis.md (pointer to the 2026-10-21
  decision), specs/016-watchlist-listening/constitution-amendment.md (status Ratified).
- Dependent documents checked, unchanged: README.md and docs/USER_GUIDE.md already describe author
  identity removal; tests/unit/test_ignis_skills.py keeps "daily" and "scheduler" out of the
  collection and analysis skills, and routine guidance stays in the Spec 017 guide.
- Follow-up TODOs: OG-3, the disposition of identity stored before Spec 015, remains an open owner
  decision (Spec 015 T034); VII records that data as an exception until then.
-->
# fn-ignis Constitution

This constitution defines the non-negotiable product, architecture, development, and governance
principles for `fn-ignis`.

---

## Core Principles

### I. Mission-Bound Autonomy and Zero-Token Collection (NON-NEGOTIABLE)

- Ignis MUST start collection or analysis only after a user or host agent explicitly assigns a
  task. Ignis itself MUST NOT contain a scheduler, worker, always-on radar or background
  collection loop, and MUST NOT discover topics on its own.
- A user MAY ask their own agent to run one watchlist on a recurring schedule through the host's
  native scheduler. Each firing is a separate explicit task: one watchlist run, bounded by the
  watchlist version, the run's own stated authority and the per-channel daily request ceilings.
  An agent MUST NOT set up, widen or resume such a routine without the user's explicit request,
  and the user MUST be able to see, pause and remove it in the host.
- Once assigned a task, Ignis MAY autonomously select and execute the bounded collection and
  analysis steps needed to satisfy that task, subject to connector authorization and evidence
  gates.
- Connectors and ingestion ETL MUST run deterministically without consuming LLM tokens. Agent LLMs
  participate in semantic judgment, strategic reasoning, and artifact presentation, not raw
  collection.
- A completed task MUST stop consuming connector quota and compute. A new task requires a new
  explicit trigger.

### II. Pluggable and User-Controlled Connector Architecture

- Every platform connector MUST implement the connector port and remain independently callable for
  tactical collection or as part of a research mission.
- Circuit breaking and error isolation are required: one platform failure MUST NOT terminate healthy
  connector work or be silently reported as complete coverage.
- Browser sessions, platform tokens, paid quotas, and other user-controlled resources MUST be used
  only when the task explicitly places them in scope and the repository's authorization boundary is
  satisfied.
- Connector availability, authentication state, rate limits, and missing channels MUST remain
  visible to the user and to downstream evidence qualification.

### III. Evidence-First Research and Falsification

- SQLite is the zero-configuration default; PostgreSQL with optional TimescaleDB is the production
  backend. Behavioral storage contracts MUST run on both.
- Persistence MUST separate one canonical external `source`, each immutable `observation`, and the
  exact `mission_evidence` association that used it. Runtime code MUST NOT maintain a second source
  identity or mission-ownership policy in titles, URLs, or legacy tables.
- Every strategic claim MUST trace to the mission evidence frame that supports it. Missing channels,
  failed probes, sample limits, and contradictory observations MUST remain first-class evidence.
- A mission MUST actively test its core hypothesis against counterevidence and at least one credible
  alternative explanation. It MUST NOT treat confirmation of the user's initial belief as the goal.
- Evidence qualification and verdict generation MUST fail closed: when required evidence is absent
  or insufficient, Ignis MUST return the gap and the next validation action instead of manufacturing
  certainty.
- Collection windows, evidence frames and every other time-window query MUST use an ingestion
  clock whose provenance is exact. Legacy observations whose ingestion time was never recorded keep
  `observed_at = NULL` with explicit provenance.
- A listening period (a calendar day, week or month of a watchlist) places each observation by its
  publication time when a plausible one exists, and otherwise by its ingestion date, flagged as
  such. The basis MUST be stated with every figure; publication time MUST NOT silently substitute
  for ingestion time anywhere else.

### IV. Deterministic Report Builders

- Research reports that Ignis issues, such as mission reports and Gap Reports exported through the
  MCP server, MUST be built from maintained builders and templates.
- HTML templates in `src/ignis/infrastructure/templates/html/` are the only research-report source
  committed as code. Agents MUST NOT regenerate a research report's full HTML/CSS ad hoc.
- A tracking artifact is a host agent's point-in-time rendering of a mission snapshot, not an Ignis
  research report, and this template rule does not govern it. Agents MAY render it in any form, but
  MUST follow the tracking guidance Ignis ships: show only states present in the snapshot, never
  present a withheld or stale claim as permitted, label the artifact as point-in-time, and keep it
  on the user's machine unless the user consents to each publication.
- Standalone documentation diagrams MAY live outside the report-template directory when they are not
  runtime report sources. HTML remains the canonical diagram source; exported SVG/PNG MAY be embedded
  in documents, and parallel Mermaid sources are prohibited.
- Report builders and templates MUST preserve layout fidelity, reproducibility, accessible output,
  and the vendored FINOLABS design tokens.

Rationale: a report Ignis issues must be reproducible and must not be rewritten into a different
claim. A tracking artifact draws its integrity from snapshot states and the shipped display rules,
not from a template.

### V. Simplicity, Surgical Changes, and Type Safety

- Runtime support is Python 3.11+ with explicit type hints and typed domain models where practical.
- New behavior MUST use the minimum coherent change needed to satisfy a measured contract. The
  project MUST NOT add speculative abstractions, workflows, or configuration.
- Domain vocabulary MUST remain data-driven and runtime-extensible; source code MUST NOT hard-code
  market terms, brand names, synonyms, or intent vocabularies.
- Contract changes MUST identify every consumer and prove behavioral parity or an intentional
  breaking boundary before release.

### VI. Evidence-Gated Migration and Release

- A migration that transforms persisted evidence MUST publish its projection, counts, invariants,
  and deterministic digest before production data is changed.
- Production baselines MUST come from the exact quiesced snapshot being migrated. A tracked rehearsal
  baseline documents policy; it is not a production reference.
- Runtime safety guards are fail-closed backstops, not permission to violate the documented migration
  sequence.
- Work is not shipped until it is merged, deployed, migrated where required, verified from the
  production or public surface, and activated.

### VII. No Author Identity at Rest

- Ignis studies markets in aggregate and MUST NOT keep who said something. Usernames, account and
  channel identifiers, display names, profile links, avatars, and handles in links or in content
  text MUST be removed before an observation is stored, and MUST NOT appear in a tool response,
  report or log, except an account the requester declared for that mission.
- Distinct voices MAY be counted only through per-mission markers under a key that belongs to one
  mission, is encrypted at rest, and is destroyed with the mission's evidence. An atomic probe
  outside a mission MAY count them only with a key scoped to one response and never stored.
  Markers MUST NOT be linkable across missions or responses.
- The only identities Ignis MAY keep are accounts a requester declares for one mission; a
  declaration applies only to content collected after it and MUST be withdrawable without
  rewriting evidence.
- Content with no content reference MAY be kept as context, never as support for a claim.
- Every new connector MUST be covered by the author identity conformance check before it ships.
  Free-text personal names are outside this principle and MUST be documented as such.
- Author identity stored before this principle took effect is a recorded exception: it stays
  unchanged until the owner decides its disposition (Spec 015, OG-3), MUST NOT grow, and MUST NOT
  appear in a tool response, report or log.

---

## Product Reasoning Constraints

- **Outcome thinking:** Every mission, feature, and plan MUST state the decision outcome first and
  define observable evidence that proves the outcome was reached. Steps that cannot trace to that
  outcome MUST be removed.
- **Design thinking:** Ignis MUST be designed for the person making the decision. Research flows MUST
  expose collection cost, friction, missing data, and the next useful action instead of optimizing
  only for technical completeness.
- **Critical thinking:** Every mission MUST make assumptions explicit, search for disconfirming
  evidence, preserve competing explanations, and separate observation from inference.

The initial product beachhead is founder, operator, analyst, consultant, and small consumer-market
teams researching Vietnam. This constrains the first validation corpus and language experience; it
does not authorize claims of universal geographic or industry coverage.

---

## Technology Constraints

- **Language and runtime:** Python >= 3.11; `uv` is the preferred package manager.
- **Persistence:** SQLite or PostgreSQL 16; TimescaleDB and pgvector are optional backend
  capabilities, not requirements for zero-configuration operation.
- **Protocol:** Model Context Protocol through FastMCP.
- **Ingress libraries:** `google-api-python-client`, `feedparser`, `httpx`, and `playwright` where a
  user-requested connector requires a browser.
- **Research reports:** maintained single-file HTML templates using the vendored FINOLABS design
  tokens. Tracking artifacts are host-rendered under Principle IV.

---

## Governance and Spec-Driven Development

Large features use the Spec Kit artifact chain:

1. `/speckit-specify` — requirements and acceptance scenarios.
2. `/speckit-plan` — technical decisions and architecture.
3. `/speckit-tasks` — dependency-ordered work items.
4. `/speckit-implement` — implementation and tests.
5. `/speckit-converge` — code-to-spec gap assessment.

An amendment requires an explicit owner decision, a documented impact report, and a semantic version
bump: MAJOR for incompatible governance changes, MINOR for new or materially expanded guidance, and
PATCH for non-semantic clarification. Architecture and product ADRs MUST be reconciled with the
constitution; a superseded ADR remains in history and names the newer decision that replaces it.

Every plan and pull request MUST evaluate constitution compliance. An exception MUST identify who
pays the cost, its expiry condition, and the owner approval that permits it. Tests, configuration,
labels, and remembered command output are not evidence by themselves: run the command against the
surface that owns the claim, read the output, and record what was not checked.

**Version**: 2.2.0 | **Ratified**: 2026-08-31 | **Last Amended**: 2026-10-21

