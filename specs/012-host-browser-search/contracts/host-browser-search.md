# MCP Contract: Host Browser Search v1

Additive operations only; existing signatures and defaults unchanged. Implemented locally under the
approved plan; integration/release remains separate. Typed entities: [data-model.md](../data-model.md).

## prepare_host_browser_search

Input: `host_task_ref`, `session_ref`, `queries`, `result_limit`, `lifetime_seconds`, `authorized`,
optional `mode` (default `TACTICAL`) and optional `mission_id` (default null).
Tactical supplies exact finite queries and no mission ID. Mission supplies its existing confirmed
mission ID, `queries=[]`, `result_limit=20` and `authorized=true`; the complete query union,
including falsifiers, derives from confirmed authority. The manifest must authorize `tiktok_video`
and browser-session access. There is no client-supplied host-surface or capability-list parameter;
supported host navigation/DOM evaluation remains a precondition, not new account authority.
Output: immutable request, per-query URLs/IDs, plan bindings, packaged extractor version/instructions.
Invalid authority, mode or scope returns `BLOCKED` with `INVALID_HOST_SEARCH_SCOPE`.
Preparation neither starts a run nor collects; host browser capability remains a host precondition.

## submit_host_browser_search

Input: request ID and matching task/session references. Complete typed per-query answers are staged
through the same-origin local relay form, not copied into MCP arguments.
Output: receipt with tactical observations/outcomes or mission run/current frame references.
Verified healthy/empty answers enter ingestion; degraded answers record explicit failure, never absence
proof. Structural invalidity or wrong/stale IDs/pages rejects whole submission before any write.
Mission includes an outcome for every approved surface.

Unavailable, invalid, expired or conflicting submission returns `BLOCKED` with
`HOST_SEARCH_NOT_ACCEPTABLE`. Mission ingestion failure returns `FAILED` with
`HOST_MISSION_INGESTION_FAILED` and available run references. Once claimed,
conflicts/failures terminate ticket; no implicit retry. Exact accepted replay returns cached receipt.
Uncertain persistence returns failed run identity and requires readback, not resubmission.
Cancellation drains in-flight persistence and terminal cleanup before releasing writer ownership;
cleanup may outlast the deadline without extending collection authority.

## cancel_host_browser_search

Input: request and matching task/session references. Output: terminal cancellation receipt or existing
terminal/in-progress conflict (`BLOCKED`, `HOST_SEARCH_CANNOT_CANCEL`). Does not remotely close Chrome. Host stops further navigation and
cleans up task-created resources only.

## Browser Boundary

Host uses authorized APIs, same session, exact finite query batch and packaged deterministic extractor.
Never export storage/tokens/private UI/raw HTML/screenshots. No fallback/account interaction.
Verified records: `HEALTHY`; verified search with explicit no-results evidence: `EMPTY_NO_DATA`;
incomplete/blocked/unverified: `DEGRADED` or precise existing auth/rate status. Aggregation preserves
partial failures. Unknown platform timeframe never attests mission window; unknown counters stay unknown.

## Trust / Availability

Opaque IDs prevent binding/replay mistakes, not forged-data authenticity. Authorized host is trusted
collector; not a generic file-import endpoint. Ownership/session properties require host tests.
Same live process required for tickets; restart refuses. Installed-wheel discovery/round-trip is a gate.
