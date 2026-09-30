# Contract: Hypothesis Register and Evidence Qualification

## Outcome

Every Market mission tests a falsifiable decision frame rather than accumulating material that
confirms the initial belief. Supporting and contradictory evidence are judged with the same quality
standard and remain visible in every downstream decision surface.

## Confirmed Market Brief

A new or revised Market Brief is valid only when it contains:

- the decision, target user, problem, geography, and timeframe;
- one falsifiable core hypothesis;
- at least two credible and distinct alternative hypotheses;
- one credible null hypothesis;
- at least one falsifier and at least one kill criterion;
- one revision rule stating when the question must be reframed;
- the confirmed Mission Manifest and confirmer identity.

The immutable frame fingerprint covers every field above. An earlier Brief missing the expanded
hypothesis register is readable but cannot be upgraded in place or assigned fabricated values.

## Collection-plan requirement

Before a strategic run begins, the plan names each probe's:

- query family and exact connector surface;
- hypothesis target: core, a named alternative, null, or neutral context;
- expected evidence role: support, contradiction, or context;
- declared audience, geography, timeframe, sampling limit, and authority tier.

At least one probe must be capable of finding counterevidence. Merely labeling a confirmatory query
as “contradiction” does not satisfy this contract.

## Qualification assessment

```json
{
  "observation_id": "uuid",
  "relation": "QUALIFIED_SUPPORT | QUALIFIED_CONTRADICTION | CONTEXT_ONLY | EXCLUDED_IRRELEVANT | UNASSESSED",
  "purpose": "DEMAND | SUPPLY | VOC | CONTEXT",
  "hypothesis_target": "core | alternative:<id> | null | null",
  "evidence_role": "SUPPORT | CONTRADICTION | CONTEXT",
  "confidence": 0.0,
  "reason_code": "typed reason code",
  "judged_by": "host identifier",
  "model": "optional model identifier"
}
```

Rules:

- `QUALIFIED_SUPPORT` requires `SUPPORT` and a non-null hypothesis target.
- `QUALIFIED_CONTRADICTION` requires `CONTRADICTION` and a non-null hypothesis target.
- `CONTEXT_ONLY` requires `CONTEXT`; its hypothesis target is optional.
- `EXCLUDED_IRRELEVANT` and `UNASSESSED` contribute to no conclusion.
- Relation is not inferred from sentiment, popularity, or keyword overlap.
- An identical replay is idempotent. A changed judgment needs a new mission or Brief revision.
- A stale frame fingerprint, duplicate item, foreign observation, or invalid enum rejects the whole
  batch.

## Channel outcome contract

Every manifest-declared surface has exactly one persisted outcome:

| State | Interpretation | Eligible as measured zero |
|---|---|---|
| `HEALTHY` | Declared measurement completed with observations | No |
| `EMPTY_NO_DATA` | Exact declared measurement completed with no qualifying observations | Yes |
| `AUTH_REQUIRED` | Required authority was unavailable | No |
| `RATE_LIMITED` | Quota/rate boundary prevented measurement | No |
| `DEGRADED` | Measurement was partial or soft-failed | No |
| `FAILED` | Measurement did not complete | No |
| `NOT_REQUESTED` | Known surface was not executed in this run | No |

A missing outcome row is a persistence error, not an implied state.

## Sufficiency decision

Sufficiency is deterministic policy over persisted facts. It runs before candidate strategic prose
is accepted and checks at minimum:

- required channels and metrics were actually measured;
- all current evidence was assessed or explicitly terminal-unavailable;
- support and contradiction coverage satisfy the declared analysis policy;
- the evidence frame and Brief revision are current;
- the claimed calculation has its required denominator and timeframe.

If any required gate fails, the only permitted strategic output is a Gap Report. Safe direct
observations may remain visible, but Opportunity Index, whitespace, saturation, demand-gap, and
commercial recommendations are withheld.

