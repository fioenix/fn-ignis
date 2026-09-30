---
name: ignis-collect
description: Collect bounded social evidence with Ignis when a user requests a source probe, social listening, or a mission collection frame. Use it for collection without requiring market analysis.
---

# Ignis collection

The output is a bounded evidence frame that says what was queried, which surfaces answered, and
what was unavailable. Design for the requester who needs inspectable source material before making
a business decision.

Read the relevant collection and qualification rules in
`specs/011-evidence-grounded-product-reset/contracts/` and the current MCP tool descriptions
before calling a tool. The persisted Mission Manifest, collection plan, channel outcomes, and
evidence frame are the shared policy; this skill does not define a second policy.

## Choose the smallest request

1. For one source-specific question, call the relevant atomic connector tool. Return its source
   identity, query, scope, collection time, and channel state. Stop after answering the request.
2. For a bounded multi-source frame, propose and confirm a research workspace, then call
   `create_attention_mission` or `confirm_market_brief` with the requester's confirmed Mission
   Manifest. Call `execute_mission_ingress` once for the assigned mission.
3. Inspect the returned collection-plan digest, frame digest, and every declared channel outcome.
   Treat an unavailable surface as missing evidence. An exact measured empty result has its own
   `EMPTY_NO_DATA` state. See [the frame example](examples/collection-frame.md).
4. Return evidence and operational limits. Start analysis only when the requester assigned an
   analysis task; the collection result is useful on its own.

User-supplied files, URLs, and purchased datasets are context for forming a query. Associate any
record used as primary Market evidence with an authorized mission and qualify it against that
mission's current frame.

Completion criterion: each requested surface has a recorded outcome, source provenance is readable,
and the task has reached its declared stop condition.
