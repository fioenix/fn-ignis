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

## Opt-in host-browser search

Use this path only when the requester authorizes their live browser for the exact public TikTok
query batch and the host provides supported navigation and read-only DOM evaluation. Read the live
`prepare_host_browser_search`, `submit_host_browser_search`, and `cancel_host_browser_search` schemas.
This path is not a default collector or an automatic fallback.

Prepare explicit task/session references, result and lifetime bounds, and authorization. For MISSION,
use the existing confirmed mission ID, queries=[] and result_limit=20; the complete query union
including falsifiers comes from that mission. Preparation holds no mission writer while waiting.

Open the returned loopback relay through host browser tooling. Read its #request and #extractor
fields into host memory. Reuse one authorized session and one task-created public search tab.
Before each navigation check task cancellation/expiry and owner interruption; execute only the
returned exact URLs. Evaluate the packaged extractor on each matching page and retain the JSON.
Once every query has an answer, fill the relay's Search answer JSON field directly from that retained
object and click Stage answer. Call MCP submit with IDs only, then read back observations/outcomes
or canonical mission run/frame. A failed or uncertain ingestion requires journal/frame readback.

Unsupported host transport stops before collection. Never reconstruct result records in model
tool arguments. Unverified/failed search is DEGRADED; explicit verified no-results differs from it.
Counters, publication dates and windows the extractor did not measure remain unknown. The visible
grid is a bounded sample, not representative demand or a commercial conclusion.

On cancellation, failure or completion stop navigating, cancel a nonterminal request when possible,
and close task-created tabs in the host's finally path. Preserve owner tabs and browser. The relay
closes on submission, rejection, cancellation, expiry or server exit; it cannot close Chrome itself.
