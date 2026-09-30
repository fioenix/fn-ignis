# Research: Evidence-Grounded Product Reset

## Inputs reviewed

- Approved product proposal: `docs/PRODUCT_PROPOSAL.vi.md`.
- Competitive research archive:
  `/Users/fioenix/Documents/Ignis_Competitive_Landscape_Research_20260929/ignis_competitive_landscape_report.md`.
- Accepted workspace and evidence decisions in `docs/decisions/` and Specs 007–008.
- Current constitution 2.0.0.
- Live source inventory for MCP tools, worker/scheduler entrypoints, connector registry, persistence,
  maintained templates, bootstrap files, manifests, tests, and canonical documentation.

The competitive evidence was not refreshed during planning. This plan inherits the proposal's
stated limits: OSS candidates were not installed and exercised, and authenticated Perplexity
Computer behavior was not tested.

## Decision 1: One mission-bound product, not two runtime tracks

**Decision**: Remove unattended collection as a product capability. The only valid execution
surfaces are an explicit atomic connector request or a workspace-scoped `ATTENTION`/`MARKET`
mission. Autonomy begins after assignment and ends at the mission boundary.

**Rationale**: This traces compute and quota to a requested outcome and prevents a shared baseline
from silently becoming evidence for a question it was not collected to answer.

**Alternatives considered**:

- Keep the worker as an optional advanced mode: rejected because optional code still creates public
  contracts, maintenance cost, and two sources of truth.
- Pause rather than remove the worker: rejected because a dormant compatibility surface keeps the
  old product model alive and complicates every connector decision.

## Decision 2: Recommend removal of the entire unscoped radar surface

**Decision**: The breaking cutover recommends removing these unscoped operations:

- `run_autonomous_research_mission`
- `create_research_mission`
- `get_trending_topics`
- `get_topic_detail`
- `generate_trend_artifact`
- `trigger_ingress_refresh`
- `trigger_autonomous_discovery`
- `get_latest_daily_discovery`

The scheduler CLI entrypoints, Docker worker service, scheduled trigger enum branch, autonomous
discovery use case, daily report templates/handlers, and scheduler configuration disappear with
them. Atomic connector tools remain available for tactical collection. Workspace tools remain the
only path to strategic `ATTENTION` and `MARKET` analysis.

**Rationale**: Each listed operation either creates a mission without a surface/Brief, reads a
shared global trend corpus, or generates a strategic artifact without the new mission evidence
contract. Retaining them would leave a bypass around FR-006, FR-016, and FR-021.

**Owner gate**: This is the plan's exact recommended signature-removal set. Repository policy still
requires owner confirmation before implementation removes the MCP signatures.

**Alternatives considered**:

- Keep the names and silently redirect them: rejected because a caller would receive different
  semantics under the same contract and because compatibility aliases were explicitly rejected.
- Keep global trend reads as archive inspection: rejected from MVP because the distinction between
  “historical context” and “current evidence” would add a second user-facing mode. Historical data
  can be exported or inspected through a later, explicitly read-only archive contract if a real use
  case appears.

## Decision 3: Extend the Spec 008 evidence core instead of rebuilding it

**Decision**: Preserve canonical sources, immutable observations, mission-evidence associations,
probe outcomes, persisted qualifications, qualification state authority, and deterministic
sufficiency. Add only the missing product-reset contracts:

- mission manifest and stop/authority boundaries;
- full hypothesis register;
- contradiction as a first-class qualification relation;
- complete channel states including `FAILED` and `NOT_REQUESTED`;
- persisted claim ledger and claim-to-evidence bindings; and
- actionable gap output.

**Rationale**: Specs 007–008 already solve the most expensive provenance, workspace, run-journal,
and fail-closed foundations. A parallel model would create the two-truth failure the repository has
repeatedly encountered.

**Alternatives considered**:

- Replace the existing workspace/evidence model: rejected because it would discard accepted,
  verified contracts and multiply migration risk.
- Store the new fields only in workspace JSON: rejected because the configured database is the
  canonical store and copied workspace files are projections, not a backup.

## Decision 4: Use one additive migration for evidence-contract expansion

**Decision**: Plan migration `025` as the next schema step. It adds a mission manifest, extends the
immutable Market Brief with competing hypotheses, expands qualification/channel enums, and adds the
claim ledger. It does not transform scheduled baseline records or delete existing rows.

**Rationale**: The new fields are canonical, cross-host research state and must have SQLite and
PostgreSQL parity. One migration keeps the referential rules and pre/post evidence digest in one
reviewable unit.

**Owner gate**: Planning the migration does not authorize writing or applying it. The owner must
approve migration implementation, and production activation retains Constitution VI gates.

**Alternatives considered**:

- Separate migrations by table: rejected because the feature cannot safely expose a partial state
  where claims exist without the frame or hypothesis register they reference.
- No migration, derive everything at response time: rejected because reopened missions would change
  meaning and host agents could disagree about the same historical frame.

## Decision 5: The host judges semantics; Ignis owns policy and history

**Decision**: A host agent may classify evidence and draft typed candidate claims. Ignis validates
and persists those judgments, applies deterministic sufficiency and authority policy, and refuses
any claim that cannot bind to the current evidence frame. No external AI provider becomes a required
server dependency.

**Rationale**: This preserves provider neutrality and lets Ignis run in Codex, Claude, Perplexity,
or another host while keeping one policy boundary.

**Alternatives considered**:

- Embed a required model provider in the server: rejected because it adds credentials, cost, and
  provider coupling to the self-hosted core.
- Let each host decide whether evidence is sufficient: rejected because one host could promote an
  insufficient frame while another refuses it.

## Decision 6: Contradiction is a relation, not a negative sentiment

**Decision**: Add `QUALIFIED_CONTRADICTION` beside `QUALIFIED_SUPPORT`. It is judged relative to one
explicit hypothesis in the current register and still carries an evidence purpose such as demand,
supply, or Voice of Customer. `CONTEXT_ONLY`, `EXCLUDED_IRRELEVANT`, and `UNASSESSED` remain.

**Rationale**: Evidence can be relevant and high quality while weakening the core hypothesis.
Treating it as context or sentiment would erase the product's critical-thinking contract.

**Alternatives considered**:

- Add a boolean `is_counterevidence`: rejected because one observation may contradict the core but
  support an alternative; a typed target and relation are required.
- Infer contradiction from negative sentiment: rejected because sentiment and hypothesis support
  are different judgments.

## Decision 7: The claim ledger is the report authority

**Decision**: Persist each strategic claim and its evidence bindings before it appears in a report.
Maintained builders render the claim ledger; they do not invent or reclassify claims. Gap reports
are derived from the same mission frame and policy decision.

**Rationale**: Citation formatting is not enough. A claim must preserve wording, type, method,
limitations, frame digest, evidence roles, and what could change it.

**Alternatives considered**:

- Keep claims only in generated HTML: rejected because the artifact would become a second source of
  truth and could not be reproduced safely.
- Persist the entire model transcript: rejected because it is unbounded, provider-specific, and may
  retain sensitive context that is not part of the product contract.

## Decision 8: Two small skills, one MCP contract

**Decision**: Replace the monolithic `fn-ignis-harness` product skill with `ignis-collect` and
`ignis-analyze`. Both call the same MCP server; neither duplicates server policy. Collection may be
tactical. Analysis requires an eligible mission evidence frame.

**Rationale**: Users can pull data without paying the ceremony of a strategic dossier, while the
analysis skill cannot become a generic CSV summarizer that bypasses provenance.

**Alternatives considered**:

- Keep one skill with two long modes: rejected because the current skill already mixes tactical
  tools, a rigid six-step recipe, daily discovery, and analysis promises.
- Build two MCP servers: rejected because it would split evidence authority and duplicate setup.

## Decision 9: Baseline data is triaged, never auto-promoted

**Decision**: Produce a read-only inventory with counts, time range, provenance completeness,
retention reason, and proposed disposition. Archive only data with a stated audit or research reason.
Propose other records for recoverable deletion. No baseline row becomes mission evidence through
the cutover.

**Rationale**: Scheduled data was collected under another purpose and cannot inherit a new mission's
authority after the fact.

**Alternatives considered**:

- Migrate all baseline data into a synthetic mission: rejected because it would invent a task,
  hypothesis, and sampling frame that did not exist.
- Delete everything during upgrade: rejected because deletion requires exact targets and may destroy
  audit history or evidence with a legitimate retention reason.

## Decision 10: Pilot validates the wedge before monetization

**Decision**: Run five Vietnam consumer-market missions covering sufficient evidence, auth block,
high-volume low relevance, contradiction, and missing metric. Compare decision usefulness and
auditability against a generic research agent and a composable OSS workflow. Capture baselines;
do not invent adoption or revenue targets.

**Rationale**: The architectural wedge is not product-market fit. The pilot must show that users
value custody, counterevidence, and refusal enough to accept the added friction.

**Alternatives considered**:

- Ship a hosted product first: rejected because managed operations would mask whether the research
  method itself creates value.
- Optimize connector count first: rejected because coverage is not the chosen competitive axis.

## Resolved unknowns

No `NEEDS CLARIFICATION` item remains for planning. The following are explicit later gates rather
than research unknowns:

- owner approval before writing migration `025`;
- owner approval of the exact MCP signature-removal set before implementation;
- target-specific authorization before any baseline deletion; and
- separate approval for version bump, tag, release, or production migration.
