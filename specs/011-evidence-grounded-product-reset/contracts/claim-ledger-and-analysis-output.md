# Contract: Claim Ledger and Analysis Output

## Outcome

Every rendered strategic statement is traceable to an exact Mission, Brief revision, evidence
frame, inference method, and set of supporting or contradicting records. Narrative style may vary;
the evidentiary permission cannot.

## Candidate-claim submission

The host submits 1–50 candidate claims against the current `frame_digest`:

```json
{
  "client_claim_key": "stable caller key",
  "claim_type": "OBSERVATION | MEASUREMENT | INFERENCE | ASSUMPTION | RECOMMENDATION | UNKNOWN",
  "wording": "exact wording to render",
  "inference_method": "method identifier and version",
  "metric_denominator": "required for MEASUREMENT or null",
  "metric_timeframe": "required for MEASUREMENT or null",
  "confidence": 0.0,
  "limitations": ["string"],
  "change_conditions": ["string"],
  "evidence_bindings": [
    {
      "observation_id": "uuid or null",
      "probe_outcome_id": "uuid or null",
      "role": "SUPPORT | CONTRADICTION | CONTEXT",
      "hypothesis_target": "core | alternative:<id> | null | null"
    }
  ]
}
```

Exactly one of `observation_id` and `probe_outcome_id` is present per binding. A probe outcome can
support measured absence only when its state is `EMPTY_NO_DATA` for the exact frame.

## Validation and persistence

- `OBSERVATION` binds to at least one current observation and needs no invented confidence.
- `MEASUREMENT`, `INFERENCE`, and `RECOMMENDATION` name their method and evidence bindings.
- `MEASUREMENT` carries its own denominator and timeframe; these are persisted with the claim and
  cannot be enabled or bypassed through a batch-level option.
- `INFERENCE` and `RECOMMENDATION` include limitations and change conditions.
- Support and contradiction bindings agree with persisted qualification roles.
- A strategic claim cannot be `PERMITTED` when the mission sufficiency decision is not ready.
- Submission is idempotent on `(mission_id, frame_digest, client_claim_key)`.
- A replay that changes the payload for the same key is refused.
- A new evidence frame does not mutate old claims; read projections mark them `SUPERSEDED`
  for current rendering using the same transaction snapshot as frame and sufficiency derivation.
- A frame change detected after a batch commits returns `CONFLICT` / `STALE_FRAME` with
  `WITHHELD` rendering and zero permitted claims. The response reports the actual recorded count;
  the immutable audit candidates remain stored but cannot render for another frame.

The repository persists both permitted and withheld candidates so an audit can distinguish “not
considered” from “considered but blocked.”

## Analysis response

A ready response contains:

- mission, manifest, Brief revision, collection-plan, and evidence-frame identities;
- channel outcomes and qualification counts;
- all current permitted claims grouped by claim type;
- contradictory evidence and material limitations adjacent to the claims they affect;
- withheld claim count and machine-readable reasons;
- retention, redaction, platform-policy, and reuse limitations.

An insufficient response contains only:

- `analysis_status: INSUFFICIENT_EVIDENCE`;
- withheld outputs and failed gates;
- missing evidence or metric;
- attempted probes and their exact channel states;
- safe partial conclusions, if any;
- the smallest next-best probe and required authority or known cost.

It does not contain null, zero, placeholder, dimmed, or prose-caveated versions of forbidden
strategic scores.

## Deterministic artifact contract

`generate_mission_artifact` renders only persisted current-frame records through maintained builders
and templates under `src/ignis/infrastructure/templates/html/`.

- A ready Market artifact renders the Claim Ledger, supporting and contradictory evidence, channel
  coverage, limitations, and decision conditions.
- An insufficient Market artifact renders the Gap Report and omits forbidden verdict sections.
- An Attention artifact may rank attention signals but contains no Market verdict.
- Artifact text never becomes the canonical claim source; persisted claims remain authoritative.
- The artifact records the frame digest and template revision needed for reproduction.
- Canonical claim wording stays unchanged; outward claim/analysis projections and HTML exports
  sanitize personal data in all nested fields, including limitations and change conditions.
