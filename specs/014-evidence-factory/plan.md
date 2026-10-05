# Implementation Plan: Ignis Relay — Observable Research Mission

**Branch**: `codex/ignis-evidence-factory` | **Date**: 2026-10-04 | **Spec**: [approved R1](spec.md)

**Status**: T001–T034 accepted:34/92. T034 current/pending/stale/history projection independently verified:396PASS0SKIP plus13 independentPASS and an actual newer-STARTED-history refusal probe. Nested Gap privacy P1 resolved with genuine RED regression. US1 and T032/T033 are committed; T035–T040 remain required for US3. Commit each task; PR after full spec completion. No UAT/shipment claim.

## Summary

Current acceptance update (2026-10-05): T001–T031 independently accepted:31/92. The first internal slice (US1) is implemented and automatically verified on frozen source:1348PASS3 disclosed conditional skips, zero failures/errors; final independent correction gate18PASS0SKIP. Canonical idle/STARTED/Unknown and actual persisted observation/qualification transitions pass through FastMCP, real HTTP and isolated Chromium on disposable SQLite file/private memory/local PostgreSQL. Unsupported research remains unavailable and strategic permission withheld. Changes are explicitly parked uncommitted/unmerged. This closes US1 only; later stories, full-feature UAT and shipment remain unaccepted.

Historical T022 acceptance follows.

Current acceptance update (2026-10-05): T022 joins both submission use cases to narrow atomic fact/event operations through a structural port and workspace delegates. Typed transaction-window stale errors retain CONFLICT/STALE_FRAME, with no submission write; existing final-readback withholding and audit history remain unchanged. Independent re-review closes the sole P2; all314 scoped cases pass with no skip, including6 new RED-before-fix race controls. Full3375 cases:3168PASS187FAIL10ERROR10SKIP2warnings598.10s. Exact36 original producer RED nodes pass; no new failed/error node. Remaining failures belong to future HTTP/projection/browser implementations or inherited isolated-settings/doc checks; clean-user bootstrap setup remains unaccepted. Canonical ledger22/92; T023 next, no integration/release action.

Historical T021 acceptance follows.

Current acceptance update (2026-10-05): T001–T021 accepted,21/92. T021 resolves all24 collection producer failures; final producer plus18 added controls:75PASS12FAIL0ERROR0SKIP. All12 residual failures are unchanged T022 qualification/claim cases. Independent cancellation finding resolved; host test gate adaptation preserves assertions and passes independent review. Final related regression135PASS2SQLite-specificSKIP. Full before host gate adaptation:3148PASS201FAIL10ERROR10SKIP2warnings542.96s; no full-suite GREEN. Two host gate timeouts were subsequently resolved by the focused run;10 clean-install setup errors and inherited environment/doc checks remain explicitly disclosed. Work is local/uncommitted and parked at the accepted task boundary; T022, old-schema, minimum-runtime, UAT and integration remain open. Historical T020:direct32PASS, covering273PASS0SKIP, unit146PASS; T016 then33PASS36FAIL. Historical T019:direct56PASS, covering591PASS11SKIP, full2501PASS231FAIL587SKIP2warnings. Historical T017 acceptance follows.
T017 initial review found four Important test gaps; scoped R1 review addressed all four
without new breakage. Final source77f7311e..., reporte4f15e71..., review90e8a33b....
Earlier R1 selected28:17 missing-listener RED/11 assertion-readiness PASS; final logging-only
selected4:4 missing-listener RED, zero errors/skips. These are distinct tested revisions,
not HTTP/security GREEN. Short-expiry stability and HEAD security/refusal Minor controls
remain T024/final review. Runtime, browser, lifecycle, security and integration stay open.

Historical T016 acceptance (2026-10-05):
T016 initial review found five Important test-contract gaps; R1 addressed four and R2
closed the zero-delta preservation residual, with no new breakage. R1 actual66 nodes:
36 expected missing-producer RED/30 PASS; final R2 narrow6:3 no-op PASS/3 positive-delta
missing-receipt RED, cleanup verified. Final source253333a8..., report0b440ed3...,
scoped review02c83702.... Historical T015 evidence remains revision-specific.
T016 accepts test design only; T019–T022 producer/schema compatibility, viewer, UAT,
full regression and integration remain open. No broader final-revision GREEN claim.

The outcome is an inspectable, light-mode observatory of a real assigned research mission: collection facts, specialist work, counterevidence and evolving findings reach the viewer without manufacturing activity or bypassing Claim Ledger. Acceptance requires a real concurrent research scenario, sequential fallback, one bounded follow-up, privacy tests and rendered UAT; a static animation is insufficient.

Add typed operational records alongside canonical evidence, an explicit host-work protocol and a separate finite GET-only loopback viewer. The host performs semantic research and actual delegation; Ignis records and validates receipts, performs deterministic authorized collection and builds the display. Operational events are committed with the facts they describe. The viewer uses a coherent no-bootstrap read boundary and never starts work.

Implement in three vertical slices after plan approval and task generation:

1. Coherent persisted telemetry, no-write viewer and the evidence journey.
2. Host research assignments, real work/handoffs, finding revisions and current-frame claim gates.
3. Bounded child-mission follow-up, complete lifecycle/security/concurrency UAT and integration.

The first slice is useful but does not close Spec 014. New APIs below are proposals, not installed tools. No release version is selected.

## Technical Context

**Language/Version**: Python >=3.11; existing typed domain/application ports; plain browser JavaScript, SVG and CSS. Local planning environment is Python 3.13; minimum-version CI remains required.

**Primary Dependencies**: Existing FastMCP, Jinja2, psycopg, SQLite and template infrastructure. Lock and installed package inspection found FastMCP 4.0.4; uv.lock records Jinja2 3.1.6. No new dependency, frontend framework, model SDK or hosted server is proposed. Standard-library HTTP is restricted to loopback and is not a public deployment solution.

**Storage**: Configured SQLite or PostgreSQL, canonical source/observation/mission evidence and Claim Ledger retained. Add operational tables and narrow transactional write/read ports on both backends. No legacy evidence rewrite, backfill of imaginary timestamps or replacement corpus.

**Testing**: pytest regressions and dual-backend behavioral contracts; Playwright rendered scenarios using existing tooling; actual declared host concurrency UAT; live-source UAT only under separate current authorization. A recorded replay is not the acceptance substitute.

**Target Platform**: Local MCP process with browser-accessible loopback viewer. No remote multi-tenant service, desktop-client config change or always-on worker.

**Project Type**: Existing agent harness plus local read-only product surface, not a new agent platform.

**Performance Goals**: SC-008/013 rendering <=5 seconds after successful coherent read; SC-005 >=50 FPS over 30 seconds on a named reference machine. Bound packet rendering with disclosed aggregation, not fabricated throughput. Polling cadence and render cap are implementation constants to be selected and measured during task design, not claims of achieved performance.

**Constraints**: Finite viewer capability; no automatic reads/motion when hidden, closed, refresh-paused or expired; no bootstrapping on viewer open; stale strategic permission withheld; finite host authority and cumulative collection reservations; masked typed projections; no private reasoning. Maintain all existing tool signatures and connector tiers.

**Scale/Scope**: One explicitly selected mission per viewer capability. Related child missions require separately scoped inspection. Events and inspection are bounded/paged; animation aggregates large sets while exposing exact counts and identities. No full-corpus DOM or unrestricted event dump.

## Constitution Check

Pre-research and post-design checks are design checks, not runtime acceptance results.

| Principle | Pre-research | Post-design obligation |
|---|---|---|
| I — Mission-bound autonomy | Compatible with approved R1 | Explicit assignment, finite authority, no viewer-triggered work, deterministic collectors; research end fences all new work. |
| II — User-controlled connectors | Preserve tiers/contracts | No new source/session permissions; child follow-up admission checks source, credential, scope and cumulative budget before any probe. |
| III — Evidence and falsification | Reuse canonical identities | Atomic durable-fact events, coherent read high-water, immutable input references, alternatives/counterevidence, fail-closed current-frame claims; SQLite/PostgreSQL parity. |
| IV — Maintained artifacts | Preserve report-source boundary | Runtime template and FINOLABS partial under maintained HTML directory; generated exports remain ignored. No parallel Mermaid/ad hoc report. |
| V — Simplicity and type safety | Existing stack sufficient | Four additive typed MCP operations; existing composition and evidence ports extended narrowly; no model runtime or agent scheduler. |
| VI — Migration/release evidence | No evidence-transforming change now | Schema scripts planned only after approval; publish additive-schema invariants and rollback/read compatibility. Any evidence transformation needs separate owner ruling. Integration and release remain separately evidenced. |

No constitution exception is requested. A review finding that requires an exception blocks implementation until recorded owner approval.

## Project Structure

### Documentation

```text
specs/014-evidence-factory/
  spec.md                         # Approved requirements
  plan.md                         # Owner-approved technical design
  research.md                     # Repository-grounded choices and alternatives
  data-model.md                   # Workflow, revision and transaction boundaries
  contracts/relay-viewer.md        # Read tools, HTTP and UI protocol
  contracts/research-work.md       # Host work and findings protocol
  contracts/follow-up.md           # Child collection admission and provenance
  quickstart.md                   # Validation guide and acceptance mapping
  checklists/requirements.md       # Existing scope checklist
  tasks.md                        # Dependency-ordered implementation work
```

`tasks.md` is generated under Spec Kit after explicit plan approval; unchecked tasks are not implementation evidence.

### Proposed source locations, not created in planning

```text
src/ignis/domain/                  # Typed work/event/finding/lifecycle models
src/ignis/application/ports/       # Narrow workflow transactions and read projection
src/ignis/application/use_cases/   # Record work, project viewer, admit follow-up
src/ignis/infrastructure/persistence/
                                  # SQLite/PostgreSQL atomic operations and read adapters
src/ignis/infrastructure/templates/html/
                                  # Maintained relay template; existing FINOLABS partial
src/ignis/interfaces/mcp/          # Four additive tool handlers and lifespan ownership
src/ignis/infrastructure/          # Separate bounded loopback viewer service
sql/                              # Future additive PostgreSQL schema, no evidence rewrite
tests/unit/                       # Domain, masking, transitions, template/security contracts
tests/integration/                # DB parity, MCP, lifecycle, viewer and follow-up tests
```

Follow existing file naming/composition after tasks identify exact ownership. Extend existing evidence decoders rather than creating another source policy.

## Design and delivery boundaries

- Proposed tools: `open_mission_relay`, `get_mission_relay_snapshot`, `record_mission_research_work`, `execute_mission_follow_up`. No existing tool is renamed, removed or widened.
- Viewer transport owns only capabilities and rendering; host-work writes are MCP operations outside HTTP. Task Relay's one-answer POST transport is untouched.
- FastMCP lifespan owns the async loop and viewer shutdown. HTTP threads submit bounded read coroutines to that loop; they never borrow a PostgreSQL pool across loops. Cancel pending reads and revoke capabilities before loop teardown.
- A read-only adapter refuses absent/old schema. SQLite file connections use read-only access; in-memory support uses a coherent snapshot of the already initialized store without bootstrapping canonical storage. PostgreSQL reads use read-only repeatable-read transactions. Do not call lazy repository initialization from viewer opening or refreshing.
- Progress mutation and related evidence/work/finding mutation share one transaction. Existing multi-commit mission execution must receive narrow transaction operations; filesystem journals are not the event bus. No promise of a globally atomic collection pass.
- Collection status, research authority and viewer lifetime remain independent. A recorded writer claim is not proof of active work. Bounded host activity receipts distinguish host-reported from harness-observed facts.
- Follow-up uses a new child collection mission with inherited/tightened authority and a persisted parent relationship; the completed parent is never reopened. A child frame does not permit a parent claim. Related results are labeled with their mission/frame, not blended into one apparent permission context.
- No host semantic classification or provider call occurs in the viewer. Host judgment uses existing analysis/qualification/claim responsibilities; deterministic admission and lifecycle validation stay in code.

## Integration and approval gates

Owner approved this plan on 2026-10-04 in response to the question explicitly covering the four additive public tools and workflow schema. Proceed to `speckit-tasks`; runtime execution remains the next phase. Applying schema to Supabase or using actual social sessions follows the applicable explicit authority boundary. No such operation occurs during planning or task generation.

Before calling the feature integrated: converge against all FR/SC, review/security findings resolved or explicitly accepted, actual UAT evidence attached, focused PR merged and post-merge checks verified in canonical backlog. Do not equate local checks with shipping or silently select a release/version.

## Complexity Tracking

No exception. The added workflow tables and four tools pay for requirements FR-019–029, not a speculative scheduler. The cost falls on repository transaction implementations and hosts recording trustworthy receipts; the benefit is a truthful viewer and bounded research handoffs.
