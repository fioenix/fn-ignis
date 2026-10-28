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
   Manifest. For non-host collection, call `execute_mission_ingress` once; for opt-in host-browser
   search, follow the path below to collect and submit one mission run.
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

Use the requester's own browser through the host's existing browser tooling, only with explicit
live-browser authorization for this bounded batch. This is not a default collector or an automatic fallback.
Before prepare, check the host can open a tab, click in the relay, evaluate read-only script in a
tab it opened, and close tabs it opened. If any capability is missing, stop before collection:
unsupported transport. Read the live `prepare_host_browser_search`, `submit_host_browser_search`
and `cancel_host_browser_search` schemas. Before opening the relay, use the browser/profile the requester named
for collection and confirm the host tooling is connected to it; with several browsers connected, ask the requester which.
If tooling asks for or refuses origin access (source site or loopback relay), stop and ask the
requester to grant access in the host; ungranted means that source is unavailable for this run.

Call `prepare_host_browser_search` with source="tiktok" or source="threads", explicit task/session
references, authorization, result and lifetime bounds. For MISSION, use the confirmed mission ID,
queries=[] and result_limit=20; the mission supplies the full query union, including falsifiers.
When both sources are in scope, prepare sibling tickets for the same mission/task/session/frame,
stage both before submitting either, and compose one mission run. Preparation holds no mission writer.

Open the returned loopback relay in the confirmed browser. For each query, check
cancellation/expiry and owner interruption, click "Open search" in the relay, wait for results to load,
evaluate `tab_script` once in the relay-opened source tab, then read its status and counts.
The packaged script posts records directly to the relay; the agent only moves between prepared URL,
extractor and relay. Source-tab conduct is read-only: wait for load and run that script only;
no typing, clicking, scrolling, signing in, consenting or challenge solving.
If automatic handoff fails, the manual Stage-answer path transfers the packaged extractor's
retained object directly into the relay's Search answer JSON field and clicks Stage answer;
never reconstruct, transcribe or repair model-built records. Missing host capabilities still stop collection.
Call `submit_host_browser_search` with IDs only after all queries are staged; read back observations/outcomes
or canonical mission run/frame. Failed or uncertain ingestion requires journal/frame readback.

For a visible sign-in wall, challenge, error page or missing grid, the extractor reports `DEGRADED`
(or the validator rejects a mismatched page). On any such state, stop that query, retain the
outcome as reported (unavailable/`DEGRADED`), tell the requester and move on; no retry loop or other collector.
Unverified/failed search is `DEGRADED`; explicit verified no-results differs from it; current Threads
extraction cannot verify empty results. Unmeasured counters, publication dates and windows remain unknown.
The visible grid is a bounded sample, not representative demand or a commercial conclusion.
Use only this host path for search; these alternatives are excluded:
- Separately launched Playwright/headless browsers: blocked despite a valid session on 25/10/2026.
- LLM agents reading/driving pages: periods lose comparability and the charter forbids model-built records.
- Third-party scrape/unblocker services: data leaves the machine; proxy unblocking is evasion.
- CDP / remote debugging: excluded by Spec 012; anti-detection tooling is also excluded.
Reels keeps its flag-free Playwright path, outside this search guidance.
On cancellation, failure or completion, stop navigating, cancel a nonterminal request when possible,
and close task-created tabs in the host's finally path. Preserve owner tabs and browser. The relay
closes on submission, rejection, cancellation, expiry or server exit; it cannot close the browser itself.
