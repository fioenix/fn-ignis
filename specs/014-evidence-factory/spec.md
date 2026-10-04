# Feature Specification: Ignis Evidence Factory

**Feature Branch**: `codex/ignis-evidence-factory`

**Created**: 2026-10-04

**Status**: Draft — scope clarification and design approval required

**Input**: Owner-requested Goal 2: a cinematic high-tech page visualizing Ignis collection, processing and analysis, with moving data blocks, streams, processing pools and separation, resembling a science-fiction factory. Continue after Goal 1 source integration.

## Outcome and audience

A person evaluating or using Ignis can follow an observation from a requested task to its evidence role, inspect the reason for separation, and understand why a conclusion is permitted or withheld. The page should feel like an instrumented futuristic research factory, not a generic dashboard or an animation claiming activity that did not occur.

The intended audience is founders, operators and analysts unfamiliar with Ignis's evidence control plane. This audience is an assumption to confirm, not an independently measured user-research result.

## User Scenarios & Testing

### User Story 1 — Follow the evidence journey (Priority: P1)

A viewer enters a coherent factory scene and follows data blocks from an explicitly assigned research task through collection, provenance, qualification, falsification and the claim gate.

**Why this priority**: The cinematic effect must explain Ignis's differentiator: critical research on traceable observations, not automatic confirmation of a preferred idea.

**Independent Test**: Walk through all six scenes and identify each stage's input, output and reason for rejection or withholding without reading product documentation.

**Acceptance Scenarios**:

1. **Given** no task has started, **When** the page opens, **Then** collection is visibly idle and no real collector or quota operation starts.
2. **Given** a running visual sequence, **When** a block crosses a stage, **Then** its provenance and evidence role remain inspectable and consistent.
3. **Given** conflicting observations, **When** the falsification stage is inspected, **Then** support and contradiction remain visible under the same qualification standard.

### User Story 2 — Inspect without being forced to watch (Priority: P2)

A viewer pauses the factory, selects a stage or observation, reads a plain-language explanation, and resumes or restarts the presentation.

**Why this priority**: Constant movement without inspection would obscure the actual method and exclude users sensitive to motion.

**Independent Test**: Complete stage navigation and evidence inspection using only a keyboard and again with reduced motion enabled.

**Acceptance Scenarios**:

1. **Given** an animated sequence, **When** Pause is selected, **Then** the sequence and moving blocks stop while explanatory content remains available.
2. **Given** reduced motion, **When** the page opens, **Then** the complete method is accessible without continuous movement or camera sweeps.
3. **Given** a narrow viewport, **When** a stage is selected, **Then** controls and explanations remain readable without horizontal page overflow.

### User Story 3 — Recognize the data and conclusion boundary (Priority: P1)

A viewer can distinguish demonstration, a recorded mission replay and current runtime facts, and understand why missing evidence does not become a recommendation.

**Why this priority**: A convincing factory visual must not manufacture a convincing market claim.

**Independent Test**: Inspect the insufficient-evidence ending and verify that no category winner, invented confidence or commercial verdict appears.

**Acceptance Scenarios**:

1. **Given** synthetic presentation data, **When** any scene is viewed, **Then** a persistent demonstration label is visible and no count is described as live.
2. **Given** unknown publication time or reach, **When** an observation is inspected, **Then** the value remains explicitly unknown, not zero or fresh.
3. **Given** insufficient evidence, **When** the final gate is reached, **Then** a gap and next validation action appear rather than a commercial verdict.

### Edge Cases

- Empty, unavailable and degraded channels must be distinguishable from healthy measured absence.
- Closing or hiding the page must stop unnecessary presentation work; it must never extend collection authority.
- Missing fonts, network access or animation support must not remove the explanatory content.
- An excluded block remains inspectable; it does not silently disappear into a visually successful output.
- A replay ends at its recorded terminal state; continuous visual throughput must not imply an always-on collector.
- Loading a replay or viewing an observation must not expose credentials, private messages or unmasked personal data.

## Requirements

### Functional Requirements

- **FR-001**: The page MUST present the six-stage task-to-claim evidence journey as one recognizable cinematic factory.
- **FR-002**: Data blocks MUST flow through visible processing pools and separate by their actual displayed evidence roles; animation MUST NOT be a measured statistical encoding unless its denominator and mapping are disclosed.
- **FR-003**: Each stage MUST expose what it receives, what it produces, why it matters and what can fail.
- **FR-004**: The page MUST preserve provenance, counterevidence, context-only and excluded roles; raw popularity MUST NOT become demand or claim permission.
- **FR-005**: A persistent mode indicator MUST distinguish synthetic demonstration, recorded replay and live observations wherever those modes are supported.
- **FR-006**: The initial product scope is [NEEDS CLARIFICATION: explanatory cinematic page with synthetic data, recorded mission replay, or a live mission operations dashboard?]. Live runtime integrations MUST NOT be added by assuming the last interpretation.
- **FR-007**: The page MUST provide Pause, Resume/Play, Restart and direct stage inspection, with visible keyboard focus and no hover-only essential content.
- **FR-008**: Reduced-motion viewing MUST preserve all information while disabling continuous block flow and cinematic camera movement.
- **FR-009**: Unknown metrics, unmeasured source windows, channel failures and missing hypothesis coverage MUST stay visible rather than being assigned flattering numbers.
- **FR-010**: The final gate MUST show a permitted claim with its bindings only when allowed by its displayed frame, or show a clear Gap Report. Synthetic claims MUST be labeled illustrative, not business advice.
- **FR-011**: The presentation MUST use the maintained FINOLABS product design system; mint is the everyday flow accent, while violet marks one high-stakes claim gate. Colour MUST have accompanying labels/shapes.
- **FR-012**: Merely opening, replaying or restarting the presentation MUST NOT start a connector, scheduler, authentication flow or paid operation.
- **FR-013**: No existing MCP signatures, connector tiers, persisted evidence, release versions or owner-client settings may change solely to implement the presentation.

### Key Entities

- **Presentation mode**: Provenance of the displayed activity: demonstration, recorded replay or live.
- **Factory stage**: A named transformation with an input, output, explanation and visible failure state.
- **Evidence block**: An inspectable observation with source/query identity, time/metric missingness and qualification role.
- **Evidence frame**: The task-bound context against which qualification and claims are considered.
- **Decision gate**: A permitted claim with traceable bindings or a withheld outcome with explicit gaps.

## Success Criteria

### Measurable Outcomes

- **SC-001**: Every one of the six stages can be selected directly; a viewer can complete the explanatory journey in at most two minutes without waiting for animations.
- **SC-002**: All essential controls and explanations are available using a keyboard and in reduced-motion mode.
- **SC-003**: At 390, 768 and 1440-pixel viewport widths, all stage explanations and controls remain available without horizontal page overflow or clipped essential text.
- **SC-004**: Demonstration/replay/live identification is visible in every supported scene; no unsupported market verdict is emitted in the insufficient-evidence scenario.
- **SC-005**: On the declared reference machine, a 30-second presentation sample maintains at least 50 frames per second in its normal desktop mode; measurements must identify the machine and viewing conditions rather than claiming universal performance.
- **SC-006**: Source observations, exclusions, contradiction and gaps remain readable with animation paused and external resources unavailable.
- **SC-007**: Final acceptance includes actual rendered screenshots at the three viewport sizes, a keyboard/reduced-motion walkthrough, mode/data-integrity readback and complete regression results; a successful file open is not pixel proof.

## Assumptions and boundaries

- Goal 1 source integration is PR #50/main a94db308. Accepted historical test-first and pixel-proof exceptions in that goal do not waive new Goal 2 visual acceptance.
- The first proposed experience is explanatory and opt-in. Its scope is not approved by the proposal itself; FR-006 awaits the owner's answer.
- No dependency, new backend or real social account access is assumed. Technical choices belong in the subsequent plan after scope and design approval.
- Maintained report templates remain the only report source committed as code; generated exports remain local runtime output.
- Vietnamese is the audience-facing narrative; developer specifications and identifiers remain English.

## Storyboard — proposed experience, not an approved implementation

| Scene | Factory composition and movement | Meaning and inspection |
|---|---|---|
| 01 — Mission ignition | A dark instrument deck, dormant intake rails, one bounded task capsule. A deliberate Play action lights the route. | Outcome, audience, hypotheses, authorized sources and stop conditions. No always-on collection. |
| 02 — Source intake | Distinct source docks send small labeled blocks down luminous rails into a receiving pool. A unavailable dock has no fabricated stream. | Exact query and channel status; collection is not yet market evidence. |
| 03 — Provenance chamber | Blocks settle into an indexed pool; each opens into source, observation and task-binding layers. Unknown fields remain visibly unset. | Identity, collection time, source time, measurement provenance and masking. |
| 04 — Qualification separator | Blocks fan into named lanes for support, contradiction, context and exclusion; labels and geometry accompany colour. | Why a particular observation belongs in its role. Rejected data stays inspectable. |
| 05 — Falsification reactor | Support and contradiction orbit the same hypothesis chamber. Alternative/null routes stay visible; uncovered routes remain incomplete. | Competing explanations, identical evidentiary standards and remaining hypothesis gaps. |
| 06 — Claim airlock | One high-stakes gate either admits an explicitly bound claim or stops the flow at a gap panel. The scene settles at a terminal state. | Traceability, limitations, withheld verdict and next useful validation action; no endless successful-output loop. |

### Scope alternatives

1. **Explanatory cinematic demonstration — recommended first**: Smallest presentation scope, synthetic data clearly labeled, no runtime wiring. Cost: it explains the method but cannot report an actual task's progress.
2. **Recorded mission replay**: Real persisted lineage with an explicit snapshot/replay boundary. Cost: privacy, sanitization and frame-binding requirements; cannot be called live.
3. **Live operations dashboard**: Actual ongoing mission state, failures, cancellation and freshness. Cost: a new telemetry and authority contract, substantially broader than presentation alone.

## Clarifications

### Session 2026-10-04

- Q: Which presentation scope should be built first? → A: Unresolved. A direct question was sent to the owner; noulmes routed the demo-versus-live scope question to the owner. No recommendation is recorded as owner approval.
- Q: Who owns the design artifacts? → A: Spec Kit owns Spec 014, rather than a parallel brainstorming design document (agent decided; basis: repository .specify ownership and the canonical coding workflow).
