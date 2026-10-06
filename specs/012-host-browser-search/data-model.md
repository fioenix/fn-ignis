# Data Model: Host Browser Search

New typed models reject unknown fields and bound payload sizes. No database migration.

## HostSessionReference

Opaque task-local session reference, host kind, declared capabilities and collector/extractor versions.
No cookies, tokens, browser handle, debugging endpoint or profile path. Actual handle stays with host.

## SearchRequest

Protocol version, process epoch, random request ID, host task/session references, tactical/mission mode,
issued/expiry times and exact finite query list. Each query: ID, exact text, public search URL, surface
(`tiktok_video`) and record limit. Mission binding: workspace/mission, status/revision, manifest digest,
Brief revision, collection-plan digest and current frame digest when present. Full union includes
approved falsifiers. Tactical scope supplies finite bounds; mission derives them from authority.
Missing bounds refuse; no implicit quota/expiry renewal.

## SearchAnswer

Matching request/task/session/query IDs, actual page URL, start/capture times, extractor version,
search verification facts, outcome, public records, optional explicit window evidence and limitations.
Every issued query must have an answer; an unexecuted query is an explicit failure.

Parse HTTPS host/path/decoded query, not raw URL prefixes. Never navigate submitted arbitrary URLs.
Capture occurs after issue, within lifetime and not in the future. Wrong/stale page, login/challenge,
suggestions and unverified blank are not measured empty. Visible bounded grid is not platform-wide
coverage. Unknown publication, window and counter facts remain nullable.

## PublicRecord / Existing Observation

Canonical public video URL/ID, public creator handle if visible, exact excerpt, query associations,
capture time, nullable publication time and nullable explicitly typed counters. Allowlist fields and
cap lengths/counts. No HTML/private UI/credentials. Deduplicate within query, retain cross-query
associations. Normalize into existing signals and mission source/observation persistence. Numeric
storage defaults carry explicit unknownness and cannot become measured zero in qualification/reports.

## Ticket / Receipt

States: `PREPARED → SUBMITTING → ACCEPTED | FAILED`;
`PREPARED → CANCELLED | EXPIRED | REJECTED`. Terminal tickets accept no work.
Atomic claim prevents concurrent writes. Identical accepted replay returns cached receipt; altered
replay refuses. Cancellation during submission reports conflict, not a false rollback.

Collection expiry remains the original request deadline, enforced across awaited mission work.
Active SUBMITTING tickets cannot be evicted by preparation cleanup. Terminal receipts expire after
the original request duration measured from completion, without extending collection permission.

Receipt binds payload digest, outcomes and tactical observations or mission/run/frame references.
Uncertain persistence returns failed run identity for readback; no automatic retry. Restart loses
tickets and refuses old submissions; no durable resume or exactly-once crash guarantee.

## Authority

Manifest is canonical mission scope; ticket is a short-lived projection rechecked under writer before
collection/write. Session declaration grants no new account authority. Evidence remains in existing DB,
not the ticket registry. Host origin/cleanup claims require adapter tests, not merely valid JSON.
