# Feature Specification: Evidence-Grounded Product Reset

**Feature Branch**: `011-evidence-grounded-product-reset`

**Created**: 2026-09-29

**Status**: Accepted for planning

**Input**: Owner approval of `docs/PRODUCT_PROPOSAL.vi.md` on 2026-09-29

## Clarifications

### Session 2026-09-29

- Q: Does Ignis retain an optional always-on radar or scheduled daily collection mode? → A: No.
  Ignis starts only after an explicit task, acts autonomously inside the confirmed mission boundary,
  and stops when the task reaches a terminal state (owner decided; basis: approved proposal).
- Q: How are `evidence-grounded` and `evidence-gated` used? → A: `Evidence-grounded social
  market research agent` is the public category promise; `evidence-gated` names the internal
  mechanism that permits or withholds an inference (owner approved with the proposal).
- Q: Is the removal of worker, scheduler, daily-discovery reports, and their public operations
  gradual? → A: No. They are removed together in a breaking release without a deprecated
  compatibility period (owner decided; basis: approved proposal).
- Q: Does scheduled baseline data become mission evidence? → A: No. It is archived read-only only
  where a concrete retention reason exists; otherwise it becomes an explicit deletion candidate.
  Deletion still requires target-specific authorization and verification (owner decided; basis:
  approved proposal and repository safety policy).
- Q: Who is the first validation audience? → A: Founders, operators, independent analysts,
  consultants, and small teams researching consumer markets in Vietnam (owner decided; basis:
  approved proposal).

### Session 2026-09-30

- Q: Where should the breaking implementation run while `main` contains unrelated owner changes?
  → A: Use an isolated managed worktree and import only the approved Spec 011 planning artifacts
  before implementation (agent decided; basis: preserve the dirty owner checkout and keep the
  implementation review range attributable).
- Q: Which feature and migration numbers apply after refreshing from the live repository? → A:
  Use Spec 011 and planned migration `025`; the live base already contains completed Spec 009,
  Spec 010, and `sql/024_youtube_quota_ledger.sql` (agent decided; basis: preserve unique canonical
  identities without changing the approved product scope).
- Q: How should the new `SUPPORT`/`CONTRADICTION`/`CONTEXT` role avoid colliding with the existing
  mission-association `EvidenceRole` enum? → A: Keep `EvidenceRole` for
  `MARKET_EVIDENCE`/`ATTENTION_CONTEXT`, add the internal enum `EvidenceDirection`, and serialize it
  through the public field `evidence_role` (agent decided; basis: preserve the existing contract
  while giving analytical direction a distinct type).
- Q: How should pytest prevent an inherited shell credential from reaching code or failure output?
  → A: Quarantine production credential variables at the top of `tests/conftest.py`, before any
  `ignis` import; use inert SQLite/empty connector values, remove host/release credentials, and
  preserve only the explicit isolated `IGNIS_TEST_POSTGRES_DSN` integration-test channel (agent
  decided; basis: tests must neither call live services nor print ambient credentials, while the
  dedicated throwaway PostgreSQL contract remains usable).
- Q: May implementation write migration `025` and remove the exact eight public MCP operations
  enumerated by this feature? → A: Yes. Write and test migration `025` locally without applying it
  to a persistent database; remove exactly the approved eight MCP operations without aliases, but
  do not release or publish the cutover yet (owner decided; basis: explicit "Tiếp tục đi" in
  direct response to the two named owner gates on 2026-09-30).
- Q: Where does authority to declare a `frame_digest` current belong? → A: Keep `EvidenceFrame`
  derived as designed. Repositories enforce mission ownership, compatible qualifications, latest
  completed measured-absence outcomes, idempotency, and explicit supersession, but they do not
  promote an arbitrary caller digest to current. T040 derives the canonical frame and T054
  validates it before persisting and superseding claims (agent decided; basis: repository storage
  lacks the complete derived frame, and persisting a second current-frame truth would contradict
  the approved data model).
- Q: How should the expanded strategic sufficiency policy relate to the existing deterministic
  demand and supply minimums? → A: Extend the existing policy in place: retain its current demand
  and supply minimums, then add required-channel completion, contradiction coverage,
  current-frame identity, and metric denominator/timeframe gates; every failure derives a typed
  Gap Report (agent decided; basis: preserve the already tested product-safety floor while adding
  the missing Spec 011 gates without creating a second policy authority).
- Q: Where should a calculated claim's denominator and timeframe live? → A: Persist both on each
  `MEASUREMENT` claim and withhold that claim when either is absent; no batch-level option may
  decide whether metric validation applies (agent decided; basis: every claimed calculation must
  carry its own auditable basis, and caller-controlled validation would fail open).
- Q: How should a dataset path, URL, or raw JSON supplied in place of a Market mission ID be
  handled without adding an unapproved MCP parameter? → A: Return a typed `CONTEXT_ONLY` refusal
  from the analysis, opportunity, and artifact boundaries before opening runtime components;
  preserve their existing signatures and require mission-scoped provenance and qualification
  before primary Market use (agent decided; basis: FR-007/FR-008 and the approved public contract).
- Q: How are the two Hermes tool catalogs kept in sync after the approved breaking MCP removal?
  → A: Derive both from the live FastMCP schema with a deterministic checked script, retaining
  the order of surviving operations and appending new ones by name (agent decided; basis: the
  public runtime is the contract and hand-maintained schema copies had drifted).
- Q: Does the removed unattended script filter apply to explicitly requested collection?
  → A: No. Requested collection preserves returned languages for downstream evidence
  qualification; the historical scheduled quota ledger remains audit data, not authority to run
  a scheduled sweep (agent decided; basis: no always-on collection survives the approved cutover).

### Session 2026-10-01

- Q: May the synchronous strategic reasoner produce a Market opportunity from qualified raw
  observations without loading the persisted current-frame Claim Ledger? → A: No. The reasoner
  may expose channel audit observations but must not mint Market verdicts; Market analysis,
  opportunity, artifact, and quality boundaries read the persisted analysis contract instead
  (agent decided; basis: FR-015/FR-016 and T058, avoiding a second verdict authority).
- Q: How should a no-write baseline inventory classify unscoped rows without a documented
  retention reason? → A: List them as exact deletion candidates, not deletion instructions;
  archive candidates require a concrete reason, orphan metrics are held for investigation, and
  every deletion requires a verified export and a later target-specific owner decision (agent
  decided; basis: FR-026/FR-027 and the accepted legacy disposition design).

## User Scenarios & Testing

### User Story 1 - Start Only From an Explicit Research Task (Priority: P1)

As an operator, I want Ignis to remain idle until I or my host agent assigns a bounded task, so that
the product consumes no connector quota or compute for research nobody requested.

**Why this priority**: Mission-bound autonomy is the product reset. Keeping any silent collection
path would preserve the cost and source-of-truth conflict this feature is meant to remove.

**Independent Test**: Observe an initialized installation without an assigned task, then assign and
complete one tactical collection task. Verify that no collection begins while idle, that the task
may proceed autonomously inside its confirmed boundary, and that collection stops at completion.

**Acceptance Scenarios**:

1. **Given** an initialized installation with no active task, **When** time passes, **Then** no
   connector probe, discovery digest, alert, or recurring collection is started.
2. **Given** a user-assigned task with confirmed sources and limits, **When** the task starts,
   **Then** Ignis may select and sequence the necessary in-scope probes without asking about every
   internal step.
3. **Given** a task reaches `COMPLETED`, `INSUFFICIENT_EVIDENCE`, `CANCELLED`, or `FAILED`, **When**
   no explicit continuation is requested, **Then** Ignis performs no further collection for it.
4. **Given** a probe requires a new browser session, token, paid quota, or material scope change,
   **When** that authority is not already in the task boundary, **Then** Ignis stops before using it
   and states what approval is missing.

---

### User Story 2 - Collect a Transparent Social Evidence Frame (Priority: P1)

As a founder, analyst, or consultant, I want Ignis to collect social evidence for my exact business
question and disclose what each source did or did not measure, so that I can audit the sample instead
of trusting an opaque dataset.

**Why this priority**: Collection is useful only when its provenance, missingness, and authority are
visible. More observations without these boundaries increase false confidence.

**Independent Test**: Run a mission spanning healthy, empty, unauthenticated, and failed connector
surfaces. Verify that the result retains the exact query and source lineage, distinguishes every
surface state, and never interprets an unmeasured surface as zero.

**Acceptance Scenarios**:

1. **Given** a bounded mission, **When** a connector returns observations, **Then** each observation
   retains its source identity, collection query, collection time, available publication time,
   collection path, and connector revision.
2. **Given** one required surface is unauthenticated or rate limited, **When** collection completes,
   **Then** that state remains distinct from both healthy emptiness and measured absence.
3. **Given** a user supplies a keyword, URL, brief, file, or dataset, **When** the mission is framed,
   **Then** that material is treated as input or context until Ignis collects or verifies evidence
   through an authorized mission surface.
4. **Given** an observation appeared in an earlier mission, **When** a new mission begins, **Then**
   the observation is not silently counted as support without qualification against the new mission
   and Brief revision.

---

### User Story 3 - Challenge the Initial Belief Before a Verdict (Priority: P1)

As a decision maker who may already favor an idea, I want Ignis to search for counterevidence and
credible alternative explanations before recommending action, so that the research tests my belief
instead of decorating it.

**Why this priority**: Confirmation-bias resistance is the primary differentiation from a generic
research agent with social connectors.

**Independent Test**: Run one mission whose core hypothesis has strong supporting evidence but also
qualified contradictions, and one whose required evidence is insufficient. Verify that the first
shows both sides and unresolved alternatives, while the second withholds the strategic verdict and
returns the smallest useful next probe.

**Acceptance Scenarios**:

1. **Given** a Market mission, **When** its frame is confirmed, **Then** it records a falsifiable
   core hypothesis, at least two credible alternatives, a null hypothesis, falsifiers, kill
   criteria, and a revision rule.
2. **Given** supporting, contradicting, and neutral observations, **When** they are qualified,
   **Then** the same relevance and quality standard is applied regardless of whether they agree with
   the initial hypothesis.
3. **Given** qualified contradictory evidence, **When** a report is produced, **Then** the evidence
   remains visible with the same source traceability as supporting evidence.
4. **Given** required evidence is missing or insufficient, **When** analysis is requested, **Then**
   no demand-gap, whitespace, saturation, or Opportunity Index verdict is emitted and an actionable
   gap report identifies the next-best probe.

---

### User Story 4 - Use Collection and Analysis as Independent Capabilities (Priority: P2)

As a host-agent user, I want to invoke focused social collection without a full dossier and invoke
the Senior Market Analytics method only over an eligible Ignis evidence frame, so that the product
fits both tactical and strategic work without forcing one rigid pipeline.

**Why this priority**: The two capability families make Ignis useful inside existing agent
workflows while the shared evidence contract preserves the product's trust boundary.

**Independent Test**: Complete one tactical collection request without creating a strategic report,
then complete one Market mission that uses both capability families. Verify that both paths are
usable independently and that strategic analysis cannot bypass evidence sufficiency.

**Acceptance Scenarios**:

1. **Given** a user requests a bounded source-specific probe, **When** collection succeeds, **Then**
   Ignis returns the evidence and channel state without forcing a full Market workflow.
2. **Given** a qualified mission corpus, **When** strategic analysis is requested, **Then** the
   result distinguishes observation, measurement, inference, assumption, recommendation, and
   unknown.
3. **Given** an arbitrary external dataset without equivalent provenance and sampling evidence,
   **When** strategic analysis is requested, **Then** it cannot be used as primary evidence for a
   Market verdict.
4. **Given** any supported strategic claim, **When** a reviewer inspects it, **Then** the reviewer
   can trace it through the claim record to the exact evidence frame and Brief revision.

---

### User Story 5 - Complete the Breaking Product Cutover (Priority: P2)

As an installer or contributor, I want every product surface to describe and enforce the same
mission-bound product, so that setup instructions, public operations, runtime behavior, and reports
do not expose two contradictory versions of Ignis.

**Why this priority**: A runtime change without canonical documentation and public-contract removal
would leave users invoking a product that no longer exists or assuming background work still runs.

**Independent Test**: Install the breaking release from a clean environment, inspect every public
operation and canonical guide, and verify that no worker, scheduler, daily-discovery operation, or
silent compatibility alias remains while an on-demand tactical and Market mission still work.

**Acceptance Scenarios**:

1. **Given** the breaking release, **When** a new installation is bootstrapped, **Then** no background
   worker or recurring research schedule is installed or started.
2. **Given** a previous public operation for daily discovery or worker control, **When** a client
   enumerates the new public contract, **Then** that operation is absent rather than deprecated or
   silently redirected.
3. **Given** canonical project guidance, **When** a contributor reads the product architecture,
   **Then** every active document describes mission-bound autonomy and names old dual-track material
   as superseded or historical.
4. **Given** scheduled baseline data from an earlier installation, **When** cutover is planned,
   **Then** it is inventoried separately and is not migrated into mission evidence without a new
   evidence qualification decision.

### Edge Cases

- A host retries a completed mission and accidentally creates a background loop.
- A task says “monitor this continuously” even though recurring monitoring is outside the product
  contract.
- A connector returns HTTP success while only searching the authenticated account's own content.
- A healthy connector measures the exact scope and returns zero observations.
- A connector returns observations but not the denominator or timeframe needed by a Market claim.
- All observations support the core hypothesis because no disconfirming query was actually run.
- Contradictory evidence is lower volume but comes from a more relevant target-user sample.
- Alternative explanations are cosmetically different but predict the same observations.
- A report contains strong narrative language while its claim record is incomplete.
- A previous mission's evidence is still physically stored but no longer qualifies for the new
  Brief revision.
- An external CSV has valid URLs but no reproducible query, sampling frame, or collection time.
- The former baseline corpus includes records with legal, retention, or provenance reasons to keep
  and other records with no remaining value.
- A user needs only a tactical collection result and declines a Market Brief.
- An Attention mission finds a popular topic but no evidence of a consumer problem or willingness
  signal.
- A host agent attempts to turn `INSUFFICIENT_EVIDENCE` into a strategic verdict in its own prose.

## Requirements

### Functional Requirements

- **FR-001**: Ignis MUST NOT initiate collection, analysis, alerts, or report generation while no
  explicit user or host-agent task is active.
- **FR-002**: Every task MUST declare its requested outcome, scope, allowed social surfaces,
  authority boundary, output type, and stop conditions before using resources outside a tactical
  source-specific request.
- **FR-003**: Ignis MUST stop connector and analysis work when a task reaches a terminal state unless
  an explicit continuation or revision is assigned.
- **FR-004**: Recurring monitoring, scheduled discovery, daily auto-collection, and idle-state
  autonomous expansion MUST remain outside the product contract.
- **FR-005**: The product MUST expose two independently usable capability families: bounded social
  evidence collection and Senior Market Analytics over an eligible evidence frame.
- **FR-006**: Both capability families MUST use one shared mission evidence frame for provenance,
  channel state, qualification, counterevidence, sufficiency, and claim traceability.
- **FR-007**: A file, URL, keyword, brief, or external dataset supplied by a user MUST be treated as
  input or context until its evidence is collected or verified through an authorized mission path.
- **FR-008**: Arbitrary external or purchased data without equivalent provenance and sampling
  evidence MUST NOT become primary support for a Market verdict in this feature.
- **FR-009**: Every requested connector surface MUST report exactly one of `HEALTHY`,
  `EMPTY_NO_DATA`, `AUTH_REQUIRED`, `RATE_LIMITED`, `DEGRADED`, `FAILED`, or `NOT_REQUESTED` for the
  completed collection frame.
- **FR-010**: `AUTH_REQUIRED`, `RATE_LIMITED`, `DEGRADED`, `FAILED`, and `NOT_REQUESTED` MUST NOT be
  interpreted as zero demand, zero supply, or healthy measured absence.
- **FR-011**: `EMPTY_NO_DATA` MUST be used only when the connector measured the declared query,
  scope, and timeframe and returned no qualifying observations.
- **FR-012**: A Market mission MUST record a core hypothesis, at least two alternative hypotheses,
  a null hypothesis, falsifiers, kill criteria, and a revision rule before strategic collection is
  considered complete.
- **FR-013**: The collection plan for a Market mission MUST include probes capable of finding
  supporting, contradicting, and neutral or contextual evidence.
- **FR-014**: Evidence qualification MUST apply the same relevance and quality standard to evidence
  that supports and evidence that contradicts the core hypothesis.
- **FR-015**: Analytical statements MUST be identifiable as `OBSERVATION`, `MEASUREMENT`,
  `INFERENCE`, `ASSUMPTION`, `RECOMMENDATION`, or `UNKNOWN`.
- **FR-016**: Evidence sufficiency MUST be decided before strategic narrative generation and MUST
  constrain every host-facing result and deterministic artifact.
- **FR-017**: When evidence is insufficient, Ignis MUST withhold strategic Market verdicts and
  return the failed gate, missing evidence, attempted probes, safe partial conclusions, required
  authority or quota, and smallest next-best probe.
- **FR-018**: Opportunity Index and demand-versus-supply outputs MUST be absent, not dimmed or
  caveated, when their evidence contract is not satisfied.
- **FR-019**: Every strategic claim MUST bind to evidence identifiers, evidence roles, source and
  channel distribution, inference method, confidence, limitations, corpus identity, Brief revision,
  and conditions that would change the claim.
- **FR-020**: Qualified contradictory evidence MUST remain visible in every strategic artifact and
  MUST NOT be filtered as noise merely because it weakens the core hypothesis.
- **FR-021**: Evidence from an earlier mission MUST NOT silently qualify as support for a new mission
  or revised Brief; reuse requires an explicit mission-scoped qualification.
- **FR-022**: Attention exploration MAY identify and rank signals without a Market hypothesis, but
  MUST NOT emit commercial demand, whitespace, saturation, or Opportunity Index verdicts.
- **FR-023**: Tactical collection MUST remain usable without forcing a full research dossier, and a
  strategic dossier MUST remain impossible without an eligible mission evidence frame.
- **FR-024**: The breaking cutover MUST remove the worker, scheduler, daily-discovery reports,
  alerts, and public operations dedicated to unattended collection without compatibility aliases or
  a deprecation period.
- **FR-025**: Bootstrap, canonical documentation, agent guidance, examples, and backlog state MUST
  describe the same mission-bound product and identify superseded dual-track material as historical.
- **FR-026**: Existing scheduled baseline records MUST be inventoried and classified for explicit
  read-only archival or target-specific deletion; they MUST NOT be automatically converted into
  mission evidence.
- **FR-027**: Actual deletion of baseline records MUST require an explicit, recoverable target list
  and verification step separate from feature planning.
- **FR-028**: Existing decision-grade evidence invariants from Spec 008 MUST remain valid for
  on-demand Market missions across both supported persistence modes.
- **FR-029**: Host agents MAY present different narrative styles, but MUST NOT convert an
  insufficient-evidence state into a strategic verdict without a new or revised evidence frame.
- **FR-030**: The first product validation MUST exercise five real mission conditions: sufficient
  multi-source evidence, required-channel authentication block, high-volume low relevance,
  contradictory signals, and a missing decision-critical metric.
- **FR-031**: Every connector and artifact path MUST expose retention, redaction, platform-policy,
  and reuse limitations relevant to the collected evidence.
- **FR-032**: The public category MUST use “evidence-grounded social market research agent”; product
  documentation MAY use “evidence-gated” only for the mechanism that permits or withholds inference.

### Key Entities

- **Task Assignment**: The explicit authority to start work; includes requested outcome, scope,
  allowed resources, output, and stop conditions.
- **Mission**: A bounded research execution created from a task assignment and independent of a chat
  session.
- **Market Brief Revision**: The immutable decision frame for a Market mission, including target
  user, problem, geography, timeframe, and research question.
- **Hypothesis Register**: The core, alternative, and null hypotheses plus falsifiers, kill criteria,
  and revision rule.
- **Collection Plan**: The declared source surfaces, query families, exclusions, sample or window,
  evidence roles, auth tier, and quota boundary.
- **Channel State**: The exact result of attempting or not attempting one connector surface inside a
  collection frame.
- **Observation**: An immutable item collected from a canonical source with query and collection
  provenance.
- **Mission Evidence Association**: The explicit relationship that makes an observation available
  for qualification in one mission.
- **Evidence Qualification**: A mission-scoped judgment that identifies support, contradiction,
  context, exclusion, or unassessed state and its reason.
- **Evidence Frame**: The versioned corpus identity, channel states, qualifications, missingness, and
  sufficiency result used by analysis.
- **Claim Record**: A strategic statement bound to the exact evidence and inference conditions that
  support or limit it.
- **Gap Report**: A terminal or intermediate output explaining why a verdict is withheld and the
  smallest next action that can reduce the important uncertainty.
- **Capability Family**: Either bounded social collection or Senior Market Analytics, both governed
  by the shared evidence frame.

## Success Criteria

### Measurable Outcomes

- **SC-001**: In 100% of idle-state acceptance runs, an initialized installation makes zero
  connector calls and creates zero research artifacts until an explicit task is assigned.
- **SC-002**: In 100% of terminal-state acceptance runs, connector quota and analysis work stop
  after the task reaches a terminal state unless an explicit continuation is recorded.
- **SC-003**: Both capability families complete their independent acceptance journey, and the
  combined Market journey uses the same evidence frame without a worker or recurring schedule.
- **SC-004**: Unsupported-verdict escape rate is 0% across semantic negative controls and all
  insufficient-evidence benchmark cases.
- **SC-005**: 100% of strategic claims in accepted artifacts trace to qualified evidence or
  qualified measured absence in the same Brief revision.
- **SC-006**: 100% of `AUTH_REQUIRED`, `RATE_LIMITED`, `DEGRADED`, `FAILED`, and `NOT_REQUESTED`
  cases remain distinct from zero in responses, artifacts, and reopened missions.
- **SC-007**: 100% of qualified contradictory evidence remains present in the corresponding claim
  bundle and strategic artifact.
- **SC-008**: A clean installation exposes no worker, scheduler, daily-discovery, or unattended-alert
  operation and starts no background research process.
- **SC-009**: A canonical-surface audit finds zero active documents that present always-on or
  dual-track collection as current product behavior without an explicit superseded marker.
- **SC-010**: The five pilot missions complete with all integrity metrics preserved and record a
  user-verifiable next action: proceed, narrow, reposition, collect more evidence, or stop.
- **SC-011**: The pilot records baseline values for time to qualified evidence frame, manual analyst
  time, user recall of supporting and contradicting evidence, decision-confidence change, repeat
  intent, and willingness-to-pay without converting those first measurements into unsupported
  growth claims.
- **SC-012**: Every strategic artifact records the exact evidence-frame identity, Brief revision,
  analysis policy, source distribution, missingness, and conditions that could change its verdict.

## Assumptions

- The approved product proposal is the authoritative product input for this feature.
- The product remains open-source, local-first, and self-hosted by default; hosted multi-tenancy,
  team billing, and enterprise compliance packages are outside this feature.
- Spec 008 provides the existing decision-grade evidence foundation. This feature preserves those
  invariants and changes the product trigger, challenge method, packaging, and public surface.
- The owner accepts a breaking public-contract removal and does not require compatibility aliases
  for worker, scheduler, or daily-discovery operations.
- No arbitrary dataset import path is added for primary Market evidence in this feature.
- Existing baseline data is not deleted during specification or planning. Any later deletion uses a
  separately approved and verified target list.
- Vietnam consumer-market missions are the first validation corpus, not evidence of universal
  geographic or vertical coverage.
- The first pilot creates outcome baselines; it does not claim adoption, retention, or commercial
  targets before those measurements exist.
- “Evidence-grounded” is the category promise and “evidence-gated” is an internal mechanism term.
