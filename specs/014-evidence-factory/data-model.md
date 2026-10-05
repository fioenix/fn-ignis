# Data Model: Research Observability

**Status**: Additive schema/typed design approved with the technical plan; no SQL written or applied.

Canonical sources, immutable observations, mission evidence, manifest/Brief, probe outcomes, qualifications and Claim Ledger remain authoritative. New rows reference them. No raw content, transcript, credential or hidden model reasoning is copied into an event/result payload.

## Research assignment

Fields: assignment ID, mission ID, host task reference, research epoch, expected manifest/Brief digest, granted actions/sources, explicit deadline, collection quota ceiling, reserved/settled usage, host execution capability (`CONCURRENT`, `SEQUENTIAL`, `UNAVAILABLE`), recorded capability provenance, state, version and recorded timestamps/reason.

Authority is an explicit finite envelope that can tighten existing mission authority, never widen it. Free-form `analysis_policy` is not automatically a new grant. External host model spending remains the host's responsibility; Ignis does not invent measured token/cost totals. Assignment termination prevents new starts and follow-ups; a new assignment requires explicit authority.

States: `ASSIGNED` → `ACTIVE` → `COMPLETED | CANCELLED | FAILED | INSUFFICIENT_EVIDENCE | EXPIRED`. Cancellation request is separate from an acknowledged stop. Admission consults deadline/current epoch before starting; passage of time need not write a row to make authority expired. Pending receipts cannot resurrect a terminal assignment.

## Research work item

Fields: work ID, assignment/mission/run IDs where applicable, parent work/gap ID, question, expertise description, known assignee/host reference, input binding set, dependency/handoff IDs, authority epoch, state, version, ownership fence, idempotency key, start/wait/end reasons and recorded times.

Input binding set includes exact mission, manifest/Brief, frame when available, immutable observation IDs and exact predecessor finding revisions. Work with pending evidence has no fabricated complete frame. Shared IDs across work items count once as evidence, not independent corroboration.

Transitions: `ASSIGNED` → `RUNNING`; `RUNNING` ↔ `WAITING`; `RUNNING/WAITING` → `HANDOFF_READY` → `COMPLETED`. Failure, cancellation, expiry or explicit interruption terminate admissible work. Unknown activity is a projection state, not an invented persisted completion. Result admission checks expected version, ownership fence, authority epoch and input identity transactionally.

## Handoff

Fields: immutable handoff ID, producer work/version, intended consumer/dependency, input revisions, observation/outcome/claim references, concise public-safe result, limitations, open questions, occurrence time if known, recorded time, acceptance/rejection disposition and reason.

Completion/result/handoff/findings/events commit together. Invalid or late results cannot become current; an audit rejection receipt may record the reason without retaining unsafe rejected content. Evidence references target immutable observations, not cascade-deleted membership rows. A reference does not bypass current membership/qualification checks.

## Finding revision

Fields: stable finding ID, append-only revision, predecessor revision, producing work/handoff, input binding set, result type (`DESCRIPTIVE` or `STRATEGIC_CANDIDATE`), safe statement, limitations, open questions, supporting/contradicting/context references, alternative explanation, optional Claim Ledger ID and recorded update time.

No scalar confidence is invented. Exact bound input revisions determine currentness. New evidence/frame or revised dependencies invalidate downstream current status. Historical rows remain inspectable within authorized scope. A strategic candidate appears permitted only with current-frame PERMITTED ledger readback; naming it provisional changes nothing.

## Progress event and coherent cursor

Fields: event ID, mission ID, committed mission revision, ordinal, event kind, optional collection run/work/handoff/finding IDs, causation/idempotency key, occurrence time if supplied/known, recorded time, provenance (`HARNESS_OBSERVED` or `HOST_REPORTED`), typed safe references/reason.

Unique `(mission_id, revision, ordinal)`; unique command idempotency scope. Allocate revision on a control row within the mutating transaction; PostgreSQL row lock and SQLite serialized write transaction provide equivalent behavior. Do not use `MAX+1` outside the transaction, wall-clock order or a separately committed sequence.

Examples: collection started, observations committed, qualification recorded, claim gate changed, work started/waiting, handoff committed, finding revised, cancellation requested/acknowledged. A start event never counts as a stored observation or eligible frame.

A coherent snapshot reads canonical evidence, operational current state and high-water together. Paginated events never exceed that high-water. Older/out-of-order client snapshots are discarded. A missed/unknown cursor requests resync without inventing arrival animation. No automatic historical event backfill or destructive retention job is introduced.

## Child follow-up relationship and quota reservations

Fields: follow-up ID, gap/parent work/assignment IDs, parent mission, unique child mission ID, approved query/source scope, expected parent research epoch, child manifest digest, authority deadline, reservation ID, state, result reference and idempotency key.

Atomic admission persists child identity, authority and quota reservation before collection. One racing caller wins; retry returns the existing child/result, never creates another probe. Reservations conservatively cover unresolved work, preventing budget reset on child creation or crash. Settlement releases only demonstrably unused allowance. Missing usage or crash recovery cannot silently reclaim uncertain budget or mission writer ownership.

Child observations are canonically owned by child evidence membership. Child frame/claims are displayed under child identity. Parent findings can reference a labeled related result but cannot claim permission from a composite parent/child frame. Inspecting the child requires an explicitly scoped child viewer. New source/credential/Brief/budget demands owner authority, not inherited broad permission.

## Viewer session — transient, not research truth

Fields: cryptographically random capability, selected mission, creation/expiry boundary, permitted read scope and process lifecycle identity. Process-local storage only; restart revokes sessions. No token in logs, redirects, external requests or generated reports. No new persisted mission row is written to open a viewer.

Client state: last successful coherent cursor/read time, refresh and motion settings, visibility, expiry, selected inspection item. It never grants research authority. Hide/refresh-pause/expiry aborts in-flight delivery and prevents new automatic reads; one already admitted read may settle but cannot create mission writes or apply a late UI update.

## Backend and migration invariants

- Same typed/transactional behavior on SQLite and PostgreSQL; new PostgreSQL tables use existing owner-only/RLS conventions.
- Additive bootstrap/migrations occur only in explicit setup, never viewer reads. Old/missing schema returns unavailable with a setup action outside the viewer.
- Canonical source, observation, legacy timestamp, qualification and claim data remain unchanged by schema installation. Verify before/after counts/digests and FK/access invariants.
- Evidence transformations, dropping legacy data or changing existing qualification uniqueness are outside this plan and require a separate owner decision.
- Rollback disables new tools/viewer while retaining additive data; do not delete historical evidence or workflow receipts to make old code start.
