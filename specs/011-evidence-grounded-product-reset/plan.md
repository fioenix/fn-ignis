# Implementation Plan: Evidence-Grounded Product Reset

**Branch label**: `011-evidence-grounded-product-reset`  
**Date**: 2026-09-29  
**Spec**: [spec.md](spec.md)  
**Approved input**: [Product Proposal](../../docs/PRODUCT_PROPOSAL.vi.md)

## Summary

Deliver one mission-bound Ignis product that starts only from an explicit task, offers independent
social collection and Senior Market Analytics capabilities, and prevents strategic claims until an
auditable evidence frame passes deterministic sufficiency gates. The implementation extends the
Spec 008 mission-evidence foundation with a Mission Manifest, expanded hypothesis register,
counterevidence qualification, complete channel outcomes, and a persisted Claim Ledger. In the same
breaking release it removes the worker, scheduler, daily-discovery runtime, and eight unscoped MCP
operations without compatibility aliases.

The finished state is observable when an idle installation performs zero research work; tactical
connector probes still work independently; a Market mission either produces traceable claims with
visible contradiction or a Gap Report with no strategic verdict; and every public surface describes
the same product. The first validation boundary is five real Vietnam consumer-market missions, not
generic benchmark coverage or monetization.

## Technical Context

**Language/Version**: Python 3.11+ under the repository's current `>=3.11` contract  
**Primary Dependencies**: FastMCP, Pydantic 2, Pydantic Settings, existing HTTP/browser connector
stack; no new required runtime dependency  
**Storage**: SQLite by default; PostgreSQL 16 as production backend; workspace run journals and
generated HTML as projections, not competing canonical stores  
**Testing**: pytest and pytest-asyncio; unit, integration, SQLite/PostgreSQL parity, public MCP
inventory, clean-install, deterministic artifact, and repository-convention gates  
**Target Platform**: self-hosted MCP server on supported macOS/Linux agent hosts; no resident worker
process  
**Project Type**: Python package, FastMCP server, CLI/bootstrap integration, deterministic HTML
artifact builders, and two host-agent skill packages  
**Performance Goals**: zero connector or LLM work while idle; preserve existing non-I/O read-path
latency targets; process semantic submissions in bounded batches of 1–50; reopen persisted missions
without re-running AI judgments  
**Constraints**: zero-token deterministic ingress; explicit authority for browser sessions, tokens,
paid quota, migration application, and data deletion; fail-closed strategic analysis; no arbitrary
unverified dataset as primary evidence; no hidden scheduler; no second report source outside
`src/ignis/infrastructure/templates/html/`; dual-backend behavioral parity  
**Scale/Scope**: one breaking product cutover, 47-operation starting MCP inventory, eight planned
removals, two planned additions, mission evidence schema extensions, two capability skills, and five
pilot mission conditions for the Vietnam consumer-market beachhead

## Constitution Check

*Gate result before Phase 0 research: PASS. Re-checked after Phase 1 design: PASS.*

| Principle | Design response | Result |
|---|---|---|
| I. Mission-Bound Autonomy and Zero-Token Collection | Every run begins from an explicit atomic request or confirmed manifest; the worker, scheduler, recurring triggers, and follow-up loops are removed | PASS |
| II. Pluggable and User-Controlled Connectors | Atomic connector tools remain independently callable; authority tier and every declared channel outcome remain explicit | PASS |
| III. Evidence-First Research and Falsification | Mission evidence, hypothesis alternatives, counterevidence, missingness, sufficiency, and claims are persisted against one immutable frame | PASS |
| IV. Deterministic Artifact Builders | Only maintained builders and templates under `src/ignis/infrastructure/templates/html/` render runtime reports | PASS |
| V. Simplicity, Surgical Changes, and Type Safety | Extend Spec 008 records and repository ports; add no AI provider or parallel workflow engine; use typed enums and payloads | PASS |
| VI. Evidence-Gated Migration and Release | Migration 025 is planned but not written or applied; removal, deletion, version, and release remain explicit owner gates | PASS |
| Outcome thinking | Success is zero idle work plus either traceable current-frame claims or an explicit Gap Report | PASS |
| Design thinking | Founder/operator/analyst workflows expose friction, cost, missing authority, and the next useful probe | PASS |
| Critical thinking | Every Market mission records alternatives and null, seeks contradiction, and separates observation from inference | PASS |

No constitutional exception is requested. The plan deliberately stops before four owner-controlled
actions: writing or applying migration 025, changing/removing existing MCP signatures, deleting
baseline data, and preparing a version/tag/release.

## Project Structure

### Documentation for this feature

```text
specs/011-evidence-grounded-product-reset/
├── spec.md
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── checklists/
│   └── requirements.md
└── contracts/
    ├── mission-bound-public-surface.md
    ├── hypothesis-and-qualification.md
    └── claim-ledger-and-analysis-output.md
```

`tasks.md` is intentionally absent. It belongs to the subsequent `/speckit-tasks` phase.

### Source code affected by implementation

```text
src/ignis/
├── domain/
│   ├── entities.py
│   ├── research_workspace.py
│   └── value_objects.py
├── application/
│   ├── ports/
│   │   ├── repository_port.py
│   │   └── research_workspace_port.py
│   └── use_cases/
│       ├── confirm_market_brief.py
│       ├── create_attention_mission.py
│       ├── execute_mission.py
│       ├── get_evidence_qualification_batch.py
│       ├── submit_evidence_qualifications.py
│       ├── get_mission_analysis.py
│       ├── submit_mission_claims.py        # planned
│       └── get_mission_claims.py           # planned
├── infrastructure/
│   ├── persistence/
│   │   ├── sqlite_repository.py
│   │   ├── postgres_repository.py
│   │   └── workspace_repository.py
│   └── templates/html/
│       ├── _fino_theme.html
│       └── mission_report.html
└── interfaces/
    ├── mcp/server.py
    └── cli/                                # scheduler removal and retained bootstrap/diagnostics

sql/
└── 024_evidence_grounded_claim_ledger.sql  # planned; owner gate before creation/application

tests/
├── unit/
└── integration/

.agents/skills/
├── ignis-collect/                          # planned
└── ignis-analyze/                          # planned
```

Other required cutover consumers include `pyproject.toml`, `docker-compose.yml`, `env.example`,
bootstrap/setup scripts, package manifests, `README.md`, `README.vi.md`, `AGENTS.md`, `CLAUDE.md`,
the canonical backlog, and curated case-study generators. Their changes remain bounded to removing
the obsolete runtime contract or documenting the new one.

**Structure decision**: retain the current layered package and repository ports. The new behavior is
an extension of mission evidence, not a new service or workflow engine. The two skill packages are
thin host instruction surfaces over the same MCP and persistence contracts; they do not own policy,
thresholds, or a second schema.

## Phase 0: Research Decisions

The resolved research is recorded in [research.md](research.md). The controlling decisions are:

1. One mission-bound product replaces the optional always-on track.
2. Eight unscoped radar operations are removed together after the implementation-time owner gate.
3. Spec 008's immutable mission-evidence core remains authoritative and is extended rather than
   replaced.
4. Planned migration 025 is additive for mission analysis and does not ingest legacy baseline data.
5. Host agents perform bounded semantic judgment; Ignis owns typed policy, persistence, and audit.
6. Contradiction is a first-class evidence relation, not negative sentiment.
7. A persisted Claim Ledger is the report authority; narrative HTML is a projection.
8. `ignis-collect` and `ignis-analyze` share one evidence contract.
9. Legacy baseline disposition begins with an inventory-only dry run.
10. Product validation precedes monetization and covers five specified mission conditions.

No research item remains `NEEDS CLARIFICATION`. Competitive findings are inherited from the approved
proposal and retain their documented limitations; competitor behavior is not used as implementation
proof.

## Phase 1: Design and Contracts

### 1. Mission-bound execution boundary

Add a typed Mission Manifest containing outcome, allowed resources, authority, output, stop
conditions, retention, and analysis policy. Persist its canonical digest with every surfaced mission.
An atomic tactical probe carries an equivalent ephemeral boundary but does not need a full Market
Brief. Every use case refuses work after a terminal mission state unless a new explicit run is
requested.

Remove runtime registration and packaging for scheduled work only after a consumer audit covers:

- scheduler CLI and autonomous-discovery use case;
- Docker worker service and package entrypoints;
- `IngressTrigger.SCHEDULED` and scheduled-only filtering/configuration;
- daily-discovery builders/templates and their callers;
- canonical guides, setup scripts, manifests, tests, and examples.

The exact public boundary is [contracts/mission-bound-public-surface.md](contracts/mission-bound-public-surface.md).

### 2. Hypothesis register and collection planning

Extend confirmed Market Brief revisions with two or more alternatives, a null hypothesis, kill
criteria, and a revision rule. Include all fields in the immutable frame fingerprint. A deterministic
collection-plan projection maps each probe to the hypothesis and evidence role it can discriminate,
then persists its digest on the run outcome and its readable form in the collision-safe journal.

Legacy Briefs remain auditable but require a new revision before they can authorize the new strategic
analysis contract. No fallback text or inferred alternatives are generated.

### 3. Complete channel outcomes

Persist exactly one outcome for every manifest-declared channel. Extend the current outcomes with
`FAILED`, `NOT_REQUESTED`, `scope_attestation`, `note`, and `collection_plan_digest`. Only exact-frame
`EMPTY_NO_DATA` represents measured absence; all other unavailable or partial states are missingness.

This state model must be implemented identically in SQLite and PostgreSQL and returned by every
analysis/artifact boundary.

### 4. Counterevidence qualification

Extend evidence qualification with `QUALIFIED_CONTRADICTION`, `hypothesis_target`, and
`evidence_role`. Keep semantic classification in the host-agent batch flow, but keep validation,
idempotency, current-frame checks, and sufficiency consequences in deterministic code. Do not add an
embedded LLM provider or free-form prompt storage.

The typed rules are [contracts/hypothesis-and-qualification.md](contracts/hypothesis-and-qualification.md).

### 5. Evidence frame, sufficiency, and Claim Ledger

Derive a canonical evidence-frame digest from the Mission Manifest, confirmed Brief revision,
collection plan, current observations, qualifications, and channel outcomes. Any constituent change
invalidates old claims for current rendering.

Add `mission_claims` and `mission_claim_evidence` persistence behind repository ports. The host may
submit candidate claims, but deterministic validation decides `PERMITTED` or `WITHHELD`. Persist both
states for audit; only current-frame permitted claims render as strategic conclusions. When required
evidence is insufficient, derive a Gap Report and omit forbidden verdicts entirely.

The input, output, and artifact rules are
[contracts/claim-ledger-and-analysis-output.md](contracts/claim-ledger-and-analysis-output.md).

### 6. Two capabilities, one product contract

Package two agent-facing skills:

- `ignis-collect` selects authorized atomic connectors or one mission ingress run, returns provenance
  and channel outcomes, and never writes a strategic verdict.
- `ignis-analyze` frames the Market Brief, drives bounded qualification and candidate-claim
  submission, and renders only what the current evidence frame permits.

Both skills call the same MCP tools and use the same typed records. Neither contains thresholds,
connector credentials, duplicated templates, or independent evidence policy. Skill evaluation must
include misuse cases: arbitrary external data, an auth-blocked channel, all-confirmatory queries, and
an attempt to narrate around `INSUFFICIENT_EVIDENCE`.

### 7. Deterministic artifacts

Refactor `mission_report.html` and its builder to render the Claim Ledger, counterevidence, channel
coverage, limitations, and decision conditions. An insufficient mission renders a Gap Report and
does not instantiate forbidden score sections. An Attention artifact remains non-commercial.

Before removing `trend_card.html`, `trend_dashboard.html`, or `trend_graph.html`, trace every consumer.
Remove only templates made unreachable by the eight-operation cutover; retained mission visuals stay
under the canonical template directory and FINOLABS token contract.

### 8. Legacy baseline disposition

Build an inventory-only command or use case that classifies legacy scheduled records by provenance,
retention obligation, reproducibility, and remaining product value. Its default output is a
recoverable manifest of archive candidates and deletion candidates; it writes no data and never
promotes a record into mission evidence.

Archival implementation, target-specific deletion, and post-action verification are separate tasks
that require explicit owner authorization. Migration 025 does not include baseline disposition.

### 9. Validation and release sequence

Validation proceeds in this order:

1. Unit contracts for manifests, hypothesis frames, channel states, qualifications, claims, and Gap
   Reports.
2. SQLite/PostgreSQL repository parity and migration rehearsal using synthetic evidence.
3. MCP inventory and clean-bootstrap tests proving no worker or schedule is installed.
4. Deterministic HTML artifact tests proving current-frame claims and contradiction render, while
   forbidden sections are absent under insufficiency.
5. Five real, explicitly authorized Vietnam consumer-market pilot missions: sufficient multi-source,
   required-channel auth block, high-volume low relevance, contradictory signals, and missing
   decision-critical metric.
6. Formal breaking-release preparation only after the owner approves the MCP removal set, migration,
   version bump, tag, and release.

The runnable acceptance map is [quickstart.md](quickstart.md).

## Delivery Slices

### Slice A — Governance and public inventory

- Reconcile active guidance with constitution 2.0.0 and the accepted ADR.
- Freeze the starting MCP, CLI, config, packaging, template, and documentation consumer inventories.
- Obtain the owner gate for the exact eight-operation removal set before source changes.

**Evidence**: checked inventory artifact and public-contract test that fails against the old surface.

### Slice B — Schema and domain contracts

- Obtain approval to write migration 025.
- Add Mission Manifest, expanded Brief, channel outcomes, contradiction, Claim Ledger, and repository
  contracts on both backends.
- Rehearse migration projections, counts, constraints, and digest without production data.

**Evidence**: dual-backend tests and deterministic rehearsal manifest.

### Slice C — Application and MCP behavior

- Enforce mission boundaries and terminal stop behavior.
- Extend qualification, sufficiency, Gap Report, claim submission/read, analysis, and artifact use
  cases.
- Remove the approved unscoped operations and all scheduler/worker call paths without aliases.

**Evidence**: public MCP inventory, idle-zero-work test, tactical probe test, and fail-closed analysis
tests.

### Slice D — Skills and artifacts

- Add `ignis-collect` and `ignis-analyze` as thin, shared-contract instruction surfaces.
- Update maintained mission templates; remove only consumer-proven unreachable trend templates.
- Update canonical English developer guidance and Vietnamese market-facing documentation.

**Evidence**: skill misuse evaluations, deterministic artifact snapshots, link checks, and clean
bootstrap readback.

### Slice E — Pilot and release gate

- Run the five authorized pilot conditions and record mission/frame identities, not only screenshots.
- Decide separately whether legacy baseline candidates are archived or deleted.
- Prepare the formal breaking release only after owner authorization and all repository release gates.

**Evidence**: pilot decision log, public-install verification plan, and explicit unresolved risks. A
local green suite is not release completion.

## Post-Design Constitution Re-check

- No design introduces work without an explicit task.
- No design adds token use to deterministic collection.
- Connector authority and incomplete coverage stay visible.
- Counterevidence and missingness are persisted rather than hidden in prose.
- Runtime HTML remains template-owned in the canonical directory.
- The plan extends existing mission evidence instead of creating a second product stack.
- Migration, signature removal, deletion, and release all retain their owner gates.

Result: **PASS with no exception**.

## Complexity Tracking

No constitution violation requires justification. The two new Claim Ledger operations are the
minimum typed boundary needed for a host agent to submit semantic analysis without making transient
chat prose canonical. The alternative—letting `get_mission_analysis` infer or persist hidden prose—
would erase authorship, frame binding, and auditability.

## Explicit Non-Goals

- Recurring monitoring, alerts, daily discovery, or a paused worker mode.
- Analysis of arbitrary purchased or uploaded datasets as primary Market evidence.
- A bundled AI provider or hidden automatic prose generator.
- Universal industry or geography claims from the Vietnam beachhead pilot.
- Monetization, hosted multi-tenancy, or enterprise administration in this feature.
- Actual migration creation/application, baseline deletion, version bump, tag, or release without
  their separate owner decisions.
