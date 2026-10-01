# Contract: Mission-Bound Public Surface

## Outcome

The public MCP surface exposes one mission-bound product. It can perform a bounded tactical probe or
an explicit `ATTENTION`/`MARKET` mission, but it cannot start recurring, idle, scheduled, or unscoped
research work.

This contract is the planned breaking boundary. Implementation requires the owner's separate
approval before any existing MCP signature is changed or removed.

## Operations removed in the breaking release

The following eight operations are removed together, without aliases, redirects, or a deprecation
period:

- `run_autonomous_research_mission`
- `create_research_mission`
- `get_trending_topics`
- `get_topic_detail`
- `generate_trend_artifact`
- `trigger_ingress_refresh`
- `trigger_autonomous_discovery`
- `get_latest_daily_discovery`

Their scheduler CLI entrypoints, Docker worker service, scheduled trigger path, daily-discovery
artifact builders, and dedicated configuration are removed in the same release after a consumer
audit proves that no retained path depends on them.

## Operations retained without product-semantic changes

All existing operations not named in the removal or changed sections remain public. This includes:

- atomic collection and enrichment operations for Google Trends, YouTube, TikTok, Threads, and
  Instagram Reels;
- connector authentication, status, health, and credential-clear operations;
- runtime configuration, diagnostics, vocabulary, and noise-list operations;
- workspace proposal, confirmation, listing, session lookup, and writer recovery operations;
- mission quality evaluation and opportunity discovery, subject to the evidence gates below.

An atomic collection operation may return observations and channel state. It never creates a
strategic verdict or starts follow-up work by itself.

## Operations with changed request or response contracts

### `create_attention_mission`

Adds a confirmed Mission Manifest to the request:

```json
{
  "requested_outcome": "string",
  "allowed_resources": ["connector-surface"],
  "authority_boundary": {
    "public_http": true,
    "official_api": false,
    "browser_session": false,
    "paid_quota": false
  },
  "output_type": "COLLECTION_FRAME | ATTENTION_REPORT",
  "stop_conditions": ["string"],
  "retention_policy": "string"
}
```

The mission cannot open unless the manifest is internally consistent with the selected platforms.

### `confirm_market_brief`

Retains the existing confirmed Market Brief fields and adds:

```json
{
  "alternative_hypotheses": ["at least two unique statements"],
  "null_hypothesis": "string",
  "kill_criteria": ["at least one criterion"],
  "revision_rule": "string",
  "mission_manifest": { "...": "same shape as create_attention_mission" }
}
```

Legacy Briefs remain readable, but cannot authorize a new strategic run until a new revision
satisfies this contract.

### `execute_mission_ingress`

The request remains an explicit one-run action. Its result adds:

- `manifest_digest` and `collection_plan_digest`;
- one outcome for every manifest-declared channel;
- exact channel states from `HEALTHY`, `EMPTY_NO_DATA`, `AUTH_REQUIRED`, `RATE_LIMITED`,
  `DEGRADED`, `FAILED`, and `NOT_REQUESTED`;
- scope attestation and an operational note where required;
- an explicit terminal or next state, never a scheduled continuation.

### `get_mission_evidence_qualification_batch`

The batch frame adds the hypothesis register and collection-plan identity so the host can judge
support and contradiction against the same immutable frame.

### `submit_mission_evidence_qualifications`

Each assessment additionally accepts:

- relation `QUALIFIED_CONTRADICTION`;
- `hypothesis_target` for support and contradiction;
- `evidence_role`: `SUPPORT`, `CONTRADICTION`, or `CONTEXT`.

Submission remains atomic, frame-bound, idempotent for identical replay, and fail-closed for stale
or foreign evidence.

### `get_mission_analysis`, `discover_market_opportunities`, and `generate_mission_artifact`

These operations read the persisted sufficiency decision and Claim Ledger. When the frame is
insufficient they return a Gap Report and omit strategic verdicts, opportunity scores, and
demand-versus-supply conclusions. A host cannot enable them with a prose override.

## New operations

### `submit_mission_claims(mission_id, frame_digest, claims)`

Records 1–50 typed candidate claims for the exact current evidence frame. The operation validates
claim type, evidence bindings, qualification roles, sufficiency, limitations, and change
conditions. It returns each claim as `PERMITTED` or `WITHHELD`; canonical audit wording is never
rewritten, while outward projections sanitize personal data. Frame identity, sufficiency, and
claim selection use one read-only database snapshot. A frame change detected after committing
the batch returns `CONFLICT` / `STALE_FRAME`, `WITHHELD` rendering, zero permitted claims, and
the actual recorded count; retained candidates are audit history, not current findings.

### `get_mission_claims(mission_id)`

Returns the current frame digest, persisted claims, evidence bindings, and render status. Claims
bound to an older frame remain auditable but are `SUPERSEDED` and cannot render as current findings.
Supersession is a non-mutating read projection, never a destructive write performed by a reader.

## Forbidden compatibility behavior

- No retained operation may silently create a legacy surface-null mission.
- No tactical probe may enqueue another probe after returning.
- No `monitor`, `daily`, `schedule`, or `continuous` request may be translated into a background
  loop; the response must state that recurring monitoring is outside the product contract.
- No missing, failed, unauthenticated, or rate-limited channel may be translated into measured zero.
- No external dataset may become primary Market evidence without mission-scoped verification and
  qualification.
