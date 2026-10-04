# Feature Specification: Ignis Evidence Factory

**Feature Branch**: `codex/ignis-evidence-factory`

**Created**: 2026-10-04

**Status**: Draft — live scope selected; written design approval required

**Input**: Owner-requested Goal 2: a cinematic high-tech page visualizing Ignis collection, processing and analysis, with moving data blocks, streams, processing pools and separation, resembling a science-fiction factory. Continue after Goal 1 source integration.

## Outcome and audience

A person monitoring an explicitly selected real Ignis mission can follow its observed progress, inspect an observation's evidence role and understand why a conclusion is permitted or withheld. The page should feel like an instrumented futuristic research factory, not a generic dashboard or a demonstration labeled live. The owner selected a live mission dashboard rather than the proposed synthetic explanatory page.

The intended audience is founders, operators and analysts following their assigned research mission. They need to see genuine progress, source failures, qualification backlog and remaining decision gaps without interpreting internal logs. This audience is an assumption, not an independently measured user-research result.

## User Scenarios & Testing

### User Story 1 — Follow the evidence journey (Priority: P1)

A viewer explicitly selects a real mission, opens a bounded read-only viewing session and follows data blocks through collection, provenance, qualification, falsification and the claim gate as persisted facts change.

**Why this priority**: The cinematic effect must explain Ignis's differentiator: critical research on traceable observations, not automatic confirmation of a preferred idea.

**Independent Test**: Walk through all six scenes and identify each stage's input, output and reason for rejection or withholding without reading product documentation.

**Acceptance Scenarios**:

1. **Given** no task has started, **When** the page opens, **Then** collection is visibly idle and no real collector or quota operation starts.
2. **Given** a new coherent mission snapshot, **When** an observation or qualification changes, **Then** the corresponding transition is animated once with its actual provenance and evidence role.
3. **Given** conflicting observations, **When** the falsification stage is inspected, **Then** support and contradiction remain visible under the same qualification standard.

### User Story 2 — Inspect without being forced to watch (Priority: P2)

A viewer pauses visual motion or live refresh, selects a stage or observation, reads its real facts and resumes the viewer without starting, cancelling or repeating the research mission.

**Why this priority**: Constant movement without inspection would obscure the actual method and exclude users sensitive to motion.

**Independent Test**: Complete stage navigation and evidence inspection using only a keyboard and again with reduced motion enabled.

**Acceptance Scenarios**:

1. **Given** an active viewer, **When** motion is paused, **Then** moving blocks stop while real state remains inspectable; stopping refresh separately freezes the last snapshot and labels it paused, not live.
2. **Given** reduced motion, **When** the page opens, **Then** the complete method is accessible without continuous movement or camera sweeps.
3. **Given** a narrow viewport, **When** a stage is selected, **Then** controls and explanations remain readable without horizontal page overflow.

### User Story 3 — Recognize the data and conclusion boundary (Priority: P1)

A viewer can distinguish a current mission snapshot from a paused, stale or terminal snapshot, and understand why missing evidence does not become a recommendation.

**Why this priority**: A convincing factory visual must not manufacture a convincing market claim.

**Independent Test**: Inspect the insufficient-evidence ending and verify that no category winner, invented confidence or commercial verdict appears.

**Acceptance Scenarios**:

1. **Given** a selected mission, **When** any scene is viewed, **Then** mission/run identity, last successful read time and freshness state are visible; no synthetic data is substituted if reads fail.
2. **Given** unknown publication time or reach, **When** an observation is inspected, **Then** the value remains explicitly unknown, not zero or fresh.
3. **Given** insufficient evidence, **When** the final gate is reached, **Then** a gap and next validation action appear rather than a commercial verdict.

### Edge Cases

- Empty, unavailable and degraded channels must be distinguishable from healthy measured absence.
- Closing or hiding the page, ending its bounded viewing session or stopping refresh must stop viewer reads and unnecessary presentation work; the underlying mission is not cancelled or started by these actions.
- Missing fonts, network access or animation support must not remove the explanatory content.
- An excluded block remains inspectable; it does not silently disappear into a visually successful output.
- A collection terminal state stops intake animation but does not imply qualification or claim work has completed: those facts can be recorded later within the explicit viewing session.
- A dashboard reconnect, identical snapshot or repeated observation must not animate a duplicate arrival or duplicate count.
- A newer Brief/frame must invalidate displayed claim permission; records from different missions, runs or incompatible revisions must not be mixed into one apparent pipeline.
- Active-run progress without a complete evidence frame must remain pending; the preceding completed run must not masquerade as current-run success.
- Viewing an observation must not expose credentials, private messages or unmasked personal data.

## Requirements

### Functional Requirements

- **FR-001**: The page MUST present the six-stage task-to-claim evidence journey as one recognizable cinematic factory.
- **FR-002**: Data blocks MUST flow through visible processing pools and separate by their actual persisted evidence roles. Transitions MUST correspond to observed changes, not a repeating synthetic throughput loop. If particles aggregate observations, the mapping and exact total MUST be disclosed.
- **FR-003**: Each stage MUST expose what it receives, what it produces, why it matters and what can fail.
- **FR-004**: The page MUST preserve provenance, counterevidence, context-only and excluded roles; raw popularity MUST NOT become demand or claim permission.
- **FR-005**: A persistent header MUST identify the selected mission, current run when known, last successful read, displayed frame when available and current/paused/stale/terminal viewer status. Unknown runtime facts MUST be identified as unknown.
- **FR-006**: The initial product MUST be a read-only dashboard for a real explicitly selected Ignis mission, as selected by the owner on 2026-10-04. Synthetic demonstration and recorded replay are not substitutes for this acceptance scope.
- **FR-007**: The page MUST provide independent motion and live-refresh controls plus direct stage/observation inspection, with visible keyboard focus and no hover-only essential content. Controls MUST distinguish viewer actions from mission actions; no mission restart/cancel/collect button is included in this scope.
- **FR-008**: Reduced-motion viewing MUST preserve all information while disabling continuous block flow and cinematic camera movement.
- **FR-009**: Unknown metrics, unmeasured source windows, channel failures and missing hypothesis coverage MUST stay visible rather than being assigned flattering numbers.
- **FR-010**: The final gate MUST show an actual permitted claim with its bindings only when allowed by the current coherent evidence frame, or show a clear Gap Report. An incomplete/changed frame MUST withhold permission rather than reuse a stale claim.
- **FR-011**: The presentation MUST use the maintained FINOLABS product design system; mint is the everyday flow accent, while violet marks one high-stakes claim gate. Colour MUST have accompanying labels/shapes.
- **FR-012**: Merely opening, replaying or restarting the presentation MUST NOT start a connector, scheduler, authentication flow or paid operation.
- **FR-013**: No existing MCP signatures, connector tiers, persisted evidence, release versions or owner-client settings may change solely to implement the presentation.
- **FR-014**: The viewer MUST use a coherent mission-state boundary with freshness and revision identity; it MUST reject mismatched mission/run/frame snapshots. Observation arrivals, qualifications and claims MUST be idempotent across refresh, reconnect and reordered responses.
- **FR-015**: A missing persisted stage event MUST appear as unavailable or pending; the dashboard MUST NOT invent stage timestamps, active-processing status, completion percentages or confidence to fill the cinematic sequence.
- **FR-016**: A viewing session MUST have a visible finite boundary. Hidden/closed/expired/paused viewers MUST perform no refresh reads or continuous motion. Intake stops at collection terminal state; any subsequent qualification/claim updates remain separate facts within the authorized viewing session.
- **FR-017**: The read surface MUST protect selected mission scope, mask public-observation text as required and refuse unauthorized access. It MUST expose neither secrets nor write/collection operations.
- **FR-018**: ATTENTION and MARKET MUST retain their distinct semantics; an Attention observation or attractive animation MUST NOT be represented as qualified Market support.

### Key Entities

- **Viewing session**: Explicitly selected mission, finite observation boundary, refresh status and last successful read.
- **Mission snapshot**: Coherent mission/run identity, current persisted facts, freshness and evidence-frame identity where available.
- **Factory stage**: A named transformation with an input, output, explanation and visible failure state.
- **Evidence block**: An inspectable observation with source/query identity, time/metric missingness and qualification role.
- **Evidence frame**: The task-bound context against which qualification and claims are considered.
- **Decision gate**: A permitted claim with traceable bindings or a withheld outcome with explicit gaps.

## Success Criteria

### Measurable Outcomes

- **SC-001**: Every one of the six stages can be selected directly; a viewer can complete the explanatory journey in at most two minutes without waiting for animations.
- **SC-002**: All essential controls and explanations are available using a keyboard and in reduced-motion mode.
- **SC-003**: At 390, 768 and 1440-pixel viewport widths, all stage explanations and controls remain available without horizontal page overflow or clipped essential text.
- **SC-004**: Mission identity, freshness and viewer state are visible in every scene; no unsupported market verdict is emitted in the insufficient-evidence scenario.
- **SC-005**: On the declared reference machine, a 30-second presentation sample maintains at least 50 frames per second in its normal desktop mode; measurements must identify the machine and viewing conditions rather than claiming universal performance.
- **SC-006**: Source observations, exclusions, contradiction and gaps remain readable with animation paused and external resources unavailable.
- **SC-007**: Final acceptance includes actual rendered screenshots at the three viewport sizes, a keyboard/reduced-motion walkthrough, mode/data-integrity readback and complete regression results; a successful file open is not pixel proof.
- **SC-008**: In a controlled real mission run, collection, qualification and claim/gap changes appear within five seconds of a successful source read, with zero invented arrivals or duplicated transitions after reconnect/reordered snapshots.
- **SC-009**: A stopped, hidden, closed or expired viewer makes zero subsequent automatic reads until explicitly resumed within valid scope; it never invokes collection, credential use or mission writes.
- **SC-010**: During a failed refresh or incompatible frame transition, all stale claims lose displayed current permission immediately and the actual last successful read remains visible.

## Assumptions and boundaries

- Goal 1 source integration is PR #50/main a94db308. Accepted historical test-first and pixel-proof exceptions in that goal do not waive new Goal 2 visual acceptance.
- The owner selected real live monitoring, not demonstration. The viewer is read-only and opt-in; this written design still requires review before the technical plan and implementation.
- No dependency, new backend or real social account access is assumed. Technical choices belong in the subsequent plan after scope and design approval.
- Maintained report templates remain the only report source committed as code; generated exports remain local runtime output.
- Vietnamese is the audience-facing narrative; developer specifications and identifiers remain English.

## Storyboard — proposed experience, not an approved implementation

| Scene | Factory composition and movement | Meaning and inspection |
|---|---|---|
| 01 — Mission console | A dark instrument deck displays the explicitly selected task capsule. Dormant/active rails follow persisted run state, not a Play command that starts collection. | Actual outcome, audience, hypotheses, authorized sources and stop conditions. No always-on collection. |
| 02 — Source intake | Source docks send newly persisted observations down luminous rails into a receiving pool once. An unavailable dock has no fabricated stream. | Actual query, count and channel state; missing in-flight telemetry stays unavailable. Collection is not yet market evidence. |
| 03 — Provenance chamber | Blocks settle into an indexed pool; each opens into source, observation and task-binding layers. Unknown fields remain visibly unset. | Identity, collection time, source time, measurement provenance and masking. |
| 04 — Qualification separator | Newly persisted judgments move blocks out of the unassessed pool into support, contradiction, context or exclusion lanes; labels and geometry accompany colour. | Actual judgment and reason in the current frame. Rejected/unassessed data stays inspectable; the viewer does not classify it. |
| 05 — Falsification reactor | Support and contradiction orbit the same hypothesis chamber. Alternative/null routes stay visible; uncovered routes remain incomplete. | Competing explanations, identical evidentiary standards and remaining hypothesis gaps. |
| 06 — Claim airlock | One high-stakes gate admits a real current permitted claim or stops at actual gaps/pending assessment. Intake can be complete while qualification/claims still change. | Current frame bindings, limitations and next validation action; no endless output loop or invented research completion. |

### Scope alternatives

The following alternatives were considered before the owner selected option 3; options 1 and 2 are not an approved replacement.

1. **Explanatory cinematic demonstration**: Smallest presentation scope, synthetic data clearly labeled, no runtime wiring. Cost: it explains the method but cannot report an actual task's progress.
2. **Recorded mission replay**: Real persisted lineage with an explicit snapshot/replay boundary. Cost: privacy, sanitization and frame-binding requirements; cannot be called live.
3. **Live operations dashboard — owner selected**: Actual ongoing mission state, failures and freshness in a read-only viewer. Cost: a coherent live read/authority contract and explicit unavailable-stage handling, broader than presentation alone. Mission mutation controls remain excluded.

## Clarifications

### Session 2026-10-04

- Q: Which presentation scope should be built first? → A: Owner selected "Dashboard theo dõi mission thật" through the direct question on 2026-10-04. This supersedes the earlier unresolved scope and the agent's demonstration-first recommendation; it does not approve a written implementation plan that does not yet exist.
- Q: Can mission COMPLETED be treated as completion of every factory stage? → A: No. Stop collection flow at its recorded terminal state, but show later qualification/claim facts separately within a finite explicit viewing session. Unsupported in-flight stages remain unavailable (agent decided; basis: existing mission UAT completed collection before qualification batches and Claim Ledger readback, Constitution III and actual current-frame contracts).
- Q: Who owns the design artifacts? → A: Spec Kit owns Spec 014, rather than a parallel brainstorming design document (agent decided; basis: repository .specify ownership and the canonical coding workflow).
