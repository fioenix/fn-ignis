# Data Model: Evidence-Grounded Product Reset

## Existing records retained

- `research_workspaces`: user-visible research scope backed by the configured database.
- `research_missions`: canonical mission identity, surface, status, and workspace relationship.
- `market_brief_revisions`: immutable Market decision frame; extended by this feature.
- `sources`: canonical external-object identity.
- `observations`: immutable collection sightings.
- `mission_evidence`: explicit mission-to-observation association.
- `mission_run_journals`: one collision-safe record per execution.
- `mission_probe_outcomes`: one connector-surface outcome per run; extended by this feature.
- `mission_evidence_qualifications`: one semantic judgment per mission evidence item; extended by
  this feature.

No baseline or legacy trend table becomes mission evidence through migration.

## MissionManifest

One immutable execution and authority contract for one surfaced mission. It is created with the
mission and frozen before connector work begins.

| Field | Meaning | Rules |
|---|---|---|
| `mission_id` | Mission governed by this manifest | Primary key; references `research_missions`; cascade with mission |
| `outcome` | Finished state the requester wants | Required bounded text |
| `decision_context` | Decision owner, decision, and cost of error | Required for Market; bounded text |
| `required_channels` | Connector surfaces whose absence limits or blocks the intended output | Ordered unique list |
| `optional_channels` | Helpful surfaces that do not independently block the output | Ordered unique list; disjoint from required |
| `authority_boundary` | Allowed public/session/token/browser/paid resources | Required structured value; no credential material |
| `quota_budget` | Optional connector-call or cost ceilings | Structured non-negative limits; absent means connector defaults, not unlimited authority |
| `output_type` | Tactical evidence, Attention result, Market analysis, or strategic artifact | Required enum |
| `stop_conditions` | Completion, refusal, cost, authority, or scope-change conditions | Non-empty ordered list |
| `analysis_policy` | Policy identifier governing qualification and claims | Required versioned identifier |
| `created_by` | Requester or host-agent identifier | Required bounded identifier |
| `confirmed_at` | Time the authority boundary became active | Required UTC instant |

**Uniqueness**: one manifest per surfaced mission.

**Immutability**: changing outcome, authority, required channels, or stop conditions creates a new
mission or mission revision. A run cannot edit its own authority after collection begins.

**Tactical collection**: an atomic connector invocation is itself a bounded task assignment and does
not need a persisted `MissionManifest` unless its results are promoted into a research mission. It
must still return its query, scope, channel result, and authority state.

## MarketBriefRevision extensions

The existing immutable Brief keeps `decision`, `target_user`, `problem`, `geo`, `timeframe`, core
hypothesis, falsifiers, confirmation identity, and revision lineage. The feature adds:

| Field | Meaning | Rules |
|---|---|---|
| `core_hypothesis` | Renamed semantic role of existing `hypothesis` field | Required falsifiable statement; storage may retain column name during compatible hydration |
| `alternative_hypotheses` | Other explanations capable of producing the observed pattern | At least two unique non-empty statements |
| `null_hypothesis` | Credible no-signal or no-material-effect explanation | Required non-empty statement |
| `kill_criteria` | Conditions that support stopping or rejecting the opportunity | At least one non-empty criterion |
| `revision_rule` | Conditions that require reframing the problem or outcome | Required bounded text |

All fields participate in the immutable frame fingerprint. Earlier Brief revisions retain their
existing payload and are read as legacy frames that require a new revision before using the new
analysis contract; no hypotheses are fabricated for them.

## CollectionPlan

A versioned projection derived from the mission manifest and hypothesis register before a run. The
database stores its digest and the run journal stores the readable projection.

| Field | Meaning | Rules |
|---|---|---|
| `query_families` | Root, expanded, exclusion, and falsification queries | Versioned; no credential values |
| `evidence_targets` | Core, alternative, null, or neutral question each probe discriminates | Every strategic probe names at least one target |
| `expected_role` | Supporting, contradicting, or neutral/contextual evidence sought | Required enum |
| `connector_surface` | Exact surface to invoke | Must be allowed by the manifest |
| `scope` | Geography, audience, language, and timeframe | Must match the immutable frame |
| `sampling` | Limit, ordering, and available platform constraints | Explicit even when the platform decides ordering |
| `authority_tier` | Public HTTP, official API, or authorized browser/session tier | Must fit authority boundary |
| `plan_digest` | Canonical digest of the plan | Required; stored on run and used in artifact reproduction |

The plan is not a second canonical table in MVP. The mission manifest and Brief remain canonical;
the plan projection is written to the collision-safe run journal and its digest to the run outcome.

## MissionProbeOutcome extensions

The existing record retains run, platform, exact connector surface, signal count, queried keywords,
queried window, query fingerprint, and completion time.

### Channel states

| Status | Meaning | Can measure zero? |
|---|---|---|
| `HEALTHY` | Probe completed and returned one or more observations | No |
| `EMPTY_NO_DATA` | Probe attested to the exact query/scope/window and returned none | Yes, only for that exact frame |
| `AUTH_REQUIRED` | Required auth/session was not available | No |
| `RATE_LIMITED` | Platform quota or rate boundary prevented measurement | No |
| `DEGRADED` | Probe completed only partially or with a soft failure | No |
| `FAILED` | Probe could not complete the declared measurement | No |
| `NOT_REQUESTED` | Surface was known to the manifest but was not executed in this run | No |

The record adds:

| Field | Meaning | Rules |
|---|---|---|
| `scope_attestation` | What audience/geo/window the connector actually measured | Required for `HEALTHY` and `EMPTY_NO_DATA` |
| `note` | Bounded operational explanation | Required for every non-healthy status |
| `collection_plan_digest` | Plan projection used by this run | Required for surfaced missions |

One outcome exists for every manifest-declared channel. A missing row is a persistence failure, not
an implied `NOT_REQUESTED` state.

## EvidenceQualification extensions

The existing record remains scoped to one `(mission_id, observation_id)` pair and immutable frame.

### Relation

| Relation | Meaning | Contributes to a conclusion? |
|---|---|---|
| `QUALIFIED_SUPPORT` | Directly strengthens the named hypothesis/measurement | Yes |
| `QUALIFIED_CONTRADICTION` | Directly weakens the named hypothesis or strengthens a competing one | Yes, as counterevidence |
| `CONTEXT_ONLY` | Relevant context that measures neither support nor contradiction | No |
| `EXCLUDED_IRRELEVANT` | Does not address the frame | No |
| `UNASSESSED` | No reliable judgment was obtained | No |

The record adds:

| Field | Meaning | Rules |
|---|---|---|
| `hypothesis_target` | Core, one alternative, or null hypothesis judged | Required for support/contradiction; references current register identifier |
| `evidence_role` | `SUPPORT`, `CONTRADICTION`, or `CONTEXT` | Must agree with relation |

`purpose` remains `DEMAND`, `SUPPLY`, `VOC`, or `CONTEXT`. Contradiction is not a purpose and is not
derived from sentiment.

## EvidenceFrame

A derived immutable analysis identity, not a separate table.

| Field | Source |
|---|---|
| `mission_id` | Mission |
| `brief_revision_id` | Confirmed Brief for Market; absent for Attention |
| `manifest_digest` | Canonical MissionManifest serialization |
| `collection_plan_digest` | Completed run |
| `observations_digest` | Ordered current mission-evidence identifiers and immutable observation digests |
| `qualifications_digest` | Ordered qualification records |
| `channel_outcomes_digest` | Ordered completed-run surface outcomes |
| `analysis_policy` | MissionManifest |
| `frame_digest` | Canonical digest of all fields above |

Any change to mission evidence or its qualification changes the frame digest and invalidates claims
bound to an older frame. A report never silently rebinds them.

## MissionClaim

One persisted analytical statement permitted for one exact evidence frame.

| Field | Meaning | Rules |
|---|---|---|
| `claim_id` | Stable identity | UUID; database generated |
| `mission_id` | Owning mission | Required; references mission |
| `brief_revision_id` | Exact Market frame | Required for Market; absent for Attention |
| `frame_digest` | Evidence frame used | Required immutable digest |
| `claim_type` | `OBSERVATION`, `MEASUREMENT`, `INFERENCE`, `ASSUMPTION`, `RECOMMENDATION`, or `UNKNOWN` | Required enum |
| `wording` | Exact text approved for rendering | Required bounded text |
| `inference_method` | Bounded method identifier and version | Required for measurement/inference/recommendation |
| `confidence` | Claim-level uncertainty | Decimal 0–1 or absent for assumption/unknown |
| `limitations` | Constraints on use | Required list; may be empty only for direct observation |
| `change_conditions` | Evidence or threshold that could change the claim | Required for inference/recommendation |
| `status` | `PERMITTED`, `WITHHELD`, or `SUPERSEDED` | Only `PERMITTED` renders as a strategic conclusion |
| `created_by` | Host/runtime identifier | Required bounded identifier |
| `created_at` | Persistence time | Required UTC instant |

**Uniqueness**: exact wording is not identity. Multiple claims may use similar text; each is scoped to
its frame. Idempotent submission uses `(mission_id, frame_digest, client_claim_key)`.

## MissionClaimEvidence

Join record binding a claim to the evidence or measured absence that informs it.

| Field | Meaning | Rules |
|---|---|---|
| `claim_id` | Claim | Part of primary key; cascade with claim |
| `observation_id` | Concrete evidence item | Nullable only for a measured-absence binding |
| `probe_outcome_id` | Exact measured-absence surface | Nullable for observation binding |
| `role` | `SUPPORT`, `CONTRADICTION`, or `CONTEXT` | Required |
| `hypothesis_target` | Hypothesis being affected | Required for support/contradiction |

Exactly one of `observation_id` and `probe_outcome_id` is present. Observation bindings must point
to current mission evidence with a compatible persisted qualification. Probe-outcome bindings are
valid only for an exact-frame `EMPTY_NO_DATA` result.

## GapReport

Derived from the manifest, hypothesis register, probe outcomes, qualification progress, and
sufficiency decision. It is returned and rendered but is not a second canonical table.

| Field | Meaning |
|---|---|
| `withheld_outputs` | Verdicts or scores not permitted |
| `failed_gates` | Machine-readable policy reasons |
| `missing_evidence` | Required channel, metric, or hypothesis target not measured |
| `attempted_probes` | What ran and the exact outcome |
| `safe_partial_conclusions` | Statements still permitted by the frame |
| `next_best_probe` | Smallest bounded probe likely to reduce the important uncertainty |
| `required_authority` | New token, session, quota, or scope choice needed, if any |
| `estimated_cost` | Known quota/time consequence; never invented when unknown |

## CapabilityFamily

A packaged host-agent instruction surface, not a database table.

- `ignis-collect`: invokes atomic connectors or mission ingress; returns collection frame and
  channel states; never emits a strategic verdict.
- `ignis-analyze`: frames hypotheses, requests/submits semantic judgments, records candidate
  claims, and renders permitted analysis; refuses arbitrary unverified primary data.

Both packages name the same MCP contracts and contain no independent sufficiency thresholds.

## State transitions

### Surfaced mission

```text
TASK ASSIGNED
  -> MANIFEST CONFIRMED
  -> BRIEF CONFIRMED (MARKET only)
  -> COLLECTION PLANNED
  -> RUNNING
  -> OBSERVATIONS + CHANNEL OUTCOMES PERSISTED
  -> COMPLETED_RAW
  -> QUALIFICATION_REQUIRED
  -> QUALIFICATION_READY
  -> SUFFICIENCY DECIDED
      -> INSUFFICIENT_EVIDENCE -> GAP REPORT -> STOP
      -> READY_FOR_ANALYSIS -> CLAIMS RECORDED -> ARTIFACT -> STOP
```

No state schedules another run. A continuation creates a new run under explicit assignment; a
material frame change creates a new mission/Brief revision.

### Claim lifecycle

```text
CANDIDATE
  -> VALIDATE CURRENT FRAME
  -> VALIDATE EVIDENCE BINDINGS
  -> APPLY SUFFICIENCY POLICY
      -> WITHHELD
      -> PERMITTED -> RENDERABLE
  -> SUPERSEDED when a new mission revision replaces the frame
```

## Migration and legacy behavior

- Migration `025` is additive except for broadening enum/check constraints.
- Existing Briefs are never assigned invented alternatives, null hypotheses, or kill criteria.
  They remain readable and require a new revision for the new analysis contract.
- Existing unscoped missions remain readable for audit but cannot run new collection or generate a
  new strategic verdict after the breaking cutover.
- Existing scheduled baseline records remain outside mission evidence and outside migration `025`.
- SQLite and PostgreSQL enforce the same required fields, foreign keys, uniqueness, check
  constraints, and cascade semantics.

## Deletion and retention

- Deleting a mission cascades its manifest, runs, outcomes, qualifications, claims, and claim
  bindings according to the existing mission-deletion contract.
- Deleting or pruning mission evidence invalidates or cascades the corresponding qualification and
  claim-evidence bindings. A claim with no valid support becomes withheld rather than silently
  remaining permitted.
- Baseline archival/deletion is a separate, explicit cutover operation with inventory, target list,
  recovery method, and post-action verification.
- PostgreSQL applies owner-only access and RLS to new canonical tables; SQLite keeps foreign keys
  enabled.
