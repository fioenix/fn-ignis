# MCP Contract: Evidence Qualification

This feature adds two independently callable tools. They carry semantic judgments between the host
Agent and Ignis without making the server depend on an AI provider.

## `get_mission_evidence_qualification_batch`

Returns a bounded, stable batch of current mission evidence that still requires a judgment.

### Input

| Field | Type | Required | Rules |
|---|---|---|---|
| `mission_id` | string | yes | UUID or existing shortcode |
| `cursor` | string | no | Opaque cursor from the preceding response |
| `limit` | integer | no | Default 25; minimum 1; maximum 50 |

### Ready response

```json
{
  "status": "QUALIFICATION_REQUIRED",
  "mission_id": "uuid",
  "shortcode": "VN-MARKET-7D-1234",
  "surface": "MARKET",
  "frame_fingerprint": "immutable-frame-digest",
  "frame": {
    "brief_revision_id": "uuid",
    "decision": "Decide whether to pursue the segment",
    "target_user": "Small Vietnamese retailers",
    "problem": "Manual store operations",
    "hypothesis": "A lightweight AI copilot removes repeated work",
    "falsifiers": ["No repeated operational pain is observed"],
    "geo": "VN",
    "timeframe": "7d"
  },
  "progress": {
    "total_evidence": 60,
    "qualified_support": 0,
    "context_only": 0,
    "excluded_irrelevant": 0,
    "unassessed": 60
  },
  "evidence": [
    {
      "observation_id": "uuid",
      "source_id": "uuid",
      "platform": "youtube",
      "connector_surface": "youtube",
      "title": "Example title",
      "excerpt": null,
      "probe_keyword": "AI cho cửa hàng bán lẻ",
      "metric_highlight": "1200 views",
      "cluster_id": "uuid"
    }
  ],
  "next_cursor": "opaque-or-null",
  "recommended_judgment": {
    "relation": ["QUALIFIED_SUPPORT", "CONTEXT_ONLY", "EXCLUDED_IRRELEVANT", "UNASSESSED"],
    "purpose": ["DEMAND", "SUPPLY", "VOC", "CONTEXT"]
  }
}
```

For Attention, `frame` contains the mission title, seed, keywords, geo, and timeframe and has no
Brief fields. The response never contains credentials, raw browser sessions, prompt transcripts,
or unrelated observation metadata.

### Complete response

When every current mission-evidence row has a persisted assessment:

```json
{
  "status": "READY",
  "mission_id": "uuid",
  "frame_fingerprint": "immutable-frame-digest",
  "progress": {
    "total_evidence": 60,
    "qualified_support": 8,
    "context_only": 12,
    "excluded_irrelevant": 40,
    "unassessed": 0
  },
  "evidence": [],
  "next_cursor": null
}
```

### Refusals

- Unknown mission: `NOT_FOUND`.
- Mission without Attention/Market surface: `NOT_APPLICABLE`; legacy behavior is unchanged.
- Market mission without a readable confirmed Brief: `BLOCKED` using the existing Brief gate.
- Cursor from another mission/frame: `CONFLICT`; no state changes.

## `submit_mission_evidence_qualifications`

Atomically records one bounded batch of typed judgments.

### Input

| Field | Type | Required | Rules |
|---|---|---|---|
| `mission_id` | string | yes | Same mission used to read the batch |
| `frame_fingerprint` | string | yes | Exact immutable-frame digest returned by the read tool |
| `assessments` | array | yes | 1 through 50 unique observations |

Each assessment contains:

| Field | Type | Required | Rules |
|---|---|---|---|
| `observation_id` | string | yes | Must belong to current mission evidence |
| `relation` | enum | yes | `QUALIFIED_SUPPORT`, `CONTEXT_ONLY`, `EXCLUDED_IRRELEVANT`, `UNASSESSED` |
| `purpose` | enum | yes | `DEMAND`, `SUPPLY`, `VOC`, `CONTEXT` |
| `confidence` | number/null | yes | `0.0` through `1.0`; null only for `UNASSESSED` |
| `reason_code` | enum | yes | One code from `data-model.md` |
| `judged_by` | string | yes | Bounded Agent/runtime identifier |
| `model` | string/null | no | Evaluator model metadata; never a credential |

Semantic rules:

- `QUALIFIED_SUPPORT` cannot use purpose `CONTEXT`.
- `CONTEXT_ONLY` must use purpose `CONTEXT`.
- `EXCLUDED_IRRELEVANT` does not contribute to any purpose, even if a caller sends another value.
- `UNASSESSED` requires reason `INSUFFICIENT_CONTENT` or `EVALUATOR_UNAVAILABLE` and null confidence.
- Attention submissions cannot create a Market demand/supply verdict; their purpose is retained for
  audit but only handoff qualification is evaluated.

### Success response

```json
{
  "status": "RECORDED",
  "mission_id": "uuid",
  "recorded": 25,
  "progress": {
    "total_evidence": 60,
    "qualified_support": 4,
    "context_only": 6,
    "excluded_irrelevant": 15,
    "unassessed": 35
  },
  "next_step": "Call get_mission_evidence_qualification_batch with this mission."
}
```

### Atomic refusal contract

The whole batch is refused and no row is written when:

- the frame fingerprint does not match the current mission/Brief;
- any observation does not belong to current mission evidence;
- an observation appears twice in the batch;
- an enum, confidence, or relation/purpose combination is invalid; or
- the mission belongs to another workspace scope.

Submitting the same byte-equivalent judgments again is idempotent. A different judgment for an
already assessed observation returns `CONFLICT`; changing semantic history requires a new mission or
Market Brief revision.

## Recommended host-Agent judgment

TypeSafe-capable hosts should ask independent typed questions over the same state:

1. a `Choice` for relation to the mission frame;
2. a `Choice` for evidence purpose; and
3. a `Noul` asking whether the observation directly supports the declared scope or confirmed Brief.

Code maps low-confidence, failed, or contradictory answers to `UNASSESSED`. Confidence policy is
calibrated against project fixtures; cookbook thresholds are not copied as defaults. Hosts without
TypeSafe may use their own semantic model but must submit the identical typed contract.
