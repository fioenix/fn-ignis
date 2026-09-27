# Research: Decision-Grade Evidence Qualification

## Decision 1: Keep semantic judgment in the host Agent

**Decision**: The MCP server exposes typed qualification batches and accepts typed judgments from
the host Agent. It does not require a new AI provider or API key.

**Rationale**:

- The constitution assigns semantic synthesis to Agent LLMs and requires deterministic ingress.
- Every supported user journey already has an Agent host in the loop.
- SQLite-local must remain useful without provisioning another service or credential.
- Persisting the judgment makes reopened reports stable and avoids repeated token/API cost.
- The server can validate evidence identity and enforce policy even though it cannot prove the
  semantic judgment itself.

TypeSafe was evaluated using its current documentation. A host can use a `Choice` to classify
relation/purpose and a `Noul` to test direct support. Confidence is an uncertainty signal, not proof;
thresholds must be calibrated on Ignis fixtures. TypeSafe remains a recommended host-side
implementation, not a package dependency or hidden server call.

**Alternatives considered**:

- **Required server-side TypeSafe integration**: rejected because it makes an external API key a
  prerequisite for the default self-hosted product.
- **Optional server-side provider abstraction**: rejected for this feature as speculative. There is
  no second concrete provider and host submission already covers the use case.
- **Keyword or taxonomy rules alone**: rejected because the measured defect is keyword-matched
  semantic irrelevance.
- **Embedding similarity alone**: rejected because topical similarity does not establish that an
  item supports, contradicts, or says nothing about the target user, problem, or hypothesis. The
  optional model would also introduce runtime download and availability concerns.

## Decision 2: Persist judgments against mission evidence, not observations globally

**Decision**: One qualification belongs to a mission-evidence pair and the mission frame that was
used to judge it. The immutable observation is unchanged.

**Rationale**:

- The same observation can support one question and be irrelevant to another.
- A Market Brief revision changes the question without changing source evidence.
- The existing `(mission_id, observation_id)` ledger is the canonical statement that a mission used
  an observation.
- A foreign key to that ledger prevents qualifications for evidence the mission does not own and
  removes stale qualification automatically when the evidence association is pruned.

**Alternatives considered**:

- **Store relevance on `observations`**: rejected because it turns a question-relative judgment
  into a global fact.
- **Store qualification only in artifacts or journals**: rejected because those are projections and
  run records, not canonical research state.
- **Recompute every time**: rejected because the same completed mission could change without a new
  Brief or mission revision.

## Decision 3: Persist connector-surface outcomes per run

**Decision**: Every workspace run stores one outcome per eligible connector surface, including
healthy-empty, failed, unavailable, rate-limited, and authentication-required states.

**Rationale**:

- Zero supply is a measured claim, not the absence of a row.
- Current registry health can differ from the state during the completed mission.
- The existing mission journal gives each run a stable identity.
- Per-surface outcomes preserve the established rule that one healthy TikTok surface cannot hide a
  failed TikTok surface.

**Alternatives considered**:

- **Read current registry health during analysis**: rejected because reopened reports can change.
- **Infer success from observations**: rejected because zero observations cannot distinguish a
  healthy empty result from a failed or skipped probe.
- **Store outcomes only in the filesystem journal**: rejected because the database is canonical and
  workspace files are projections.

## Decision 4: Use deterministic sufficiency rules after semantic classification

**Decision**: The semantic judgment labels evidence; code applies the minimum evidence rules.

**Rationale**:

- Minimum counts, source independence, surface health, and fail-closed behavior are deterministic
  policy, not semantic questions.
- Separating judgment from policy makes thresholds reviewable and testable.
- The result remains safe when the Agent is uncertain: `UNASSESSED` contributes nothing.

Initial policy:

- demand: one qualified demand observation;
- positive supply: two qualified supply observations from two canonical sources;
- zero supply: two relevant healthy supply surfaces with zero qualified observations;
- Attention handoff: directly relevant cluster with two canonical sources.

**Alternatives considered**:

- **Ask the model whether evidence is sufficient**: rejected because it hides product policy inside
  an opaque judgment and makes exact negative controls difficult.
- **Copy the validation thresholds (`0.60`, `0.70`) into production**: rejected because they were
  spike review thresholds, not calibrated product policy.

## Decision 5: Block verdicts, not raw evidence access

**Decision**: Qualification-required and insufficient-evidence states remain readable analyses with
raw/context evidence, channel outcomes, and progress. They omit market verdicts and qualified
handoff candidates.

**Rationale**:

- Users need to diagnose why the system refused a conclusion.
- Raw observations remain useful for audit and reframing.
- A structured refusal is safer and more actionable than a transport error.
- Existing Market Brief and lineage contracts remain intact.

**Alternatives considered**:

- **Raise an exception from every analysis read**: rejected because it hides available evidence and
  appears as a server failure.
- **Emit zero-valued Opportunity Index**: rejected because zero reads as a measured balance, not an
  unavailable conclusion.
- **Delete or hide excluded observations entirely**: rejected because exclusion is mission-relative
  and must remain auditable.

## Decision 6: Add two MCP operations

**Decision**: Add one read operation for bounded pending batches and one write operation for atomic
typed submissions.

**Rationale**:

- A read-only batch operation can be retried and paginated independently.
- A write operation can validate the frame and all evidence identities before persisting anything.
- Combining reads and writes in one optional-argument tool would make retries and error states
  ambiguous.

**Alternatives considered**:

- **Overload `get_mission_analysis` with pagination and writes**: rejected because an analysis read
  should remain a read.
- **One submission per observation**: rejected because it increases Agent round trips and permits
  partially written batches without an atomic boundary.

## Decision 7: Do not backfill semantic outcomes

**Decision**: Migration `023` creates empty qualification and probe-outcome tables. Existing
Attention and Market missions report that qualification is required when reopened; missions with
no surface retain their old behavior.

**Rationale**:

- A migration cannot infer semantic judgments or historical connector health honestly.
- Fabricating a successful probe outcome would violate evidence provenance.
- Existing raw observations and lineage remain intact and can be qualified deliberately.

**Alternatives considered**:

- **Mark all existing evidence qualified**: rejected because post-v0.5 validation proved that many
  existing citations are unrelated.
- **Mark all missing surfaces healthy-empty**: rejected because no historical run record supports
  that claim.
