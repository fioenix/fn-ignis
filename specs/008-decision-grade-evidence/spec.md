# Feature Specification: Decision-Grade Evidence Qualification

**Feature Branch**: `008-decision-grade-evidence`

**Created**: 2026-09-25

**Status**: Accepted for planning

**Input**: Product-owner approval of
`docs/decisions/2026-09-25-decision-grade-evidence-qualification.md`

## Clarifications

### Session 2026-09-28

- Q: Which answer decides the qualification state and the next step when the submit, batch,
  analysis and artifact responses could disagree? → A: One domain function,
  `decide_qualification`, over the persisted progress; every response answers from it (agent
  decided after the fourth review's churn stop; basis: the review of `a81661b` and the
  architecture checkpoint).
- Q: Does a recorded `INSUFFICIENT_CONTENT` judgment stop the batch from handing out the remaining
  evidence? → A: No. Only a recorded evaluator failure outranks pending evidence; the rest is still
  judged so the qualification counts stay complete, and the frame turns terminal once nothing is
  pending (agent decided; basis: US4 inspection and the accepted corpus replay counts).
- Q: Does an empty supply search count as measured-zero evidence when the connector did not apply
  the mission's timeframe? → A: No. Only a supply surface that attests the same bounded timeframe
  may contribute a measured zero. Until at least two supply surfaces implement that contract,
  `SUFFICIENT_ZERO_SUPPLY` may be unreachable; that is the intended fail-closed result, not a reason
  to reinterpret an unbounded empty search as evidence (agent decided; basis: decision-grade
  evidence requires the stored query claim to match what the connector actually measured).

## User Scenarios & Testing

### User Story 1 - Get the Same First Mission After Every Startup (Priority: P1)

As a requester starting a research after Ignis has restarted, I want the first mission to use the
same configured vocabulary and probe templates as later missions so that results do not depend on
whether another analysis happened to run first.

**Why this priority**: The current cold-start path can omit TikTok evidence and demand-intent probe
templates even though both are configured. Every later quality decision is unreliable if evidence
collection itself depends on process history.

**Independent Test**: Start Ignis with persisted vocabulary, execute a mission as the first tool
operation, repeat the same mission after an analysis operation has warmed the process, and verify
that both runs register the same vocabulary and invoke the same eligible connector surfaces.

**Acceptance Scenarios**:

1. **Given** a newly started Ignis process and persisted probe templates, **When** the first mission
   begins ingress, **Then** the configured templates are available before any connector probe runs.
2. **Given** persisted connector noise vocabulary, **When** the first mission uses that connector,
   **Then** the connector receives the configured vocabulary before evaluating any result.
3. **Given** the same database state and mission inputs, **When** one run starts cold and another
   starts after an analysis call, **Then** the set of eligible connector surfaces and registered
   vocabulary is the same.
4. **Given** vocabulary synchronization cannot complete, **When** a mission would otherwise run
   without required configuration, **Then** the mission fails clearly before presenting a result
   produced under a partial configuration.

---

### User Story 2 - Withhold Unsupported Market Verdicts (Priority: P1)

As a requester deciding whether to pursue a market opportunity, I want Ignis to distinguish
question-relevant evidence from query-matched noise and withhold the Opportunity Index when the
relevant evidence is insufficient, so that a numerical verdict does not create false confidence.

**Why this priority**: Post-v0.5 validation found traceable citations attached to semantically
unrelated films, drama, and motivational content. Correct provenance without support is not a
decision-grade result.

**Independent Test**: Run one Market mission whose observations repeat probe keywords but do not
address the confirmed Brief, then run a control mission with relevant demand and supply evidence.
Verify that the first returns an explicit insufficient-evidence result without an Opportunity
Index, while the control retains its qualified verdict.

**Acceptance Scenarios**:

1. **Given** a confirmed Market Brief and observations that only repeat probe keywords, **When**
   they do not address the target user, problem, hypothesis, or decision, **Then** they are not
   counted as Market support.
2. **Given** a Market topic without qualified demand evidence, **When** analysis runs, **Then** no
   Opportunity Index or demand-versus-supply verdict is emitted for that topic.
3. **Given** a Market topic with qualified demand evidence but insufficient qualified supply
   measurement, **When** analysis runs, **Then** no saturation or whitespace verdict is emitted.
4. **Given** one qualified demand observation and either two qualified supply observations from
   independent sources or two healthy relevant supply surfaces that both return no qualified
   observations, **When** analysis runs, **Then** the topic is eligible for a demand-versus-supply
   verdict.
5. **Given** every topic in a Market mission lacks sufficient qualified evidence, **When** analysis
   completes, **Then** the result explicitly states that relevant evidence is insufficient,
   returns no Opportunity Index, and does not relabel missing evidence as zero demand or supply.
6. **Given** evidence qualification is unavailable or fails, **When** Market analysis runs,
   **Then** the system fails closed and exposes the unavailable qualification state instead of
   using unassessed observations as support.

---

### User Story 3 - Handoff Only a Qualified Attention Candidate (Priority: P2)

As a requester exploring Attention, I want Ignis to say when no topic is qualified for Market
handoff, so that I am not steered into investigating the least-bad item in a noisy result set.

**Why this priority**: The validation handoff selected an adjacent cluster only because every other
candidate was worse. A ranked list is not evidence that any candidate clears a useful bar.

**Independent Test**: Analyze one Attention mission containing only unrelated or adjacent clusters
and one containing a coherent in-scope cluster backed by independent sources. Verify that the first
offers no qualified handoff candidate and the second offers only the supported cluster.

**Acceptance Scenarios**:

1. **Given** an Attention cluster unrelated to the mission's declared title, seed, and keywords,
   **When** candidates are produced, **Then** that cluster is not recommended for Market handoff.
2. **Given** an adjacent cluster that is interesting but does not directly address the declared
   Attention scope, **When** results are presented, **Then** it may remain visible as context but is
   not labelled a qualified handoff candidate.
3. **Given** an in-scope cluster backed by at least two independent source records, **When**
   Attention candidates are produced, **Then** it may be offered for Market handoff with its
   evidence and qualification reason.
4. **Given** no cluster clears the qualification contract, **When** Attention analysis completes,
   **Then** it returns an explicit no-qualified-candidate outcome rather than selecting a fallback.

---

### User Story 4 - Inspect Why Evidence Was or Was Not Used (Priority: P2)

As a requester or reviewer, I want analyses and artifacts to show how many observations were
qualified, contextual, excluded, or unassessed and why, so that I can audit the boundary between
raw collection and a market conclusion.

**Why this priority**: Users must be able to distinguish low coverage from low relevance. A single
composite confidence score currently hides that difference.

**Independent Test**: Produce a Market analysis containing qualified, contextual, irrelevant, and
unassessed observations, then verify that the response and generated artifact expose each count,
the question-relevance score, the insufficient-evidence state, and citations restricted to
qualified support.

**Acceptance Scenarios**:

1. **Given** a completed mission, **When** analysis is requested, **Then** the quality scorecard
   reports question relevance separately from language, freshness, coverage, and creator diversity.
2. **Given** observations with different qualification outcomes, **When** analysis or an artifact
   is rendered, **Then** it reports counts for qualified support, context-only evidence, excluded
   evidence, and unassessed evidence.
3. **Given** a Market conclusion, **When** its citations are inspected, **Then** every supporting
   observation is qualified for the same Market Brief revision and no Attention context or excluded
   observation appears as support.
4. **Given** a low-relevance dataset with otherwise high freshness and creator diversity, **When**
   confidence is calculated, **Then** the overall confidence cannot be `MEDIUM` or `HIGH`.

### Edge Cases

- A title contains every probe keyword but describes fiction, sports, lotteries, or unrelated news.
- A relevant item uses synonyms instead of any literal mission keyword.
- A single external source is observed through more than one connector surface.
- Demand is qualified but every healthy supply surface returns no qualified observations.
- One supply surface is healthy and empty while another is unavailable, rate limited, or unauthenticated.
- Evidence is relevant to the general topic but not to the confirmed target user or problem.
- An Attention cluster is adjacent and useful as context but does not justify Market handoff.
- Evidence qualification times out or returns no decision for some observations.
- A Market Brief revision changes the target user or hypothesis while observations from the prior
  revision remain available as lineage.
- A legacy mission has no declared Attention or Market surface.

## Requirements

### Functional Requirements

- **FR-001**: Every mission ingress path MUST synchronize the database-backed vocabulary and probe
  templates it depends on before the first connector probe begins.
- **FR-002**: Cold-start and warm-process runs with the same persisted configuration and mission
  inputs MUST expose the same eligible connector surfaces and vocabulary registrations.
- **FR-003**: If required vocabulary synchronization fails, the mission MUST fail clearly before
  connector results are interpreted under partial configuration.
- **FR-004**: Raw observations MUST remain immutable and MUST NOT be deleted merely because they are
  irrelevant to one mission.
- **FR-005**: Evidence qualification MUST be scoped to a mission and, for Market, to the exact
  confirmed Market Brief revision.
- **FR-006**: Qualification MUST distinguish at least qualified support, context-only evidence,
  excluded irrelevant evidence, and unassessed evidence.
- **FR-007**: A literal keyword match MUST NOT by itself qualify an observation as support.
- **FR-008**: Market qualification MUST evaluate whether an observation addresses the confirmed
  target user, problem, hypothesis, or decision in addition to the investigated topic.
- **FR-009**: Attention qualification MUST evaluate a cluster against the mission's declared title,
  seed, and keywords without introducing a Market verdict.
- **FR-010**: The system MUST preserve the qualification outcome and reason used for a completed
  mission so the same report does not change when reopened until a new completed ingress run, a new
  mission, or a new Brief revision changes its evidence frame.
- **FR-011**: A Market topic MUST NOT emit an Opportunity Index unless it has at least one qualified
  demand observation and a qualified supply measurement.
- **FR-012**: A positive supply measurement requires at least two qualified observations from two
  independent canonical sources.
- **FR-013**: A zero-supply measurement requires at least two relevant supply connector surfaces to
  complete successfully and return no qualified observations; unavailable, rate-limited,
  unauthenticated, or unassessed surfaces MUST NOT be treated as zero supply.
- **FR-014**: When a Market topic does not meet the evidence minimum, the system MUST expose an
  insufficient-relevant-evidence outcome and MUST NOT emit a saturation, whitespace, or demand-gap
  verdict for that topic.
- **FR-015**: When no Market topic meets the evidence minimum, the mission response and artifact MUST
  omit the Opportunity Index and explicitly state that qualified evidence is insufficient.
- **FR-016**: Evidence qualification failure or unavailability MUST fail closed for Market verdicts;
  unassessed observations MUST NOT be counted as support.
- **FR-017**: The quality scorecard MUST report question relevance separately from coverage,
  localization, freshness, and creator diversity.
- **FR-018**: Overall confidence MUST be `LOW` or `UNRELIABLE` when no Market topic has sufficient
  qualified evidence, regardless of the other quality dimensions.
- **FR-019**: Every Market conclusion, strategic insight, and actionable takeaway MUST cite only
  observations qualified for the same Market Brief revision or an explicit healthy no-data
  measurement that satisfies FR-013.
- **FR-020**: Attention context MUST remain distinct from Market support and MUST NOT satisfy Market
  evidence minimums.
- **FR-021**: An Attention candidate MUST be directly relevant to the declared Attention scope and
  backed by at least two independent canonical sources before it is labelled qualified for handoff.
- **FR-022**: When no Attention cluster satisfies FR-021, the system MUST return an explicit
  no-qualified-candidate outcome and MUST NOT select a fallback candidate.
- **FR-023**: Responses and artifacts MUST report counts for qualified support, context-only,
  excluded, and unassessed evidence, plus the reason an Opportunity Index or handoff candidate was
  withheld.
- **FR-024**: Macro or news observations MAY remain visible as context but MUST NOT contribute to
  market demand or supply unless they independently satisfy the Market qualification contract.
- **FR-025**: Existing missions without a declared research surface MUST retain their current
  behavior; this feature MUST NOT retroactively reinterpret or mutate their evidence.
- **FR-026**: Behavioral contracts MUST cover SQLite and PostgreSQL and MUST include semantic
  negative controls where keyword-matched but unrelated content is refused as support.

### Key Entities

- **Evidence Qualification**: The mission-scoped decision that an immutable observation is
  qualified support, context only, excluded as irrelevant, or unassessed, including a reason and
  the mission frame used for that decision.
- **Question Relevance Score**: A quality dimension summarizing how much of the collected evidence
  directly addresses the declared Attention scope or confirmed Market Brief.
- **Qualified Demand Measurement**: Search or intent evidence that is relevant to the investigated
  topic and confirmed Market Brief.
- **Qualified Supply Measurement**: Either sufficient relevant content from independent sources or
  a measured absence across enough healthy relevant supply surfaces.
- **Evidence Sufficiency Outcome**: The topic- and mission-level result stating whether the minimum
  evidence contract is met and, when it is not, why a verdict was withheld.
- **Qualified Handoff Candidate**: An Attention cluster that is directly relevant to the declared
  scope and backed by independent canonical sources; it is a candidate for a new Market Brief, not
  a market verdict.

## Success Criteria

### Measurable Outcomes

- **SC-001**: In 100% of cold-start parity scenarios, the first mission and an equivalent warm
  mission register the same persisted vocabulary and invoke the same eligible connector surfaces.
- **SC-002**: In 100% of semantic negative-control scenarios, keyword-matched but unrelated
  observations contribute to neither demand, supply, Market conclusions, nor handoff eligibility.
- **SC-003**: In 100% of Market scenarios that lack the minimum qualified evidence, no Opportunity
  Index, saturation verdict, whitespace verdict, or demand-gap verdict is emitted.
- **SC-004**: In 100% of positive-control Market scenarios that meet the demand and supply evidence
  minimums, the qualified topic remains eligible for an Opportunity Index and its citations contain
  only qualified support.
- **SC-005**: In 100% of Attention scenarios where no cluster meets the qualification contract, the
  result explicitly reports no qualified handoff candidate and selects no fallback.
- **SC-006**: Every analysis response and generated artifact exposes question relevance, all four
  qualification counts, and a machine-readable reason when a verdict or handoff candidate is
  withheld.
- **SC-007**: Reopening a completed mission returns the same stored qualification outcomes and
  sufficiency decision until a new completed ingress run, a new mission, or a new Market Brief
  revision changes its evidence frame.
- **SC-008**: SQLite and PostgreSQL pass the same cold-start, evidence-sufficiency, semantic
  negative-control, lineage-isolation, and artifact contract scenarios.
- **SC-009**: The accepted post-v0.5 validation corpus is replayed from a committed, redacted
  acceptance fixture and changes from `0/21` supported Market conclusion units to zero emitted
  unsupported conclusion units; supported controls continue to produce conclusions.

## Assumptions

- The Market Brief remains the requester-confirmed authority for Market question relevance.
- Attention relevance is evaluated against the mission title, seed, and keywords because Attention
  intentionally has no Market Brief.
- Canonical source identity is used to count independent sources; repeated sightings of one source
  do not satisfy a multi-source minimum.
- Qualification is downstream analysis. Connector ingestion remains deterministic and stores raw
  observations even when they may later be excluded from a particular mission's conclusions.
- The initial demand and supply minimums in FR-011 through FR-013 are product safety defaults, not
  configurable tuning knobs in this feature.
- A model-assisted qualifier may be used behind a typed boundary, but provider selection and
  fallback behavior are implementation decisions constrained by fail-closed Market semantics.
- Live Alerts, new connectors, taxonomy expansion, regional expansion, and retroactive
  reclassification of legacy missions are outside this feature.
