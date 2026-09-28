# Contract: Qualified Analysis and Artifacts

## Common qualification block

Attention and Market analysis responses add:

```json
{
  "qualification": {
    "status": "READY",
    "total_evidence": 60,
    "qualified_support": 8,
    "context_only": 12,
    "excluded_irrelevant": 40,
    "unassessed": 0,
    "question_relevance_score": 13.3,
    "reason": null
  }
}
```

Allowed statuses:

- `QUALIFICATION_REQUIRED`: current evidence is missing a persisted judgment;
- `READY`: every current evidence row is assessed and at least one qualified outcome exists;
- `INSUFFICIENT_RELEVANT_EVIDENCE`: assessment is complete but no topic/candidate meets policy;
- `UNAVAILABLE`: assessment contains evaluator failures or cannot be trusted; and
- `NOT_APPLICABLE`: mission has no declared research surface and retains legacy behavior.

## Market response

### Qualification pending

```json
{
  "analysis_status": "QUALIFICATION_REQUIRED",
  "surface": "MARKET",
  "opportunity_index_applies": false,
  "market_opportunities": [],
  "strategic_insights": [],
  "actionable_takeaways": [],
  "qualification": {
    "status": "QUALIFICATION_REQUIRED",
    "unassessed": 35,
    "reason": "Current mission evidence still requires semantic qualification.",
    "reason_code": "QUALIFICATION_INCOMPLETE"
  },
  "next_step": "Read the pending evidence with get_mission_evidence_qualification_batch, judge it, and record the judgments with submit_mission_evidence_qualifications."
}
```

Raw top signals, persisted channel outcomes, Market Brief, and lineage remain readable. The empty
conclusion lists mean “not yet permitted”, not “the market has no signal”.

### Assessment complete but insufficient

```json
{
  "analysis_status": "INSUFFICIENT_RELEVANT_EVIDENCE",
  "surface": "MARKET",
  "opportunity_index_applies": false,
  "market_opportunities": [],
  "qualification": {
    "status": "INSUFFICIENT_RELEVANT_EVIDENCE",
    "question_relevance_score": 3.3,
    "reason": "No topic has both qualified demand and qualified supply measurement."
  }
}
```

The quality scorecard contains `question_relevance_score` and `qualification_counts`. Overall
confidence is at most `LOW`. A result with any unassessed/evaluator-unavailable evidence is
`UNRELIABLE` rather than `LOW`.

### Sufficient topic

Only sufficient topics appear in `market_opportunities`. Each opportunity adds:

```json
{
  "evidence_sufficiency": "SUFFICIENT_POSITIVE_SUPPLY",
  "qualified_demand_count": 1,
  "qualified_supply_count": 3,
  "independent_supply_sources": 3
}
```

All opportunity, insight, and takeaway citations reference `QUALIFIED_SUPPORT` rows for this
mission and Brief revision. Context-only, excluded, unassessed, and inherited Attention observations
never appear as support.

## Attention response

Attention continues to set `opportunity_index_applies: false` unconditionally. It adds:

```json
{
  "handoff_status": "NO_QUALIFIED_CANDIDATE",
  "qualified_handoff_candidates": [],
  "qualification": {
    "status": "INSUFFICIENT_RELEVANT_EVIDENCE",
    "reason": "No cluster is directly relevant and backed by two independent sources."
  }
}
```

Adjacent and excluded clusters may remain in the exploratory ranked-topic display with their
qualification labels. They are not silently promoted as the next Market question.

## Persisted channel outcomes

`channel_summaries` for a workspace mission are reconstructed from the latest completed run's
`MissionProbeOutcome` records plus that run's observations. They do not use current process health
to rewrite history.

An `EMPTY_NO_DATA` outcome can support a measured zero only when:

- the surface was relevant to the topic's supply query;
- the stored query fingerprint belongs to the same run/frame; and
- the surface completed successfully.

## Artifact contract

The maintained HTML builder and template render the same qualification status as the MCP response:

- a visible question-relevance dimension;
- counts for qualified, context-only, excluded, and unassessed evidence;
- an explicit withheld-verdict panel when qualification is pending or insufficient;
- no Opportunity Index card or chart when `opportunity_index_applies` is false; and
- a visible no-qualified-candidate message for Attention.

The artifact must not infer or recompute semantic qualification. It renders the canonical persisted
outcomes and deterministic sufficiency result supplied by the application layer.

## Legacy compatibility

Missions whose `surface` is null keep their current analysis and artifact behavior. The new
qualification fields may be absent or report `NOT_APPLICABLE`; no new gate is imposed retroactively.
