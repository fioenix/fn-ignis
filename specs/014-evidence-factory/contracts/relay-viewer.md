# Relay Viewer Contract

**Status**: MCP/HTTP read operations and US3 permission rendering are implemented and locally verified. The T054 research read projection and T055 recorded research UI are locally accepted; the T056 native stdio/SQLite-file/local-PostgreSQL/HTTP/Chromium chain is independently accepted with12 native and11 convention cases passing without failure/error/skip. T057 actual native overlap/sequential execution and HTTP source-bearing readback are accepted for synthetic engineering UAT; T058 native revision/display and shipment remain unverified.

## MCP read operations

`open_mission_relay(mission_id, expires_at)` explicitly selects a mission and finite viewing deadline. Validate authorized mission access and installed schema without lazy bootstrap. Return a capability URL, mission ID, session expiry, read-only statement and supported inspection state. Unknown mission/access/schema/lifespan returns a typed refusal, not initialization, diagnostics or collector invocation.

`get_mission_relay_snapshot(mission_id, cursor?, page_size)` returns the same allowlisted projection used by HTTP, subject to host mission authorization. A positive bounded page size is required. No raw repository object serialization. This operation is independent of opening a browser.

## T001 — Initial resource limits to implement and measure

Recorded on 2026-10-04. These are design resource bounds, not implemented controls or measured performance. They never change evidence eligibility, qualification, confidence, claim permission or connector quota.

| Resource | Initial bound | Admission/rendering behavior and measurement |
|---|---|---|
| Viewing lifetime | Recommend an explicit deadline 15 minutes ahead; maximum 60 minutes from session creation | `expires_at` remains required, UTC-aware and in the future; reject a longer/invalid lifetime. No implicit renewal. Show the deadline and stop automatic reads/motion at expiry, without changing research authority. |
| Visible refresh | 2 seconds after the preceding request settles | One refresh request at a time; no catch-up burst or overlapping interval. Hidden/closed/expired/refresh-paused means zero new automatic reads; discard late delivery. Measure admitted reads under each boundary. |
| Page items | Recommended requested size 100; valid range 1–200 | `page_size` remains explicit; reject out-of-range values. Page events/inspectors under a coherent high-water and expose totals/continuations; a page is not complete evidence coverage. |
| Snapshot/inspection response | At most 1,048,576 UTF-8 bytes of serialized JSON | Page before serialization where possible. If necessary return a bounded typed size refusal requesting a smaller page; never silently truncate statements, references or state or label an omitted page empty. |
| Read concurrency | At most 4 reads across the process and 1 per viewing capability | Apply a bounded admission semaphore without an unbounded waiter queue; excess requests return a typed busy refusal. Inspection and refresh share the capability allowance. This is not a research-specialist or connector concurrency setting. |
| Read deadline | 3 seconds for an admitted coherent read | Timeouts yield unavailable/stale, never a fresh empty snapshot. Cancel the coroutine and retain its admission slot until the underlying read actually settles; do not evade the cap by admitting replacements for uncertain reads. |
| Moving packets | At most 120 simultaneous rendered packets | Aggregate bursts with exact disclosed event/observation counts and stable identity drilldown; overflow is not dropped evidence. Static accessible facts remain complete/paged. Reduced motion renders no continuous packets. |

Rationale: a finite local session limits exposure/idle compute; settled-request polling avoids overlap; bounded pages and responses avoid a full-corpus DOM; a small shared read cap protects the configured database; a packet cap permits later measured rendering optimization. The existing default PostgreSQL pool maximum is three connections, so four admitted reads may include one waiting for that pool within the same deadline, not four borrowed cross-loop connections.

These conservative starting limits require validation at T012–T015, T017–T018, T059–T067 and T083. SC-008/013 still measure <=5 seconds **after a successful coherent read**, not an end-to-end collection latency promise; SC-005 still requires the declared-machine 30-second >=50 FPS measurement. Any adjustment is recorded and decision-checked; no performance success is inferred from these values.

Decision check: `jev.py check` on 2026-10-04 returned a possible match (0.84) to the owner-authorized Supabase development operations statement in Spec 011. That statement does not oppose local resource bounds or a credential-free baseline; the development delegation remains unchanged. This is an agent-selected initial implementation policy under the approved plan, not a claim that Jev endorsed the design.

Snapshot fields:

- Schema version, mission/manifest/Brief identity, displayed collection run, committed revision/high-water and read receipt time.
- Collection state/channel outcomes; active incomplete collection explicitly prevents old completed-frame permission being shown as current progress.
- Current evidence frame or unavailable/pending reason; exact source/observation counts, evidence-role groups and safe paginated inspection references.
- Assignment/work lifecycle and provenance, activity basis/deadline, handoffs and finding revisions.
- Current permitted claims with frame/bindings, otherwise gaps/withheld reasons; stale/history distinct.
- Event page, next cursor and pagination/resync status. Bounded related-child summaries carry separate mission/frame identity; no implicit child access or merged claim permission.

Empty, degraded and unauthorized are different outcomes. A successful snapshot is internally coherent; a failed read is not an empty successful snapshot. The UI's last successful read is not overwritten by a failed attempt.

## T054 additive research read projection

The allowlisted `research` section is either `AVAILABLE` or exactly `{availability: SCHEMA_UNAVAILABLE}`. Missing, partial or incompatible optional research relations leave records/counts unknown while valid canonical/progress reads and existing Claim Ledger gating remain intact. Reads perform no initialization or migration. Compatibility checks recognize the committed table representations; installed-upgrade validation remains T084.

Available research is explicitly `MISSION_CURRENT`, with its own current run/frame identity and the same held connection, corpus and committed high-water as the canonical read. Selected-run history and its existing strategic permission gate remain separate. Masked assignment/work, handoff/ACK, finding history/currentness, unique observation/source bindings and observed metadata are projected; unknown capacity or submitted time is not inferred from observed storage metadata. Activity is finite `HOST_REPORTED` receipt evidence, not proof of live reasoning. A heartbeat does not mutate the evidence frame.

Strategic finding narration comes only from exact current permitted Claim Ledger content after the existing gate and exact bindings, with `narrative_origin: CURRENT_CLAIM_LEDGER`. A matching claim ID cannot license different candidate prose. Any handoff containing a strategic candidate withholds its free-form aggregate result, including when associated claims are permitted. Source-bound descriptive findings remain distinct; neither history nor currentness grants strategic permission. The existing bounded response refusal applies without a partial raw dump.

## Local HTTP surface

Separate ephemeral listener on exact `127.0.0.1`, no wildcard/public bind. Capability authenticates only the selected read scope. Routes expose maintained HTML, coherent snapshot and safe paginated inspection; only GET/HEAD as applicable. All mutation methods/routes are refused. Capability expiry/process shutdown revokes all reads; no browser action renews it automatically.

Require exact Host/port checks, reject cross-origin requests, no CORS wildcard, no token/request/payload logging, no-store and no-referrer. CSP permits only required maintained inline scripts/styles under nonce/hash policy and same-origin read fetches; no arbitrary script origins, eval, external telemetry or browser token exposure. Do not weaken Task Relay's existing CSP to achieve this. Use escaped templates and text-safe DOM writes; source URLs use validated schemes and safe navigation attributes.

HTTP threads bridge bounded read requests to the FastMCP-owned event loop. Read concurrency/response sizes are bounded; timeouts fail closed, not indefinite waits. The reader uses explicit initialized read-only schema and does not import/init collectors or credentials. Shutdown revokes capabilities, stops listeners and settles/cancels reads before closing loop-owned resources. Test stdio shutdown and pending-read races.

## Browser behavior

Initial state is a labeled snapshot, not a synthetic live factory. Poll only while visible, unexpired and refresh enabled; never overlap refresh requests. Handle visibility, page close, expiry and explicit refresh pause by stopping timers/animation and rejecting late responses. Resume requires a valid session and resync; do not replay every historic event as fresh arrivals.

Motion pause stops movement while valid refresh may continue. Refresh pause stops both automatic reads and motion. Reduced motion disables continuous packet flow/pulsing/spatial movement but preserves selectable stage content. Terminal collection stops intake only; independently authorized recorded analysis may still change. Terminal research admits no new work, while a valid historical viewer can still inspect.

Discard older cursors, incompatible identities and reordered pages. On failed refresh or changed/incomplete frame, immediately remove current strategic permission and label stale/pending; do not infer a fresh verdict from a cache. One persisted event animates once. Aggregate packets with exact disclosed totals/identity drilldown; particle speed/quantity are not measured rates.

## Visual encoding

Use existing FINOLABS product-mode partial and role/chart tokens; no ad hoc palette. Slim persistent mission/authority header plus Sources, Cleaning, Research, Cross-check, Synthesis columns. Header preserves mission authority as the sixth responsibility. Mint indicates ordinary flow; one violet gate indicates strategic permission. Labels/shapes accompany color.

Small geometric packets encode recorded evidence roles, not popularity. Specialist lanes follow actual work/dependencies; no fixed team replicas. An activity indicator links to its fresh receipt and provenance; stale/missing evidence produces an explicit unknown/interrupted state. Synthesis distinguishes limited descriptive findings, strategic candidates, current ledger-permitted claims and gaps. Inspector/timeline remain usable without motion, external fonts or horizontal page overflow.

Use semantic buttons, visible focus, text alternatives and stage navigation; no hover-only essential information. Updated findings use restrained accessible announcement, not focus stealing. Verify 390/768/1440 rendered layouts, keyboard/reduced motion and 30-second measured desktop performance.
