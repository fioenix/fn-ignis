# Feature Specification: Dual-Surface Research Workspace

**Feature Branch**: `007-dual-surface-research-workspace`

**Created**: 2026-09-21

**Status**: Accepted for P1 implementation (US1-US3)

**Input**: User decision note: `docs/decisions/2026-09-21-dual-surface-research-workspace.md`

## User Scenarios & Testing

### User Story 1 - Create a Scoped Research Workspace (Priority: P1)

As a requester using Claude Cowork, Claude Code, or Codex, I want a new research to live in a
named child workspace inside my current workspace so that the research remains addressable across
Agent hosts without depending on the chat that started it.

**Why this priority**: A durable research boundary is required before either analytical surface
can preserve evidence, briefs, and artifacts safely.

**Independent Test**: Start a new research in a host workspace, confirm the proposed child path,
reopen the child workspace from another supported host connected to the same Ignis database, and
verify that its manifest and scoped research state are available without the original chat session.

**Acceptance Scenarios**:

1. **Given** a current host workspace and a requested research name, **When** the Agent proposes
   `.ignis/research/<research-slug>/`, **Then** no durable research files exist before the
   requester confirms creation.
2. **Given** the requester confirms the proposed path, **When** the workspace is created,
   **Then** it contains a stable identity and can be reopened through the shared Ignis database
   independently of the originating chat session.
3. **Given** an existing child folder with a matching valid manifest, **When** the requester
   selects it, **Then** the existing research is reused without overwriting its data.
4. **Given** a non-empty child folder without a valid manifest, **When** the requester selects it,
   **Then** the Agent asks for explicit adoption confirmation and preserves unrelated files.

### User Story 2 - Explore Attention Without a Market Thesis (Priority: P1)

As a requester exploring what is gaining attention, I want to run an Attention research without
first inventing a market hypothesis so that discovery remains open-ended.

**Why this priority**: Attention is the entry point for users who do not yet know which topic is
worth investigating commercially.

**Independent Test**: Create an Attention mission with its available scope, inspect its ranked
topics and citations, and verify that it does not require or emit a Market Brief or Opportunity
Index.

**Acceptance Scenarios**:

1. **Given** a confirmed research workspace, **When** the requester starts an Attention mission
   without a hypothesis, **Then** the mission can run with its declared scope.
2. **Given** Attention observations are available, **When** the Agent presents results, **Then**
   each ranked topic or cluster shows momentum, freshness, source coverage or diversity, and
   attributable evidence.
3. **Given** an Attention result, **When** the Agent recommends it for further investigation,
   **Then** the recommendation is presented as a candidate and not as a commercial verdict.

### User Story 3 - Frame and Run a Market Investigation (Priority: P1)

As a requester investigating a possible market opportunity, I want an adaptive Q&A to turn my
intent into a confirmed Market Brief before probes run, so that the resulting claims answer a
decision rather than merely repeat a trend.

**Why this priority**: A confirmed, falsifiable brief is the contract that makes Market evidence
interpretable and prevents attention signals from being mistaken for demand.

**Independent Test**: Start a direct Market mission, complete the Q&A, edit the draft, confirm all
required fields, and verify that only then can Market probes run.

**Acceptance Scenarios**:

1. **Given** a direct Market request or an Attention topic selected for investigation, **When**
   the Market framing starts, **Then** the requester is asked one adaptive question at a time.
2. **Given** the Q&A is in progress, **When** the requester has supplied enough information for
   a field, **Then** the Agent may skip redundant questions while still collecting all required
   fields.
3. **Given** a draft Brief is missing any required field, **When** the requester attempts to run
   Market probes, **Then** the Agent blocks execution and identifies the missing field.
4. **Given** the requester confirms a complete Brief, **When** the Market mission starts, **Then**
   the confirmed Brief is persisted and the mission is authorized to run its Market probes.
5. **Given** the requester abandons the Q&A before confirmation, **When** the interaction ends,
   **Then** no transcript, draft Brief, or Market mission is persisted.

### User Story 4 - Handoff and Revise Without Rewriting History (Priority: P2)

As a requester who finds an interesting Attention topic, I want to select it for a separate
Market investigation and later revise the hypothesis without changing the evidence history of
the earlier investigation.

**Why this priority**: The handoff is the defining workflow of the Dual Surface, and immutable
revisions protect the meaning of already-produced evidence.

**Independent Test**: Select an Attention topic, confirm a Market Brief, complete a Market run,
create a revised Brief, and verify separate mission lineage and evidence treatment.

**Acceptance Scenarios**:

1. **Given** an Attention topic, **When** the requester selects it for investigation, **Then** a
   new Market draft records the selected topic and its Attention lineage as context.
2. **Given** a confirmed Market Brief, **When** the requester changes a required field, **Then**
   the system creates a new immutable Brief revision and Market mission instead of mutating the
   earlier Brief.
3. **Given** a new Market revision, **When** probes run, **Then** the new mission collects or
   evaluates evidence against the new Brief; earlier evidence is not automatically counted as
   support for the new hypothesis.
4. **Given** both Attention and Market results exist for a topic, **When** the Agent reports them,
   **Then** the report distinguishes Attention context from Market evidence.

### User Story 5 - Preserve Research Integrity During Concurrent Work (Priority: P2)

As a requester using more than one Agent host, I want independent missions to run concurrently
without overwriting each other's state or evidence.

**Why this priority**: Research workspaces are shared by tools and may outlive any one Agent
process; lost updates would undermine the workspace as a canonical record.

**Independent Test**: Run two different missions concurrently, then attempt a second writer for
the same mission, and verify independent progress plus a clear revision or refusal for the
duplicate writer.

**Acceptance Scenarios**:

1. **Given** two different missions in one workspace, **When** they run concurrently, **Then**
   neither mission loses state or evidence belonging to the other.
2. **Given** a mission already has an active writer, **When** a second run targets that mission,
   **Then** it creates a new revision or fails clearly without mutating the active run.
3. **Given** two runs start within the same second, **When** each writes run state, **Then** each
   receives a distinct journal identity and neither run overwrites the other's journal.

## Edge Cases

- The requester cancels workspace creation after seeing the proposed path.
- The requested slug is invalid, already used by another research, or collides with a reserved
  workspace name.
- The selected folder is non-empty, lacks a manifest, or has a manifest belonging to another
  research.
- A connector returns no data, requires authentication, is rate limited, or fails while other
  connectors remain healthy.
- Attention finds no candidate suitable for Market investigation.
- The requester confirms a Brief with an empty or non-falsifiable hypothesis or without a useful
  falsifier.
- The requester changes the Brief while a Market run is active.
- A copied workspace is opened on a host with an older or incompatible workspace format.
- Two Agent hosts attempt to write the same mission or create the same run journal concurrently.

## Requirements

### Functional Requirements

- **FR-001**: The system MUST treat the host Agent chat session as integration metadata, not as
  the durable research identity.
- **FR-002**: The system MUST create each research under
  `.ignis/research/<research-slug>/` inside the current host workspace only after requester
  confirmation of the proposed path.
- **FR-003**: The system MUST assign each research a stable identity and manifest that can be
  used to reopen it from another supported Agent host.
- **FR-004**: The system MUST reuse an existing child folder only when its manifest is valid and
  matches the selected research.
- **FR-005**: The system MUST require explicit adoption confirmation before using a non-empty
  folder without a valid manifest, and MUST NOT delete or overwrite unrelated files during
  adoption.
- **FR-006**: The system MUST support an `ATTENTION` surface that can run without a hypothesis
  or Market Brief.
- **FR-007**: The system MUST present Attention results with attributable evidence and separate
  momentum, freshness, and source coverage or diversity from commercial conclusions.
- **FR-008**: The system MUST NOT emit an Opportunity Index for an Attention mission.
- **FR-009**: The system MUST support a `MARKET` surface that starts directly or from an
  explicitly selected Attention topic.
- **FR-010**: The system MUST collect and display a draft Market Brief through adaptive,
  one-question-at-a-time Q&A with no more than seven primary questions.
- **FR-011**: A Market Brief MUST include `decision`, `target_user`, `problem`, `geo`,
  `timeframe`, `hypothesis`, and `falsifiers` before Market execution is authorized.
- **FR-012**: The system MUST allow the requester to edit the draft Brief before confirmation.
- **FR-013**: The system MUST persist only the confirmed Market Brief and MUST NOT persist an
  abandoned Q&A transcript or unconfirmed draft.
- **FR-014**: The system MUST treat a confirmed Market Brief as immutable.
- **FR-015**: A change to a confirmed Brief MUST create a new Brief revision and Market mission;
  it MUST NOT mutate the earlier Brief or its mission evidence.
- **FR-016**: A Market revision MUST run probes against its own confirmed Brief. Earlier evidence
  MAY be linked as context or lineage but MUST NOT be counted automatically as support for the new
  hypothesis.
- **FR-017**: The system MUST keep Attention context distinct from Market evidence in mission
  analysis and artifacts.
- **FR-018**: The system MUST keep the Opportunity Index exclusive to Market analysis.
- **FR-019**: One configured Ignis database MUST be the canonical owner of research records,
  using `workspace_id` and mission foreign keys to isolate each research from every other
  workspace.
- **FR-020**: The system MUST keep workspace data local-first and MUST NOT automatically publish
  or commit research data to source control.
- **FR-021**: Different missions in one workspace MUST be able to read and write independently
  without losing each other's state.
- **FR-022**: A mission MUST have at most one active writer; a conflicting writer MUST create a
  new revision or fail clearly.
- **FR-023**: Each run MUST have an exclusive, collision-safe journal identity, including when
  multiple runs begin within the same second.
- **FR-024**: The system MUST preserve connector health and no-data states as evidence metadata;
  missing data MUST NOT be represented as zero evidence.
- **FR-025**: The host Agent MUST own adaptive Market Q&A and MUST send fn-ignis only the
  requester-confirmed Brief payload; fn-ignis MUST NOT persist abandoned questions, draft answers,
  or a transcript.
- **FR-026**: Every Market citation attached to a conclusion, opportunity, or actionable takeaway
  MUST identify the canonical `observation_id`, or explicitly identify the relevant no-data or
  degraded channel state.
- **FR-027**: Channel health in the P1 response contract MUST be keyed by connector surface, so
  distinct surfaces such as TikTok video search and TikTok comments cannot mask one another behind
  a single platform aggregate.

### Key Entities

- **Research Workspace**: The durable logical boundary for one research, including its identity,
  database scope, missions, confirmed Brief revisions, observations, evidence links, and artifacts.
- **Attention Mission**: An exploratory analysis of topics or clusters by momentum, freshness,
  coverage, and source diversity.
- **Market Mission**: A hypothesis-driven investigation authorized by one confirmed Market Brief.
- **Market Brief Revision**: An immutable, requester-confirmed decision frame containing the seven
  required fields and its confirmation metadata.
- **Observation**: An immutable source observation collected for a mission or linked as context,
  with its source and provenance.
- **Mission Evidence Link**: The explicit relationship that identifies how an observation supports
  or contextualizes a mission.
- **Run Journal**: Collision-safe, exclusive run state used to recover and audit an individual
  mission run.
- **Artifact**: A human-readable projection or export derived from canonical workspace records.
- **Agent Chat Metadata**: Host-provided context such as a chat/session identifier; it is not the
  research identity.

## Success Criteria

### Measurable Outcomes

- **SC-001**: In 100% of first-use workspace tests, no durable research file is created before
  the requester confirms the proposed child path.
- **SC-002**: A requester can complete an Attention-only flow without supplying a hypothesis or
  Market Brief in 100% of supported acceptance scenarios.
- **SC-003**: In 100% of Market execution attempts with an incomplete Brief, probes are blocked
  and the missing required fields are identified.
- **SC-004**: In 100% of revision scenarios, the earlier confirmed Brief and its evidence links
  remain unchanged and the revised hypothesis receives a distinct Market mission identity.
- **SC-005**: A research workspace can be reopened from at least two supported Agent hosts
  connected to the same Ignis database, with its manifest, confirmed Briefs, mission state, and
  evidence lineage intact.
- **SC-006**: In concurrent-run tests, 100% of distinct mission states and run journals remain
  attributable to the correct mission and no run overwrites another run's journal.
- **SC-007**: Every Market conclusion presented by the system has an attributable evidence link
  or an explicit no-data/degraded status; no missing channel is silently represented as zero.
- **SC-008**: Reviewers can distinguish Attention context, Market evidence, and Opportunity Index
  output in every generated Market analysis artifact.
- **SC-009**: A host Agent can abandon Market Q&A without creating a Brief, mission, journal, or
  other canonical research record.

## Assumptions

- The host Agent provides a current writable workspace before research begins.
- The requester is the authority who confirms workspace creation and Market Brief content.
- Research artifacts are local-first and may contain raw or sensitive source material; users
  explicitly export or version-control selected artifacts when needed.
- One Ignis installation uses one configured shared database: SQLite-local by default or
  PostgreSQL when explicitly configured. Research records are separated inside that database by
  workspace scope.
- Existing connector authentication, source identity, observation identity, and Opportunity Index
  calculation remain unchanged unless a later plan explicitly scopes a change.
- No new connector is required to validate this feature's core workflow.
- Connector failures, authentication gaps, rate limits, and empty results remain visible as
  explicit channel states rather than being converted into zero-valued evidence.

## Out of Scope

- Persisting or replaying abandoned Q&A transcripts.
- Treating chat history as the canonical research record.
- Changing the Opportunity Index formula.
- Automatic publication, Git commits, or remote synchronization of research workspaces.
- Standalone backup/export of a research database outside its Ignis installation.
- Adding new source connectors or changing connector authentication flows.
- Replacing the existing source, observation, or mission-evidence provenance model.
