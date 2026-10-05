# Research: Observable Research Mission

**Date**: 2026-10-04 | **Status**: Design decisions approved with the technical plan; not runtime verification.

Two read-only research branches inspected persistence and host integration in the managed worktree. They changed no files, ran no tests and accessed no sessions/databases. Findings below are code evidence, not executed acceptance.

## 1. Canonical evidence, operational records

**Decision**: Add workflow references alongside canonical evidence; do not duplicate observations, source identity or claim permission.

**Rationale**: `application/ports/research_workspace_port.py` defines `MissionEvidenceSnapshot`; `infrastructure/persistence/evidence_snapshot.py` reads mission, manifest, Brief, signals, qualifications, completed outcomes and claims on one pinned transaction. The actual repository method is `load_mission_evidence_snapshot` on both backends. SQLite opens its snapshot only after `_ensure_schema()`, so its existing method is not a no-bootstrap viewer boundary; PostgreSQL uses `REPEATABLE READ READ ONLY`. T013/T014 must provide the dedicated no-bootstrap readers. New workflow rows belong to this coherence boundary, not a JSON file bus.

**Alternatives considered**: Filesystem journals are filesystem-first/database-second and finalization can fail separately. Legacy cluster tables or browser-derived counts would create competing truth. Rejected both.

## 2. Durable events and ordered reads

**Decision**: Emit a result event in the transaction that commits its fact. Allocate a per-mission revision under the same serialized write boundary, with ordinal events within that transaction. Read current state and the committed event high-water together.

**Rationale**: `execute_mission.py` currently commits state, clusters, observations, attachments, pruning and outcomes separately. A generic post-call event could be missing after a successful data write or describe a failed write. A timestamp or independently allocated sequence can also miss commit-order races. Narrow transactional operations solve the fact/event invariant without pretending the whole pass is atomic.

**Alternatives considered**: Post-commit callbacks and filesystem replay cannot guarantee atomicity. Reusing frame digest for operational revision would make a heartbeat change evidence permission. Rejected.

## 3. Read-only is physical, not only semantic

**Decision**: Use a separate no-bootstrap read adapter and GET-only finite loopback capability. Do not reuse the writable Ignis Task Relay.

**Rationale**: SQLite `_ensure_schema()` runs table/seed writes and is called by ordinary read methods. Fresh repository construction must not be assumed read-only. Existing `connectors/host_browser/relay.py` provides security techniques but its POST answer staging and single-use closure do not match a live dashboard.

**Alternatives considered**: Reusing Task Relay would widen its write token and lifecycle; a public HTTP service introduces hosting/auth/multi-tenancy outside scope. A static export cannot satisfy live mission acceptance.

## 4. Minimal viewer runtime

**Decision**: Existing Jinja2 template, inline SVG/CSS/JavaScript, standard-library loopback HTTP and FastMCP-owned async lifecycle. Read requests bridge to the owner loop with bounded deadlines; no cross-loop pool use and no unattended database polling in the server.

**Rationale**: The stack already supports maintained templates, masking and local HTTP. FastMCP installed and locked 4.0.4 accepts a lifespan callable; inspected `fastmcp/server/server.py` confirms lifecycle ownership and nested lifespan reuse. The [official lifecycle documentation](https://github.com/prefecthq/fastmcp/blob/main/docs/servers/lifespan.mdx) was retrieved through Context7. Its indexed library includes older 3.x versions, so installed source—not indexed-version inference—is the compatibility evidence. No lifecycle or shutdown test has yet been executed.

**Alternatives considered**: Direct use of transitive Starlette/Uvicorn dependencies would create an undeclared direct dependency. A new frontend framework/server/model SDK adds no required capability here. Separate event loops with a shared pool risk invalid runtime ownership.

## 5. Host work, not a new agent platform

**Decision**: An explicit typed recording protocol for authorized host work, immutable handoffs and finding revisions. Host capability and provenance are declared; actual concurrency must be demonstrated in UAT. Ignis does not spawn agents from a work-record call.

**Rationale**: MCP composition has no specialist scheduler or agent registry. Connector `asyncio.gather` is parallel collection, not research team evidence. Existing qualification/claim tools accept semantic judgments from the host and gate them deterministically.

**Alternatives considered**: Fixed decorative agents fabricate topology. A provider-backed autonomous scheduler expands scope and cost. Sequential-only delivery fails SC-012 even if it is a valid fallback.

## 6. Research termination versus collection completion

**Decision**: Separate finite research authority/epoch from collection-run status. Work starts/results use version and epoch fences; activity receipts have a finite freshness boundary. Loss of activity evidence displays unknown/interrupted, not inferred completion or automatic lock reclamation.

**Rationale**: `WorkspaceRepository.mission_run` refuses completed/failed/blocked/cancelled/insufficient collection states. Qualification/claim work can follow completed collection. Persisted writer claims have no automatic expiry and cannot prove the owning process is alive. Findings cannot replace existing unique evidence qualifications.

**Alternatives considered**: Treating collection completion as full research completion strands legitimate analysis; indefinite pulses from writer rows fabricate liveness. Both rejected.

## 7. Follow-up without reopening or blending frames

**Decision**: `execute_mission_follow_up` admits and executes a child collection mission, bound to a recorded gap and live research authority. The child has its own immutable manifest, observations, outcomes and frame. Parent synthesis can show an explicitly labeled related result; strategic permission remains per exact mission/frame.

**Rationale**: Existing execute/prune behavior is a one-run path. Reopening COMPLETED would violate terminal guards; appending child observations to a parent display without canonical membership would manufacture support. Preserve original memberships and bind handoffs to immutable observation IDs, because pruning mutable membership can cascade qualifications/claim bindings.

**Alternatives considered**: An all-purpose append-batch collector would require broader executor/evidence-frame redesign. Every follow-up as a Brief revision would unnecessarily change the research question. A child relationship is sufficient; an actual question/Brief change uses the existing market-revision contract and new authority.

## 8. Rendering and stale permission

**Decision**: Motion represents once-only persisted events; pulses require fresh recorded activity. Current strategic permission is removed on failed/incompatible refresh, input change or incomplete active collection. Descriptive findings remain explicitly limited/history as appropriate.

**Rationale**: Current evidence-frame derivation relies on completed outcomes. The previous completed frame cannot masquerade as a new active pass. Popularity, shared observations and motion are not corroboration, demand or confidence.

**Alternatives considered**: Synthetic throughput, optimistic permission caching and provisional strategic verdicts bypass evidence controls. Rejected. Poll/packet limits will be bounded and measured during task design, not selected as evidence thresholds.

## Research closure and verification limits

All architecture unknowns needed for planning have a proposed resolution. Runtime feasibility and acceptance remain to be demonstrated: dual-backend transactions, lifespan shutdown races, truly read-only SQLite opening, host concurrency and child-frame UI boundaries. They are implementation verification gates, not claimed solved by documentation.

No dependency installed, product code changed, schema applied, live connector used, test suite run or benchmark performed in this planning phase.
