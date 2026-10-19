# Research: Observable Research Mission

**Date**: 2026-10-04, R2 additions 2026-10-19 | **Status**: R1 decisions approved with the R1 plan; R2-1..R2-5 drafted with the R2 plan and awaiting its approval. Sections 3, 4 and 8 are superseded by R2-1 where they concern the built-in viewer. Not runtime verification.

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

## R2 decisions (2026-10-19)

Evidence for R2 came from repository search, installed package source in `.venv` and this session's Claude Code MCP log. No product code changed and no test ran for these decisions.

### R2-1. Retire the built-in viewer

**Decision**: Remove `open_mission_relay`, the loopback HTTP listener, the viewer template and builder, and the automatic dashboard start. Keep the snapshot tool and every storage, reader and projection layer behind it.

**Rationale**: Owner decision after a product review: Ignis's value is the collection and evidence mechanism; a UI is one way to visualize it, and agents can render that view for the user. The viewer had no eligible real-mission trace, and its remaining gates (FPS, browser security, visual acceptance) were the most expensive open work.

**Alternatives considered**: Keep the viewer as an optional extra (keeps the maintenance and security surface for a feature the owner no longer wants). Leave it unmaintained (a stale tool keeps advertising a surface that no longer meets its spec). Both rejected.

### R2-2. Deliver `ignis-track` as MCP prompt and resource from one packaged source

**Decision**: One markdown guide inside the package, served as prompt `ignis_track` and resource `fn-ignis://guide/ignis-track`, mirrored to `.agents/skills/ignis-track/SKILL.md` and kept equal by a test.

**Rationale**: The wheel ships `src/ignis` only; `.agents/skills` never reaches package or image users. The server already serves `market_research_pipeline` and `fn-ignis://sop/market-research` this way, so no new mechanism is needed. A packaged file rather than a Python string keeps prose out of code.

**Alternatives considered**: A SKILL.md alone (absent from installs). A new tool returning guidance (adds a tool signature for static text). Rejected.

### R2-3. Point-in-time artifacts, no polling, local by default

**Decision**: Regenerate only on user request or at milestones inside the agent's turn. Write a local file by default; publish only with explicit consent for that publication.

**Rationale**: Constitution I forbids background loops; an agent polling a snapshot is the same loop by another name. A published artifact sends mission data off the machine, which the user must decide.

**Alternatives considered**: Periodic agent refresh (background loop, cost, and drift from the mission boundary). Host default publishing (silent data egress). Rejected by owner decision.

### R2-4. Scope Constitution IV to Ignis research reports

**Decision**: Amend IV so its maintained-template rule governs Ignis research reports (mission reports, Gap Reports) and not host-side tracking artifacts, which follow the `ignis-track` display rules instead. Executed through `speckit-constitution` before implementation.

**Rationale**: IV exists so that a report Ignis issues has reproducible layout and cannot be rewritten ad hoc into a different claim. A tracking artifact is the host's presentation of a snapshot; its integrity comes from snapshot states and display rules, not from a template.

**Alternatives considered**: A time-limited exception (leaves a standing conflict). Forbidding HTML in artifacts (limits hosts without improving integrity). Rejected by owner decision.

### R2-5. Caller roots on MCP 2026-07-28+ connections

**Decision**: On a connection whose negotiated protocol is 2026-07-28 or later and whose client advertises roots, request roots by returning `InputRequiredResult` with a `ListRootsRequest`, and validate the returned `ListRootsResult` with the existing single-root rules. If the client re-calls without roots, use only a valid, unchanged, startup-configured `IGNIS_CALLER_ROOT`; otherwise refuse with a reason naming the protocol-forbidden case. Legacy connections keep `roots/list`.

**Evidence**:
- This session's Claude Code MCP log records `negotiatedProtocolVersion "2026-07-28"` and an immediate `ROOT_REQUIRED category=ROOTS_RPC_UNAVAILABLE roots_capability=ADVERTISED rpc_error=UNKNOWN` for `list_research_missions` and `list_research_workspaces`.
- `caller_storage.py` calls `ctx.session.list_roots()` and classifies every exception other than `NotImplementedError` as `UNKNOWN`.
- Installed `mcp` 2.2.0: `ServerSession.list_roots` is marked deprecated as of 2026-07-28 (SEP-2577) and raises `NoBackChannelError`; `connection.py` states that a modern duplex connection refuses `send_raw_request` "because the protocol forbids server-initiated requests".
- Installed `mcp_types`: `InputRequests` admits `ListRootsRequest`, and `InputResponses` admits `ListRootsResult`.
- Installed FastMCP 4.0.4: `Context.input_responses` and `Context.request_state` exist, and its own guidance names the guard pattern ("return an InputRequiredResult from the tool ... and read ctx.input_responses").

**Unknowns, verified before implementation**:
- Whether FastMCP 4.0.4 lets the `on_call_tool` middleware return `InputRequiredResult` for any mission-scoped tool, or only a tool function. A spike settles this; if only tools can, each mission-scoped handler needs a shared guard.
- Whether Claude Code answers a `ListRootsRequest` inside `InputRequiredResult`. A live probe settles this; a negative result leaves the configured-root fallback as the working path.

**Rationale**: The protocol now forbids the request Ignis depends on, so the 2026-10-11 rule "RPC failure refuses without fallback" no longer describes a failure. It describes a request that can never succeed. The owner narrowed that rule for this case only.

**Alternatives considered**: InputRequired only (Claude Code stays refused if it does not answer). Configured root only (ignores the client's real roots). Downgrading the negotiated protocol (not under Ignis's control and moves against the client). Rejected.
