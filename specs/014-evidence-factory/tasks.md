# Tasks: Ignis Relay — Observable Research Mission

**Input**: R2 `spec.md` (2026-10-19), owner-approved R2 `plan.md`, `research.md`, `data-model.md`, `contracts/` (including `tracking.md` and `caller-root.md`), `quickstart.md` and constitution 2.1.0. R1 tasks and their acceptance history below are retained unchanged except where an R2 disposition is stated.

**Status**: R2 regeneration (2026-10-19): 83 accepted R1 tasks retained; T081, T083 and T090 retired or superseded (see Phase 8); T079, T082, T084, T087, T091 and T092 remain open; R2 adds T093–T113. Active ledger: 108/116 accepted (T093–T098 and T114–T116 on 2026-10-19; T117, T099–T111 and T118–T119 on 2026-10-20). R1 snapshot before R2: T001–T078, T080, T085, T086, T088 and T089 accepted: 83/92. US4 pure domain and atomic recording port contracts implemented and independently reviewed locally: 189 targeted tests passed. T041/T042 test-design acceptance does not establish storage behavior. T047 SQLite lifecycle verified with 339 scoped offline tests and independently reviewed. T048 PostgreSQL core lifecycle independently reviewed after one timing repair:118 scoped current-source PG tests passed, plus11 fresh convention tests; cleanup verified. T049 SQLite result settlement independently reviewed:416 scoped current-source offline tests passed; separate66 actualPG schema companion passed, cleanup verified. T050 PostgreSQL result parity independently reviewed:137 scopedPG,66schema,416offline and separate35 updated owner/result/convention cases passed without overlapping totals; final temporary DB/role cleanup verified. T051 typed recording service independently reviewed:396 scoped offline and32 actualPG tests passed, zero failure/error/skip; temporary DB/role cleanup verified. T052 persisted lifecycle independently reviewed:117 new/convention,385 disjoint regression and53 nativePG cases passed; zero failure/error/skip and temporary DB/roles. The final review correction strengthens the stale-activity assertion to exact REFUSED/STALE_REVISION with unchanged state and replay checks; its focused SQLite run passed2 cases, while1 PostgreSQL case was skipped without a loaded DSN. T053 record-only MCP independently reviewed through actual stdio/SQLite:37 boundary/convention cases passed;506 regression cases passed with2 localhost setup denials separately corrected2PASS, no fresh508-green claim. Canonical contract companion reviewed. T054 coherent research projection independently accepted after one schema compatibility repair: 777 scoped offline, 153 PostgreSQL, 66 schema and 34 MCP consumer cases passed, zero failure/error/skip; final temporary DB/role cleanup verified. Viewer contract companion reviewed. T055 recorded research UI independently accepted:78 browser and165 separate consumer cases passed with zero failure/error/skip; simulated GET scope disclosed. T056 native stdio MCP/HTTP/Chromium chain independently accepted:12 native and11 convention cases passed on SQLite file/local PostgreSQL; zero failure/error/skip and disposable DB/role cleanup verified. T057 actual native engineering overlap and separate sequential scenario independently accepted:four source-bearing results, exact stdio/HTTP readback and44 hashes verified. T058 actual native counterevidence revision/history independently accepted:39 hashes and exact source bindings verified; fresh-page actual HTTP response-to-DOM68.523ms single sample, prior version noncurrent, obsolete replay unchanged42tables. Retained-page wait timed out before result recording and is not passing display evidence. Synthetic engineering UAT only; controller closed, recoverable store retained. US4 engineering acceptance complete, review PR pending; no real-market validation or shipment. A broad unit attempt was network-aborted; no full-unit GREEN claimed. US3 T032–T040 accepted locally. Exact-frame permission, actual Gap/missingness and immediate stale removal verified through canonical stores, actual MCP/HTTP and isolated Chromium. Broad US1/US3 plus mission/Task Relay gate1390PASS3SKIP0FAIL0ERROR237.65s,149 frozen hashes; three known conditional skips disclosed. A final one-line receipt-directory setup amendment has separate3PASS0SKIP17.86s verification; all other148 hashes unchanged. Latest local read-to-display samples3.1msSQLite-file/1.3msmemory/2.7msPostgreSQL are not real-mission UAT or p95 proof. Final independent T040 review accepted; zero disposable PostgreSQL databases left. Evidence .handoff/spec014/us3.handoff.md and t040/{scoped.xml,final-readback.xml,final-source-settled.json,review.handoff.md}. T079, T081–T084, T087 and T090–T092 remain open. US5 remains incomplete pending T079. T074 bounded deterministic child execution is accepted after whole-candidate code/security review, scoped offline/PostgreSQL gates and independent PO verification; T075 conservative reconciliation is accepted with unknown spend retained and no measured SETTLED/release producer. T069 is runtime-verified through T077 in bounded synthetic engineering scope; real UAT remains unverified. T068 is now runtime-verified through T074:55 offline and29 PostgreSQL cases passed with exact physical and ingress assertions; its original missing-API receipts remain historical test-design evidence. Commit each accepted task; create a review PR after the current user story is fully accepted, per owner instruction on 2026-10-06. Real-mission UAT and shipment remain pending.

**Outcome**: A user follows a real mission through an agent-generated, point-in-time tracking artifact built from a bounded snapshot, with actual host work/handoffs, evolving findings and one authority-bound child follow-up; mission tools work from Claude Code. Synthetic concurrency, SQLite-only success and unverified host behavior do not close this feature. (R1 outcome, a built-in observatory, is superseded.)

## Execution rules

- Task IDs are stable; `[P]` means a possible different-file pairing **after its prerequisites**, not permission to spawn agents or skip earlier gates. Default execution is one task at a time.
- Tests are required by the approved spec. Write behavioral negatives first, observe the intended failure, implement the narrow change and rerun. A token/string/checkbox check is not proof of runtime behavior.
- Each task has a bounded deliverable and verification target. Execute its edit/test steps as 2–5 minute actions; split an oversized task into documented subtasks before coding instead of treating a backend subsystem as one unreviewed action.
- Temporary evidence belongs in `.handoff/spec014/`; ignored runtime exports belong in `reports/`. Record tested revision/commands and sanitized outcomes; never dump environment, session/token URLs, raw protected content or hidden reasoning.
- Schema files named below are planned additions, not existing scripts. Verify the next free migration numbers before writing them; a conflict requires a recorded path update, not overwriting another migration. Explicit setup performs schema writes; viewer opening/reading does not.
- Existing fn-ignis Supabase dev delegation is recorded in repository AGENTS.md; it is not authority over any other database or social session. Preserve recovery evidence before destructive operations. This design is additive and must not transform canonical evidence.
- Stop after two independent corrections leave the same invariant red; use the canonical architecture checkpoint before a third correction. Keep downstream acceptance tasks unchecked.

## Phase 1 — Setup and reproducible verification

**Goal**: Establish bounded, secret-safe verification without changing client configuration or product dependencies.

- [x] T001 Record the implementation limits to measure (finite viewer deadline, poll cadence, page/response/read concurrency bounds and packet aggregation cap) and their decision-check basis in `specs/014-evidence-factory/contracts/relay-viewer.md`; verify each is a resource bound, not an evidence/confidence threshold.
- [x] T002 Record actual branch/revision, existing schema slots, host concurrency capability and applicable DB/session authority in `.handoff/spec014/preflight.handoff.md`; verify the declared host can perform real research overlap or explicitly leave SC-012 blocked.
- [x] T003 Run existing convention/mission/relay regression baselines from `specs/014-evidence-factory/quickstart.md` with secret-safe output and record pass/fail/skip scope in `.handoff/spec014/baseline.handoff.md`; investigate failures without changing unrelated owner work.

## Phase 2 — Foundational transaction and read boundaries

**Goal**: Canonical facts and operational events share one commit; readers have a coherent, physically no-bootstrap boundary.

**Independent gate**: Transaction rollback yields neither fact nor event; concurrent commits yield a stable ordered high-water; viewer reads cannot create tables/seeds or invoke credentials/collectors. SQLite and PostgreSQL behavior must both be observed.

- [x] T004 Add failing rollback, commit-order and idempotency behavioral cases in `tests/integration/test_mission_progress_persistence.py`; verify the negatives fail for the missing transaction boundary rather than merely missing imports.
- [x] T005 [P] Add failing scope/masking/unknown-field projection cases in `tests/unit/test_mission_relay_projection.py`; assert protected values cannot appear in any serialized field and missing values remain unknown.
- [x] T006 Define typed progress event, mission cursor and safe snapshot/inspection models in `src/ignis/domain/mission_relay.py`; validate identity, provenance, finite bounds and unknown timestamps against T004/T005 cases.
- [x] T007 Define narrow atomic fact/event and read-only snapshot ports in `src/ignis/application/ports/mission_relay_port.py`; verify callers cannot request arbitrary SQL, raw repository serialization or collection through the read port.
- [x] T008 Add only mission revision/event/idempotency tables and owner-only access policy in `sql/027_mission_progress.sql`; verify schema constraints and before/after canonical evidence invariants in the isolated rehearsal used by T004.
- [x] T009 Mirror explicit SQLite schema setup in `src/ignis/infrastructure/persistence/sqlite_repository.py`; verify old evidence remains unchanged and read operations do not invoke this setup path.
- [x] T010 Implement SQLite transactional revision allocation and idempotent fact/event commit primitives in `src/ignis/infrastructure/persistence/sqlite_repository.py`; make SQLite rollback/order negatives from T004 pass.
- [x] T011 [P] Implement PostgreSQL row-locked revision allocation and equivalent atomic primitives in `src/ignis/infrastructure/persistence/postgres_repository.py`; make the same T004 behavior pass without committing a separate sequence.
- [x] T012 Add failing no-bootstrap, missing/old-schema, in-memory/file SQLite and PostgreSQL read-only cases in `tests/integration/test_mission_relay_read_boundary.py`; observe storage/write spies, not a method named read-only.
- [x] T013 Implement the dedicated SQLite file read-only and initialized in-memory snapshot reader in `src/ignis/infrastructure/persistence/mission_relay_reader.py`; make the SQLite T012 cases pass without calling lazy schema initialization.
- [x] T014 Add the pinned PostgreSQL read-only repeatable-read reader in `src/ignis/infrastructure/persistence/mission_relay_reader.py`; verify evidence, operational state and cursor belong to the same transaction and loop-owned resources are not shared across loops.
- [x] T015 Run foundation parity/race/read-boundary tests from T004/T012 and record actual backend outcomes in `.handoff/spec014/foundation.handoff.md`; skipped PostgreSQL coverage remains an unmet gate, not PASS.

## Phase 3 — US1: Follow the evidence journey (P1; first internal slice)

**Goal**: Open a finite viewer on a real selected mission, inspect all six responsibilities and see once-only committed evidence transitions.

**Independent test**: Opening and refreshing invokes zero mission/schema/collector/auth/model writes; real stored support/contradiction/context/exclusion remains inspectable through header plus five columns. Rollbacks produce no arrival, reconnect does not duplicate one.

### Test-first tasks

- [x] T016 [US1] Add failing collection/qualification/claim fact-plus-event cases through their actual use-case chains in `tests/integration/test_mission_progress_ingress.py`; separately negate each write/event atomicity claim.
- [x] T017 [P] [US1] Add failing GET-only, exact Host/Origin, capability expiry, body/response bounds and no-log-echo cases in `tests/unit/test_mission_relay_http.py`; keep existing writable Task Relay behavior as a regression anchor.
- [x] T018 [P] [US1] Add failing maintained-template, six-responsibility navigation and once-only event/reconnect cases in `tests/integration/test_mission_relay_browser.py`; distinguish fixture UI checks from real-mission UAT.

### Implementation tasks

- [x] T019 [US1] Implement narrow SQLite observation/membership, outcome/state, qualification and claim transaction operations with their matching progress events in `src/ignis/infrastructure/persistence/sqlite_repository.py`; verify rollback leaves both facts and events unchanged in T016.
- [x] T020 [P] [US1] Implement equivalent PostgreSQL fact/event operations in `src/ignis/infrastructure/persistence/postgres_repository.py`; run the same T016 invariants, retaining canonical source and observation IDs.
- [x] T021 [US1] Route collection state/outcome and durable evidence transitions through the atomic port in `src/ignis/application/use_cases/execute_mission.py` and `src/ignis/infrastructure/persistence/workspace_repository.py`; verify no globally atomic-pass claim or filesystem event fallback is introduced.
- [x] T022 [US1] Route qualification and ledger commits through the same fact/event boundary in `src/ignis/application/use_cases/submit_evidence_qualifications.py` and `src/ignis/application/use_cases/submit_mission_claims.py`; verify existing signatures and stale-frame refusals remain unchanged.
- [x] T023 [US1] Implement allowlisted coherent mission projection and bounded inspection/pagination in `src/ignis/application/use_cases/get_mission_relay_snapshot.py`; make T005/T012 pass with channel missingness and distinct ATTENTION/MARKET roles.
- [x] T024 [US1] Implement a separate finite loopback capability/listener service in `src/ignis/infrastructure/mission_relay.py`; make T017 pass without modifying the existing host-browser relay or exposing mutation routes.
- [x] T025 [US1] Bind viewer request reads and cleanup to the owning async lifecycle in `src/ignis/interfaces/mcp/server.py`; verify timeout, pending-read shutdown, capability revocation and zero startup DB/bootstrap work.
- [x] T026 [US1] Add only `open_mission_relay` and `get_mission_relay_snapshot` typed MCP handlers in `src/ignis/interfaces/mcp/server.py`; verify explicit selected scope/deadline and independent snapshot operation without browser opening.
- [x] T027 [US1] Add the maintained light-mode product template in `src/ignis/infrastructure/templates/html/mission_relay.html` and builder entry in `src/ignis/infrastructure/templates/html_builder.py`; verify FINOLABS partial/tokens, escaping and offline text fallback without new external resources.
- [x] T028 [US1] Render Sources/Cleaning/Research/Cross-check/Synthesis plus persistent mission authority header in `src/ignis/infrastructure/templates/html/mission_relay.html`; verify stage inputs, outputs, failure explanations, actual source availability and selectable evidence roles.
- [x] T029 [US1] Add visible-only finite refresh, coherent cursor rejection and once-only bounded packet animation in `src/ignis/infrastructure/templates/html/mission_relay.html`; make T018 pass with exact disclosed aggregate counts and no synthetic throughput.
- [x] T030 [US1] Add end-to-end MCP-to-HTTP-to-browser zero-write and evidence inspector tests in `tests/integration/test_mission_relay_mcp.py`; verify missing schema/access fail closed before component bootstrap or credential initialization.
- [x] T031 [US1] Run US1 tests plus original Task Relay/mission regressions and record the internal slice evidence in `.handoff/spec014/us1.handoff.md`; mark unsupported research activity unavailable and do not call this full feature acceptance.

## Phase 4 — US3: Recognize the data and conclusion boundary (P1)

**Goal**: A convincing visual cannot manufacture current permission, certainty or measured absence.

**Independent test**: Incomplete/changed/failed refresh immediately withholds strategic permission; unknown publication/reach stays unknown; insufficient evidence displays a gap without category winner or confidence.

- [x] T032 [US3] Add failing partial-run, frame-change, mismatched mission/run and unknown-metric cases in `tests/unit/test_mission_relay_claim_gate.py`; independently negate each permission/missingness assertion.
- [x] T033 [P] [US3] Add failing failed-read, reordered-response and immediate stale-claim removal browser cases in `tests/integration/test_mission_relay_browser.py`; measure from the read/failure boundary rather than connector start.
- [x] T034 [US3] Add explicit current/pending/stale/history gate projection in `src/ignis/application/use_cases/get_mission_relay_snapshot.py`; make T032 pass without treating old completed outcomes as current active-pass success.
- [x] T035 [US3] Add mission/run/frame, last successful read and unavailable reasons to the persistent header in `src/ignis/infrastructure/templates/html/mission_relay.html`; verify successful and failed reads have distinct receipts.
- [x] T036 [US3] Render only exact-frame PERMITTED strategic entries or the actual Gap Report in `src/ignis/infrastructure/templates/html/mission_relay.html`; verify descriptive/provisional labeling never grants permission.
- [x] T037 [US3] Make client failed/incompatible refresh remove current strategic permission immediately in `src/ignis/infrastructure/templates/html/mission_relay.html`; make T033 pass while preserving labeled history and the last successful read time.
- [x] T038 [US3] Add cross-mission inspector and empty/degraded/unknown channel negatives in `tests/integration/test_mission_relay_mcp.py`; verify no synthetic fallback, foreign record access or missingness-as-zero.
- [x] T039 [US3] Run gate negatives on SQLite and PostgreSQL through `tests/integration/test_mission_relay_read_boundary.py`; verify consistent frame/role interpretation and exact canonical observation identities.
- [x] T040 [US3] Record permission/missingness readback and measured successful-read-to-display latency in `.handoff/spec014/us3.handoff.md`; leave real-mission latency acceptance pending until final UAT.

## Phase 5 — US4: Follow real specialist work and evolving findings (P1)

**Goal**: Actual bounded host work yields inspectable handoffs and source-bound finding revisions, without installing a scheduler or model provider.

**Independent test**: Two real host work items overlap and hand off shared observations without duplicate corroboration; sequential mode stays sequential; counterevidence revises a finding; obsolete results never become current.

- [x] T041 [US4] Add failing assignment/work state, finite authority, epoch/fence, idempotency and provenance cases in `tests/unit/test_research_work.py`; verify free-form policy/writer ownership is not new authority or liveness.
- [x] T042 [P] [US4] Add failing atomic handoff/finding, dependency revision, shared identity and obsolete result cases in `tests/integration/test_research_work_persistence.py`; include consumer rejection and no unsafe rejected payload retention.
- [x] T043 [US4] Define typed assignment/work/activity/command models in `src/ignis/domain/research_work.py`; make T041 model validation pass with unknown assignees and honest host capability.
- [x] T044 [US4] Define immutable handoff/finding revisions and binding validation in `src/ignis/domain/research_findings.py`; verify support, contradiction, alternatives, limits and explicit descriptive/strategic types in T042.
- [x] T045 [US4] Define atomic work admission/result/lifecycle ports in `src/ignis/application/ports/research_work_port.py`; verify recording cannot dispatch agents, models or connectors.
- [x] T046 [US4] Add owner-only assignment/work/handoff/finding schema and immutable observation references in `sql/028_research_work.sql`; verify pruning mission membership cannot cascade-delete historical handoffs/findings.
- [x] T047 [US4] Add explicit SQLite research schema and work transition CAS in `src/ignis/infrastructure/persistence/sqlite_repository.py`; make assignment/version/fence/idempotency T041/T042 persistence cases pass.
- [x] T048 [P] [US4] Add PostgreSQL equivalent assignment/work transition CAS in `src/ignis/infrastructure/persistence/postgres_repository.py`; prove racing starts/results have one admitted version.
- [x] T049 [US4] Commit handoff, finding revisions, completion and progress events atomically in `src/ignis/infrastructure/persistence/sqlite_repository.py`; make SQLite rollback/dependency/history T042 cases pass.
- [x] T050 [P] [US4] Commit equivalent PostgreSQL handoff/finding/event transactions in `src/ignis/infrastructure/persistence/postgres_repository.py`; verify exact inputs and immutable observation references, not a second evidence corpus.
- [x] T051 [US4] Implement typed command dispatch/admission in `src/ignis/application/use_cases/record_mission_research_work.py`; make T041/T042 pass with public-safe result/reason allowlists and no semantic provider invocation.
- [x] T052 [US4] Implement cancellation-request/acknowledged-stop, terminal epoch fences and deadline admission in `src/ignis/application/use_cases/record_mission_research_work.py`; verify valid analysis after collection completion versus zero new work after research termination.
- [x] T053 [US4] Add `record_mission_research_work` MCP handler in `src/ignis/interfaces/mcp/server.py`; verify unknown fields, foreign mission/observations and widened authority are refused with safe typed responses.
- [x] T054 [US4] Extend coherent readers/projection with work, handoffs, findings and bounded activity basis in `src/ignis/infrastructure/persistence/mission_relay_reader.py` and `src/ignis/application/use_cases/get_mission_relay_snapshot.py`; verify dependency changes invalidate current findings without changing evidence-frame digest for a heartbeat.
- [x] T055 [US4] Render actual lanes/handoffs, finite activity basis and finding history in `src/ignis/infrastructure/templates/html/mission_relay.html`; verify no fixed replicas, endless pulses, duplicated shared evidence or provisional strategic bypass.
- [x] T056 [US4] Add MCP lifecycle/masking/race tests in `tests/integration/test_research_work_mcp.py`; exercise actual command-to-database-to-viewer chain, old receipts and terminated/expired authority on both backends.
- [x] T057 [US4] Run an explicitly assigned real two-specialist overlap on a declared capable host and a separate sequential scenario; record sanitized questions/receipts/overlap/output/readback in `.handoff/spec014/research-host-uat.handoff.md` without hidden reasoning or pretending timestamps prove execution.
- [x] T058 [US4] Verify counterevidence revision/history and <=5-second post-read display in the real host scenario, recording results in `.handoff/spec014/us4.handoff.md`; mark SC-012/013 unmet if actual host execution or freshness proof is unavailable.

## Phase 6 — US2: Inspect without being forced to watch (P2)

**Goal**: Users can inspect, pause and resume independently of mission execution, including keyboard and reduced-motion use.

**Independent test**: Motion-only pause preserves authorized refresh; refresh pause/hidden/closed/expiry admits zero new automatic reads or motion; keyboard and reduced-motion preserve all essential information.

- [x] T059 [US2] Add failing motion/refresh separation, hide/close/expiry and late-response cases in `tests/integration/test_mission_relay_browser.py`; count actual fetches/animation frames rather than inspect labels.
- [x] T060 [P] [US2] Add keyboard/focus, reduced-motion and unavailable-external-resource cases in `tests/integration/test_mission_relay_accessibility.py`; verify essential inspection works without hover or continuous motion.
- [x] T061 [US2] Add independent motion and refresh controls to `src/ignis/infrastructure/templates/html/mission_relay.html`; make T059 pass without cancel/restart/collect controls.
- [x] T062 [US2] Add visibility/expiry/page-close cleanup, aborted-read generation fencing and explicit resume/resync in `src/ignis/infrastructure/templates/html/mission_relay.html`; verify admitted reads may settle but cannot update paused/expired UI.
- [x] T063 [US2] Add semantic stage/evidence navigation, visible focus and restrained accessible update announcements in `src/ignis/infrastructure/templates/html/mission_relay.html`; make keyboard T060 cases pass without focus stealing.
- [x] T064 [US2] Apply reduced-motion/no-animation and font-unavailable fallback in `src/ignis/infrastructure/templates/html/mission_relay.html`; make remaining T060 cases pass with complete readable facts and zero continuous loops.
- [x] T065 [US2] Adjust responsive stage/inspector layout in `src/ignis/infrastructure/templates/html/mission_relay.html`; verify 390/768/1440 widths retain controls and essential text without page overflow.
- [X] T066 [US2] Capture and inspect actual rendered screenshots plus keyboard/reduced-motion walkthrough in `.handoff/spec014/visual-uat.handoff.md`; compare light hierarchy/space/motion with the approved mock, never its illustrative metrics.
- [X] T067 [US2] Run boundary counters during pause/hide/expiry on the integrated viewer and record `.handoff/spec014/us2.handoff.md`; verify underlying research neither stops nor starts because of viewer controls.

## Phase 7 — US5: Close a research gap without exceeding authority (P2)

**Goal**: One assigned gap leads to one bounded child mission and a traceable revised finding; new/exhausted authority refuses work before probes.

**Independent test**: Trace gap → assignment → child evidence → cross-check → finding/claim-or-gap; parent stays terminal, child frame stays distinct, duplicate admission performs no extra probe, expired/new scope performs zero work.

- [x] T068 [US5] Add failing scope/source/session/Brief/epoch/deadline/quota and duplicate-admission cases in `tests/integration/test_mission_follow_up.py`; assert actual connector-call counts and conservative unresolved reservations.
- [x] T069 [P] [US5] Add failing child-frame isolation and related-result inspection cases in `tests/integration/test_mission_follow_up_viewer.py`; negate parent permission, foreign child access and implicit composite-frame assertions separately.
- [x] T070 [US5] Define typed follow-up relationship/reservation/result models in `src/ignis/domain/mission_follow_up.py` and port methods in `src/ignis/application/ports/research_work_port.py`; verify no unrestricted execution-time query/credential payload.
- [x] T071 [US5] Add additive parent/child and reservation schema in `sql/029_mission_follow_up.sql`; verify uniqueness, existing child mission ownership and canonical evidence counts remain unchanged by installation.
- [x] T072 [US5] Implement SQLite atomic child admission and cumulative reservation in `src/ignis/infrastructure/persistence/sqlite_repository.py`; make SQLite racing/idempotency/exhaustion T068 cases pass.
- [x] T073 [P] [US5] Implement equivalent PostgreSQL child admission/reservation in `src/ignis/infrastructure/persistence/postgres_repository.py`; prove one child admission across competing transactions.
- [x] T074 [US5] Implement gap-linked tightened authority admission and deterministic child execution in `src/ignis/application/use_cases/execute_mission_follow_up.py`; make T068 pass while retaining parent terminal guards and existing connector authorization.
- [x] T075 [US5] Add conservative settlement/failure/cancellation/crash reconciliation in `src/ignis/application/use_cases/execute_mission_follow_up.py`; verify uncertain child/writer/quota state cannot silently rerun collection or release allowance.
- [X] T076 [US5] Add only `execute_mission_follow_up` MCP handler in `src/ignis/interfaces/mcp/server.py`; verify expected epoch/idempotency and refusal before any collector/client authentication initialization.
- [x] T077 [US5] Project explicitly scoped child result and related finding revisions in `src/ignis/application/use_cases/get_mission_relay_snapshot.py`; make T069 pass without implicit parent-child evidence membership or combined permission.
- [x] T078 [US5] Render the recorded gap-return path and labeled child result in `src/ignis/infrastructure/templates/html/mission_relay.html`; verify child inspection needs its own selected scope and viewer contains no follow-up execution button.
- [ ] T079 [US5] Run a currently authorized real bounded follow-up using existing child qualification/claim tools and record `.handoff/spec014/follow-up-uat.handoff.md`; prove revised synthesis, parent terminal state and exact child frame with observed outcomes, not synthetic replay. **R2 disposition**: evidence is the tracking artifact and snapshot readback, not the retired viewer; may run together with T112.
- [x] T080 [US5] Run all follow-up/terminal authority negatives on both backends and record `.handoff/spec014/us5.handoff.md`; assert zero unauthorized probes and leave skipped or incomplete lifecycle acceptance unchecked.

## Phase 8 — Cross-cutting review, UAT and integration

**Goal**: Close the full approved scope with evidence, then integrate only under owner authority; do not select a release/version.

- ~~T081 [P] Add and run end-to-end cross-mission/child access, Host/Origin/CSP/XSS, expiry, bounds, log/DOM/JSON masking and shutdown race cases in `tests/integration/test_mission_relay_security.py`; record both negative controls and any unverified threat surface.~~ **R2 (2026-10-19): superseded by T111.** Host/Origin/CSP/DOM and viewer-expiry cases retire with the viewer; partial cases already in the file stay as history until T108 removes the viewer ones.
- [ ] T082 Complete lifecycle race/interrupt acceptance in `tests/integration/test_research_work_mcp.py` and `tests/integration/test_mission_follow_up.py`; verify collection completion does not end valid analysis and research end never admits new work.
- ~~T083 Measure a 30-second integrated desktop sample on the declared reference machine and actual workload in `.handoff/spec014/performance.handoff.md`; verify >=50 FPS and <=5-second post-coherent-read display, plus zero idle/hidden reads and disclosed packet aggregation.~~ **R2 (2026-10-19): retired** with SC-005's FPS goal. Partial T083 evidence under `.handoff/spec014/t083/` is history, not acceptance.
- [ ] T084 Verify all additive schema rehearsals, SQLite/PostgreSQL parity, access policy and unchanged canonical counts/digests in `.handoff/spec014/schema.handoff.md`; record actual environments/revisions and rollback retention, not a production migration claim.
- [x] T085 Update executable new-tool/test/UAT guidance in `specs/014-evidence-factory/quickstart.md` and permanent `docs/USER_GUIDE.md`; verify documented commands and tool semantics against installed implementation rather than task promises.
- [x] T086 Synchronize additive tool catalogs with actual registered schemas in `README.md`, `README.vi.md`, `server.json`, `openclaw.json` and `AGENTS.md`; verify the catalog is old signatures plus exactly four intended additions, without changing version strings or client configs.
- [ ] T087 Run convention, full unit, applicable integration, minimum-supported-Python and distribution asset checks; record exact commands/revision/results/skips in `.handoff/spec014/regressions.handoff.md` and verify the maintained viewer template is packaged. **R2 disposition**: run against the R2 tree; verify the packaged `ignis_track` guide and the absence of the viewer template (T106) instead of the viewer template.
- [x] T088 Apply `speckit-converge` to implementation versus `specs/014-evidence-factory/spec.md`, `plan.md` and `tasks.md`; append genuine remaining tasks without ticking unavailable UAT or treating successful local checks as shipping.
- [x] T089 Perform actual diff/code review and security review, record findings and tested revision in `.handoff/spec014/review.handoff.md`; fix and rerun validated in-scope findings, or explicitly park accepted/deferred blockers with owner ruling.
- ~~T090 Assemble requirement-by-requirement acceptance, real host/follow-up receipts and rendered evidence in `.handoff/spec014/acceptance.handoff.md`; verify all 29 FR/17 SC and disclose unmet gates before requesting integration authority.~~ **R2 (2026-10-19): superseded by T113** (32 FR / 18 SC).
- [ ] T091 After explicit owner integration authorization, create/attach a focused PR with observed verification, risks and remaining work using `.github/PULL_REQUEST_TEMPLATE.md` when present; record actual URL/status in `BACKLOG.md`, never assume plan approval authorizes push/merge.
- [ ] T092 After explicit owner merge authorization and successful required checks, integrate and verify post-merge canonical state in `BACKLOG.md` and `specs/014-evidence-factory/tasks.md`; record deployed/activated versus parked status, leaving release/tag/version untouched without separate approval.

## Phase 9 — R2 setup and seam spike

**Goal**: Fix the R2 starting facts and prove the caller-root seam before product code changes.

- [x] T093 Record R2 preflight in `.handoff/spec014/r2-preflight.handoff.md`: revision, installed FastMCP/`mcp` versions, negotiated protocol per available host (Claude Code, Codex), whether `IGNIS_CALLER_ROOT` is set (by name only, never its value beyond the root path) and whether the owner has parked the uncommitted Relay canvas work on its own branch.
- [x] T094 Spike in a disposable script under `.handoff/spec014/r2-spike/` with an in-process FastMCP 4.0.4 server and a client negotiating 2026-07-28: prove whether `on_call_tool` middleware can return `InputRequiredResult` with a `ListRootsRequest` and read `ctx.input_responses` and `ctx.request_state` on the retry; record the chosen seam (middleware or a shared tool guard) and evidence in `.handoff/spec014/r2-spike.handoff.md`. No product source edits.

## Phase 10 — R2 foundational: caller root on MCP 2026-07-28+ (FR-032, SC-018)

**Goal**: Every mission-scoped tool, including the snapshot, works from Claude Code. Blocks R2 user-story acceptance on that host.

**Independent test**: From an in-process client at 2026-07-28 and at a legacy version, every row of [contracts/caller-root.md](contracts/caller-root.md) resolves or refuses exactly as specified.

- [x] T095 [P] Write behavioral tests first in `tests/unit/test_caller_root_modern_protocol.py` for each resolution row in `specs/014-evidence-factory/data-model.md` "Caller-root resolution": on a modern connection a valid configured root resolves without any roots request, and an invalid or changed one refuses without asking; without a configured root the first round asks and the retry is validated; invalid or foreign `request_state`; the legacy configured-versus-returned mismatch; and `ROOT_REQUIRED category=ROOTS_REQUEST_FORBIDDEN`. Observe the intended RED.
- [x] T096 Implement modern-era resolution in `src/ignis/infrastructure/caller_storage.py` through the T094 middleware seam, gated on `ctx.session.protocol_version`: a configured `IGNIS_CALLER_ROOT` is used directly with identity pinning; otherwise the first round returns `InputRequiredToolResult` with `ignis_caller_roots` and the retry validates `ListRootsResult` with the legacy rules; a retry without roots refuses with `ROOTS_REQUEST_FORBIDDEN`. Keep the legacy path and refusal format. Verify T095 plus `tests/unit/test_caller_storage_native.py`, `tests/unit/test_configured_caller_root.py`, `tests/unit/test_caller_root_diagnostics.py` and `tests/integration/test_follow_up_caller_middleware.py`.
- [x] T097 Add `tests/integration/test_caller_root_modern_mcp.py`: real in-process MCP client calls `get_mission_relay_snapshot` and `list_research_missions` at both protocol eras on SQLite file, and PostgreSQL when `IGNIS_TEST_POSTGRES_DSN` is set; skips are reported, not counted as parity.
- [x] T098 Run the live Claude Code probe and record `.handoff/spec014/r2-claude-code-probe.handoff.md`: negotiated version; with `IGNIS_CALLER_ROOT` set, that it resolves without a roots request; without it, whether Claude Code answers the `ListRootsRequest` or fails the call itself, and the resulting path. No credentials and no paths beyond the root.
- [X] T114 [P] Write behavioral tests first in `tests/unit/test_caller_root_startup_folder.py` for `specs/014-evidence-factory/contracts/caller-root.md` (revised): override wins; startup folder resolves with any client roots or none and on both protocol eras; filesystem root and home refuse `STARTUP_ROOT_REFUSED`; replaced or symlinked startup folder refuses; no roots request is ever sent. Observe the intended RED.
- [X] T115 Replace the client-roots and protocol-era logic in `src/ignis/infrastructure/caller_storage.py` with the startup-folder rule and optional override, removing the T096 roots-request code; keep the refusal format, `host_workspace` and `proposed_path` checks.
- [X] T116 Add a default test binding in `tests/conftest.py` so no test resolves to the checkout's `.fnignis/`, and update the root-dependent suites (`tests/unit/test_configured_caller_root.py`, `test_caller_root_diagnostics.py`, `test_caller_storage_native.py`, `test_dashboard_native.py`, `test_caller_root_modern_protocol.py`; `tests/integration/test_caller_root_modern_mcp.py`, `test_mission_relay_mcp.py`, `test_research_recording_mcp_boundary.py`, `test_follow_up_mcp.py`, `test_follow_up_caller_middleware.py`, `test_research_work_mcp.py`) to bind roots through it; retire tests of the superseded client-roots rules.
  - Acceptance T114–T116 (2026-10-19): RED 21 fail / 2 pass before T115. After T115 plus the independent-review fixes (home and its parents matched by file identity against `HOME` and the password-database home; world-writable, sticky and foreign-owned startup folders refuse; `host_workspace` matched by file identity and rewritten to the pinned root), the caller-root suites pass 109 with 13 PostgreSQL skips. Full suite: 4240 passed, 978 skipped, 4 failed; the failures are pre-existing (two viewer browser cases from the parked canvas template; `test_settings_do_not_leak_secrets` and `test_tool_manifests_drift` from `2974edf`). The checkout guard recorded no hit and the checkout's `.fnignis/` was unchanged by size and mtime. `test_caller_root_modern_protocol.py` is retired with the client-roots rule; `test_caller_config_layout.py` now starts its stdio server in the caller folder. PostgreSQL parity not run (no DSN loaded).
- [X] T117 Re-run the live Claude Code check in `.handoff/spec014/r2-claude-code-probe.handoff.md` without `IGNIS_CALLER_ROOT`, in a session with an extra working directory (SC-018). First remove the `IGNIS_CALLER_ROOT` entry the T098 probe left in the workspace `.mcp.json`, and fully quit and reopen the app so the new server process serves the conversation.
  - Acceptance T117 (2026-10-20): SC-018 met. A fresh Claude Code desktop session opened in the checkout, with two extra working directories, ran `46ff90d`: the serving server (parent = that session's process) had cwd = the checkout and no `IGNIS_CALLER_ROOT`, negotiated 2026-07-28, and `list_research_missions`, `list_research_workspaces` and `get_mission_relay_snapshot` all succeeded in one round each with zero `ROOT_REQUIRED`. Only `canonical.sqlite3` changed (mtime, same size), inferred to be the first-use schema check of a new server process. Evidence: `.handoff/spec014/r2-claude-code-probe.handoff.md`, section T117.

## Phase 11 — R2 US1 and US2: `ignis-track` guidance (FR-005, FR-007, FR-008, FR-014, FR-016, FR-024, FR-026, FR-030, FR-031)

**Goal**: Any MCP host can fetch one maintained guide that tells its agent how to read the snapshot and render an honest, point-in-time tracking artifact.

**Independent test**: From an installed wheel, list and read the `ignis_track` prompt and `fn-ignis://guide/ignis-track` resource; their content equals `.agents/skills/ignis-track/SKILL.md` and covers the six sections of [contracts/tracking.md](contracts/tracking.md).

- [X] T099 [P] [US1] Write `tests/unit/test_mission_relay_tracking_states.py` asserting the snapshot exposes the source of every display state in `specs/014-evidence-factory/data-model.md` "Tracking artifact" (`claim_gate.state`, `reason_code`, `gap_report`, `frame_pending_reason`, channel `status`, `read_at`, frame digest). A missing source is recorded as a spec gap through clarification before any field is added, never inferred.
  - Acceptance T099 (2026-10-20): `tests/unit/test_mission_relay_tracking_states.py`, 9 passed against the canonical claim-gate fixture. Every data-model display state has a snapshot source: permitted (`claim_gate.state` CURRENT, claims PERMITTED on the exact `frame_digest`), withheld (PENDING or UNAVAILABLE with `reason_code` and a non-null `gap_report`), stale (STALE with non-permitted `history`), missing (`frame_pending_reason`, channel `status` null with null count), point-in-time (`read_at` with zone, `revision`, counts). Research work and finding states are covered by `tests/integration/test_mission_relay_research_projection.py`. No spec gap found; no field added.
- [X] T100 [P] [US1] Write tests first in `tests/unit/test_ignis_track_guidance.py`: prompt `ignis_track` and resource `fn-ignis://guide/ignis-track` are listed and return the packaged guide (the prompt fills an optional `mission_id`); serving starts no read, collection or write; the SKILL.md body equals the packaged source; observe RED.
- [X] T101 [US1] Write `src/ignis/interfaces/mcp/guides/ignis_track.md` in English covering read, generation triggers, required content, display rules, failed-read and frame-change handling, and the local-default publication rule from `specs/014-evidence-factory/contracts/tracking.md`.
- [X] T102 [US1] Register the `ignis_track` prompt and `fn-ignis://guide/ignis-track` resource in `src/ignis/interfaces/mcp/server.py`, reading the packaged guide by package-relative path beside the existing `market_research_pipeline` prompt; no new tool.
- [X] T103 [US2] Create `.agents/skills/ignis-track/SKILL.md` with frontmatter matching `.agents/skills/ignis-collect/SKILL.md` and the guide body; verify T099 and T100 green.
  - Acceptance T100–T103 (2026-10-20, commit `4eff906`): RED 4/4 before the guide existed (one vacuous pass removed). Guide, prompt `ignis_track`, resource `fn-ignis://guide/ignis-track` and the byte-identical SKILL.md mirror pass 5 tests; with T099, `test_public_mcp_contract`, `test_repo_conventions` and `test_mission_relay_mcp`: 49 passed, 7 PostgreSQL skips. An independent review found no blocking issue; its Important findings were fixed before commit: evidence pages must share one `revision`; evidence rows, raw popularity versus demand, qualification relations and contrary evidence; `text_withheld`, `latest_recorded` versus `current_eligible` and provenance labels. Its test findings were fixed too: no vacuous storage guard, required-rule check, injected text not echoed, and an `openclaw.json` drift test. Wheel inclusion of the guide is not yet proven (T106).

## Phase 12 — R2 retirement of the built-in viewer (FR-006, FR-013)

**Goal**: Remove the viewer and every consumer while the snapshot, research-work and follow-up surfaces stay green.

**Independent test**: The public catalog has 47 tools without `open_mission_relay`; the wheel ships the guide and no viewer template; no runtime reference to the viewer remains.

- [X] T104 Confirm from `.handoff/spec014/r2-preflight.handoff.md` (T093) that the owner parked the uncommitted Relay canvas work; stop this phase if not.
  - Acceptance T104 (2026-10-20): the owner parked the canvas work on `park/relay-canvas` (`252c3c2`, not merged or pushed); recorded in `.handoff/spec014/r2-preflight.handoff.md`.
- [X] T105 [P] Write removal tests first: `tests/unit/test_public_mcp_contract.py` and `tests/unit/test_tool_manifests_drift.py` expect 47 tools without `open_mission_relay`; observe RED.
- [X] T106 [P] Add a distribution assertion in `tests/unit/test_public_distribution_contract.py` that the wheel contains `ignis/interfaces/mcp/guides/ignis_track.md` and no `mission_relay.html`; observe RED.
- [X] T107 Remove the `open_mission_relay` tool and handler, listener creation, `started_dashboard` and the `run_started` dashboard hook from `src/ignis/interfaces/mcp/server.py`, keeping `_MissionRelayRuntime.read_service` and `caller_scopes`; verify `tests/integration/test_mission_relay_mcp.py`, `tests/integration/test_research_work_mcp.py` and `tests/integration/test_follow_up_mcp.py` stay green.
- [X] T108 Delete `src/ignis/infrastructure/mission_relay.py`, `src/ignis/infrastructure/templates/html/mission_relay.html` and `build_mission_relay_artifact` in `src/ignis/infrastructure/templates/html_builder.py`; delete `tests/unit/test_mission_relay_http.py`, `tests/unit/test_mission_relay_template.py`, `tests/integration/test_mission_relay_browser.py`, `test_mission_relay_visual.py`, `test_mission_relay_accessibility.py`, `test_mission_relay_responsive.py`, `test_mission_relay_research_browser.py`, `test_mission_follow_up_browser.py` and `test_mission_follow_up_viewer.py`; remove viewer cases from `tests/integration/test_mission_relay_lifecycle.py` and `tests/integration/test_mission_relay_security.py`, keeping snapshot, scope and masking cases. **Found in T097**: `MissionRelayReadService`, which `get_mission_relay_snapshot` uses through `_MissionRelayRuntime.read_service()`, lives in `src/ignis/infrastructure/mission_relay.py`; move it to a non-viewer module before deleting the listener, and keep the snapshot MCP suites green.
- [X] T109 Update the remaining 48-tool consumers to 47: `openclaw.json`, `.hermes/tools.json`, `hermes_manifest.json`, `scripts/wheel_mcp_smoke.py`, `src/ignis/interfaces/cli/setup_bundle.py`, `tests/unit/test_public_doc_conventions.py`, `tests/unit/test_mission_relay_mcp_tools.py`, `tests/unit/test_caller_relay_read_composition.py`, `tests/integration/test_mission_relay_us3_readback.py`, `tests/integration/test_clean_user_journey.py`, `AGENTS.md` and `CLAUDE.md`; verify T105 and T106 green and that `open_mission_relay|MissionRelayHTTP|build_mission_relay_artifact|mission_relay.html` appears nowhere outside `specs/` and `.handoff/`.
- [X] T110 Update `README.md`, `README.vi.md`, `docs/USER_GUIDE.md`, `docs/USER_GUIDE.vi.md` and `docs/caller-storage.md` (which still describe the client-roots rule): retire the viewer, document `ignis-track`, that the caller root is the folder the agent was opened in, and the optional `IGNIS_CALLER_ROOT` override; the Vietnamese documents pass `vietnamizer` review.
  - Acceptance T105–T110 (2026-10-20, commit `1158c68`): RED before removal: 16 contract, manifest and smoke cases failed on the tool count, `open_mission_relay` and the guide. After removal, the catalog has 47 tools. The Hermes manifests were regenerated by `scripts/sync_tool_manifests.py`, which also resynced the pre-existing `propose_research_workspace` description drift. `open_mission_relay|MissionRelayHTTP|build_mission_relay_artifact|mission_relay.html` now appears only in negative test assertions outside `specs/` and `.handoff/`. Deviations from the task text, each for parity: (1) `infrastructure/mission_relay.py` was reduced to the snapshot read service rather than moved and deleted; (2) `tests/integration/test_mission_follow_up_viewer.py` is kept, because it is a use-case-level parent/child isolation test with no viewer code; (3) tests mixing viewer and snapshot behaviour were rewritten to read the snapshot through MCP instead of being deleted: lifecycle, security, relay MCP, research work, US3 readback, follow-up middleware, MCP tools, cold composition, and the native running mission (renamed `test_native_running_snapshot.py`); (4) `test_mission_relay_claim_rendering.py`, a viewer DOM test missing from the list, was deleted; (5) a direct read-service `RESPONSE_TOO_LARGE` test was added; (6) the wheel check is the smoke reading `fn-ignis://guide/ignis-track` from the installed package plus a source/hatch assertion, since no wheel is built in the unit suite. Full suite before the last fixes: 3970 passed, 978 skipped, 12 failed. The failures were `test_settings_do_not_leak_secrets` (pre-existing since `2974edf`) and 11 governed tool-count literals; after fixing those, the affected files passed 172 and 45. The checkout guard recorded no hit, and the checkout `.fnignis/` was unchanged. The Vietnamese documents passed the vietnamizer core workflow; Jev was not run because sending the text to TypeSafe was not authorized in this session. An independent review found no blocking or important issue. Its minor findings are fixed, except dead code left outside the plan's scope: the `run_started` dashboard hook and `DASHBOARD_START_FAILED` in `execute_mission.py` and `follow_up_caller_activation.py`, the unreachable expiry and per-scope task branches in the read service, the viewer-only `RelayReadReason` values, and `GetMissionRelaySnapshotUseCase.inspect`. The owner's uncommitted PENDING-refresh paragraph in `docs/USER_GUIDE.md` now describes the retired viewer.

## Phase 13 — R2 cross-cutting acceptance

**Goal**: Close R2 with real evidence; integration stays owner-gated in T091 and T092.

- [X] T111 [P] Extend `tests/integration/test_mission_relay_security.py` for snapshot and artifact surfaces: cross-mission and child scope, masking, page and response bounds, and log/JSON exposure; verify the packaged guide states the publication-consent rule (FR-031). Replaces T081.
  - Acceptance T111 (2026-10-20): `tests/integration/test_mission_relay_security.py` now covers the snapshot surface through a real in-process MCP client: parent/child and cross-mission scope (foreign run, unknown and malformed mission refuse with `SCOPE_MISMATCH`; a cursor past the high-water mark refuses with `INVALID_REQUEST`; no foreign identity in the read); masking of research text, observation text, structured private metadata and outward text across current and withdrawn permission; page bounds (`INVALID_PAGE_SIZE` at 0 and 201, a negative offset refused, the end of the corpus an empty `OK` page with unchanged totals, past the end a typed failure); the response bound (refused whole with `RESPONSE_TOO_LARGE`, no row text in the refusal, logs or output); and the text channel equal to the structured result in every read. The guide's publication-consent rule (FR-031) is asserted through the served resource and prompt. 12 passed and 4 PostgreSQL cases skipped (no DSN loaded); the related relay suites passed 86 with 16 skipped. These are acceptance tests over existing behaviour, so no RED phase applies. Observation for the owner: an `evidence_offset` past the end returns `UNAVAILABLE/READ_UNAVAILABLE` rather than a caller-error refusal. It is typed and never empty, but an agent may read it as a storage failure; unchanged here.
  - Follow-up decision (owner, 2026-10-20): an `evidence_offset` past the end now refuses with `REFUSED`/`INVALID_REQUEST`. The coherent read keeps an empty past-the-end page representable, and the projection refuses it; a non-empty page that overruns still fails the port invariant. RED was observed in the projection unit test, the port test and both SQLite MCP cases. Full suite: 3990 passed, 981 skipped, 1 failed (the pre-existing `test_settings_do_not_leak_secrets`); the checkout `.fnignis/` was unchanged. PostgreSQL was not run.
- [ ] T112 Run a real mission tracked from Claude Code under current authority and record `.handoff/spec014/r2-tracking-uat.handoff.md`: at least two milestone artifacts, each read back against its snapshot; zero snapshot reads between milestones and after the agent's turn; a withheld or stale claim never rendered as permitted (SC-001, SC-004, SC-005, SC-007, SC-008, SC-010, SC-015).
- [ ] T113 Assemble R2 requirement-by-requirement acceptance for FR-001–FR-032 and SC-001–SC-018 in `.handoff/spec014/acceptance.handoff.md`, citing T079, T082, T084, T087, T098 and T111–T112 evidence and disclosing unmet gates before requesting integration authority. Replaces T090.

## Phase 14 — R2 replay form of the tracking artifact (FR-033)

**Goal**: An agent can render the tracking artifact as a replay of one read without inventing figures, activity or liveness.

**Independent test**: The served `ignis_track` guide has a `## Replay` section with the FR-033 rules, and the SKILL.md mirror still equals it.

- [X] T118 [P] Extend `tests/unit/test_ignis_track_guidance.py` first: the guide has a `Replay` section and states the FR-033 rules (one step per event ending on the read step, figures that name their source and hold still between steps, disclosed event-order pacing with elapsed time, decorative ambient motion, reduced motion opening on the final step); observe RED.
- [X] T119 Add the `## Replay` section to `src/ignis/interfaces/mcp/guides/ignis_track.md` and the same body to `.agents/skills/ignis-track/SKILL.md` per `specs/014-evidence-factory/contracts/tracking.md` item 7; verify T118 green with `test_repo_conventions`, `test_public_doc_conventions` and `test_public_distribution_contract`.
  - Acceptance T118–T119 (2026-10-20): RED 2 failed / 4 passed on the missing `Replay` section. An independent review confirmed every field the section names exists in the payload and found one blocking issue, now fixed: an `OBSERVATIONS_COMMITTED` event with `reason` `MEMBERSHIP_PRUNED` references removed observations (`sqlite_repository.py` and `postgres_repository.py`), so a running count of references would exceed `counts.observations`. Its Important findings were fixed too: claim statuses before the read step are recorded history and current permission comes only from `claim_gate.claims`; the field list includes `run_id`, `work_id`, `handoff_id` and `finding_id`; a value no event establishes appears only at the read step; the pacing disclosure applies unless spacing is proportional to `recorded_at`; the test normalises whitespace and anchors 25 rules. A bad-behaviour control removing the prune rule or the elapsed-time rule from the guide fails the test. Final: guide, conventions, public docs, distribution and MCP contract suites 188 passed. The fixes were not re-reviewed; the full suite and the wheel smoke were not run. A local prototype rendered from mission `29cb1c03` revision 6 is in the ignored `reports/mission-replay/`.

## Dependencies and execution order

```text
Setup T001–T003
  → Foundation T004–T015
    → US1 T016–T031
      → US3 T032–T040
        → US4 T041–T058
          → US2 T059–T067
            → US5 T068–T080
              → Cross-cutting T081–T090
                → Owner integration gates T091–T092
```

R2 order (2026-10-19):

```text
R2 setup T093–T094
  → Caller root T095–T098 (unblocks Claude Code)
    → ignis-track T099–T103
      → Viewer retirement T104–T110
        → Acceptance T111–T113 with open R1 gates T079, T082, T084, T087
          → Owner integration gates T091–T092
```

This is an ordered task outline, not a separately maintained architecture diagram. Story numbers retain the approved spec identity; P1 stories precede P2 stories. The default one-at-a-time sequence avoids shared repository/server/template conflicts.

### Explicit prerequisites

- Within a phase, use sequential order unless a pairing below is declared. Tests written first may remain red until their linked implementation, but their failure must be the intended missing behavior.
- T010/T011 share completed T006–T009 and a stable T007 port; T015 requires both backend implementations and T012–T014.
- T019/T020 require T016 and foundation; T021/T022 require both adapters. T023 requires their coherent records; T024/T025/T026 then bind the read surface before template/browser completion.
- US3 depends on US1 projection/viewer but is independently tested without actual specialists. US4 uses US1/US3 safe projection and gate; its domain/persistence tests require no live sessions.
- US2 depends on the integrated viewer. It may be built after US3 while US4 progresses only with explicit separate-file ownership; both touch the template, so do not edit it concurrently.
- US5 requires US4 assignment/epoch/handoff semantics and US1/US3 child read/gate behavior. Its automated admission negatives can be written early; real follow-up waits for current source/host authority.
- T057/T058, T079 and final UAT require real explicitly assigned work; mocks prove deterministic mechanisms only. Unknown host capacity, unavailable session or skipped database coverage leaves those acceptance gates unmet.
- T081–T090 follow all story implementations; tests may expose upstream defects. T091/T092 require their explicit owner authority even if all local evidence is green.
- R2: T096 waits for the T094 seam decision; T098 needs T096 and an owner-run Claude Code session. T104–T110 wait for the guide (T101–T103) so documentation points at its replacement, and for the parked canvas work. T112 needs T096 and T102 plus current mission authority.

## Optional parallel opportunities

No delegation is performed by this task-generation turn. Each example requires an explicit execution decision and preserves everyone else's edits.

| Area | Different-file pairing after prerequisites | Serial owner/integration boundary |
|---|---|---|
| Foundation | T004 persistence tests with T005 projection tests; T010 SQLite with T011 PostgreSQL after shared port/schema | T013/T014 share reader; run sequentially. |
| US1 | T016 ingress tests, T017 HTTP tests and T018 browser tests; T019 SQLite with T020 PostgreSQL | T021/T022 and server/template integration serial. |
| US3 | T032 gate tests with T033 browser tests | All projection/template edits serial. |
| US4 | T041 domain tests with T042 persistence tests; T047/T048 and T049/T050 backend pairs | Command service, MCP and viewer projection/render integration serial. |
| US2 | T059 lifecycle browser tests with T060 accessibility tests | Template edits T061–T065 serial. |
| US5 | T068 admission tests with T069 viewer tests; T072 SQLite with T073 PostgreSQL | Authority/admission and child-frame integration serial. |
| R2 | T095 with T099–T100; T105 with T106; T111 with T112 preparation | `server.py` edits (T102, T107) and `caller_storage.py` (T096) serial. |

## Requirement and acceptance mapping

| Requirements | Principal tasks | Acceptance criteria |
|---|---|---|
| FR-001–004, FR-011, FR-018, FR-026 | T018, T023, T027–T029, T035–T036, T055, T065–T066 | SC-001, SC-003, SC-006, SC-015 |
| FR-005–006, FR-009, FR-012–013, FR-015 | T012–T015, T025–T026, T030, T032–T040, T086 | SC-004, SC-008–009 |
| FR-007–008, FR-016 | T059–T067, T083 | SC-002–003, SC-005–007, SC-009 |
| FR-010, FR-014, FR-024–025 | T004, T010–T011, T016, T019–T023, T029, T032–T039, T054–T058 | SC-008, SC-010–011, SC-013 |
| FR-019–022, FR-027 | T041–T058 | SC-011–013 |
| FR-023, FR-029 | T052, T056, T068–T080, T082 | SC-014, SC-017 |
| FR-017, FR-028 | T005, T012–T015, T017, T024, T030, T038, T051, T056, T069, T081 | SC-016 |
| Full-scope verification and shipping | T081–T092 | SC-001–017; integration is additional to local acceptance |

R2 mapping (2026-10-19); rows above remain R1 history.

| R2 requirements | Principal tasks | Acceptance criteria |
|---|---|---|
| FR-032 caller root on 2026-07-28+ | T093–T098 | SC-018 |
| FR-005, FR-007–008, FR-011, FR-014, FR-016, FR-024, FR-026, FR-030–031 | T099–T103, T111 | SC-002–005, SC-010, SC-015–016 |
| FR-006, FR-013 viewer retirement | T104–T110 | SC-003, SC-009 |
| FR-001–004, FR-009–010, FR-018–025, FR-027–029 (kept from R1) | Accepted R1 tasks plus T079, T082, T084, T087, T112 | SC-001, SC-004, SC-006–008, SC-011–014, SC-017 |
| Full R2 verification and shipping | T087, T111–T113, T091–T092 | SC-001–018 |

Mapping coverage is not a test result. Mark a task complete only after reading its fresh verification evidence; an implementation checkbox cannot substitute for an unmet linked acceptance gate.

## Implementation strategy and stop points

1. **First internal slice**: T001–T040 delivers real persisted evidence viewing with truthful permission/missingness. It is not release-ready by itself; motion/accessibility, actual research and follow-up still remain.
2. **Research team slice**: T041–T067 delivers source-bound work/findings with actual concurrent/sequential host evidence and usable motion controls. Host-reported and harness-observed facts remain visibly distinct.
3. **Bounded return loop**: T068–T080 delivers a gap-linked child mission without resurrecting parent collection or blending frames.
4. **Full feature**: T081–T090 closes review/UAT with fresh evidence. T091–T092 close integration under owner authority. Release is outside this task list.
5. **R2 (2026-10-19)**: MVP is T093–T098: Claude Code can call every mission tool, which is useful on its own. Then `ignis-track` (T099–T103), viewer retirement (T104–T110) and R2 acceptance (T111–T113). T081, T083 and T090 are retired or superseded.

Setup goal stopped at T003, followed by completed T004 RED execution. The subsequent owner goal now assigns all remaining tasks with independent task-by-task review; review existing T004 before progressing. RED tests remain intentionally failing pending their linked foundation implementation. Keep this ledger and canonical backlog synchronized with actual verified work; external/live/integration gates remain explicit.

## Task-generation verification — 2026-10-04

Observed structural validation: 92 sequential unique task IDs, all unchecked; story counts US1 16, US3 9, US4 18, US2 9, US5 13; shared setup/foundation/cross-cutting 27. Thirteen `[P]` candidates identify optional different-file work, not scheduled delegation. Every task includes a target path; all referenced task IDs exist. Requirement mapping covers FR-001–029 and SC-001–017. Extension hooks are absent, so pre/post tasks hooks were skipped.

`git diff --check` passed for tracked changes; explicit whitespace/placeholder checks also cover the new task file. Repository convention gate ran with a cleared environment and no traceback/captured-output exposure: `env -i PATH=/usr/bin:/bin:/usr/sbin:/sbin .venv/bin/python -m pytest tests/unit/test_repo_conventions.py -q --tb=no --show-capture=no -p no:cacheprovider` — 11 passed. This is a static repository convention result, not Spec 014 implementation, full regression, real mission, UAT or release evidence. No implementation task is ticked by these document checks.

## Setup execution evidence — 2026-10-04

- T001: `contracts/relay-viewer.md` records finite expiry, poll/page/response/read bounds and disclosed packet aggregation, with decision basis. These are selected limits, not runtime enforcement or achieved performance.
- T002: `.handoff/spec014/preflight.handoff.md` records actual worktree/HEAD, free schema slots, authority, credential isolation and unverified host overlap. SC-012 remains unmet pending actual host UAT; advertised tools are not proof.
- T003: `.handoff/spec014/baseline.handoff.md` records corrected isolated runner results: conventions 11 passed; unit regressions 132 passed; integration 74 passed and 58 skipped, all due to missing PostgreSQL test DSN. Every group exited 0. The initial collection/configuration failures and runner-only correction remain recorded separately.
- Exactly 3 of 92 tasks are complete. PostgreSQL parity, live research, feature acceptance and integration are not claimed. No product source, test, schema or dependency edit occurred; documentation is local and unmerged. Extension hooks are absent.

## T004 execution evidence — 2026-10-04

Owner approved the proposed next step after setup completion. `test_mission_progress_persistence.py` exercises real repositories and independent durable reads, without future module imports, synthetic schema or transaction substitutes. Initial results were 5 intended RED failures, 2 passing controls and 7 PostgreSQL skips for missing DSN. Independent review found missing different-command transaction contention coverage; fix round 1 adds real SQLITE_BUSY, reversed invocation/commit order, independent visibility and failure/cancellation cleanup. Scoped re-review approved the RED deliverable with no new Important/Critical finding. SQLite-only results after that fix: 6 intended failures, 2 controls passed and 8 missing-DSN skips.

A subsequent actual run on SQLite and the dedicated local PostgreSQL test server observed 10 failed, 3 passed and 3 skipped, exit 1. PostgreSQL now exercises durable receipt, commit order, replay, racing replay and conflicting-payload preservation. The three remaining PostgreSQL skips need equivalent fault injection and contended lock/commit scheduling; they are not caused by missing DSN. Missing runtime remains RED and T015 parity is still open. Retained reports/logs are in `.handoff/spec014/`; task reviews do not establish feature GREEN.

An initial mistaken test read-method call was corrected to a direct durable query; it is not an accepted RED reason. Existing convention gate passes 11/11. Full-suite results and environment-related limitations are recorded in ignored `.handoff/spec014/t004.handoff.md`; there is no full GREEN, runtime acceptance or merge claim. T004's deliverable is verified failing tests, not implementation.

## T005 execution and independent review — 2026-10-04

Observed final collection: 59 cases. Execution: 58 individually named missing-API failures and one existing real sanitizer control passed; conventions 11 passed. No projection behavior has executed, so these tests do not establish masking/refusal/missingness acceptance. Independent review accepted the bounded RED deliverable with no Important/Critical finding. Minor M1 requires a multibyte oversized fixture before T023 byte-bound acceptance; Minor M2 requires exact typed output-key allowlists in T006/T023. Future work/handoff/finding/HTTP/DOM/log surfaces retain their own gates. Initial invalid enum fixture was corrected and is not accepted RED evidence. At T005 handback, five of 92 tasks were complete; subsequent T006 evidence follows below. Work is local and unmerged.

## T006 execution and independent review — 2026-10-04

Immutable typed progress/cursor/evidence/snapshot/inspection contracts preserve initial `(0,0)`, unknown run/timestamps/measurements and explicit outward-key allowlists. Independent review found an impossible source-count invariant; three focused negatives failed before correction, then all ten count regressions passed. Scoped re-review accepted the correction with spec PASS and quality approval with deferred Minor M1. Final model/domain/convention gate: 248 passed, including 86 model cases. Final full selection: 68 failed, 2060 passed, 419 skipped, 2 warnings, retaining six T004 storage failures, 58 T005 missing-projection failures and four isolated-environment conflicts; no feature GREEN is claimed. Source hash is `5f2c3766bc29c2dfe4f323cbe2ab1a5fc52b24c16090421466730fff734a141f`; model tests hash is `4608480a7ad0d680028f892eee9151f540934f6b48e99d5c72562c04ea7e185f`.

T005 Minor M2 is addressed for T006's exact model keys, not future surfaces or actual masking. T006 Minor M1 (huge finite integers raising OverflowError during numeric validation) remains assigned to T023/T081 robustness and final review; no silent coercion is allowed. Canonical count accuracy, membership authorization, atomic revisions, coherent/no-bootstrap reads, projection sanitization, minimum-supported-Python runtime and actual browser/UAT remain their later gates. At T006 handback, six of 92 tasks were complete; subsequent accepted T007 execution follows. Local work is uncommitted/unmerged, not shipped.

### T007 execution evidence — 2026-10-04

Narrow typed commit/read ports retain the existing producer signature, derive authoritative mission/run/surface-batch command scope, compare every immutable fact field and distinguish coherent internal input from safe outward projection. Independent review found mutable Enum/timezone aliases could change admitted facts after fingerprinting. Four regression negatives failed, then recursive Enum-value and known UTC-instant snapshots fixed both nested values and completed_at. Scoped re-review restored spec PASS and quality APPROVE, with no open T007 Important/Critical finding.

Final covering gate: 313 passed, including 65 port cases and 86 accepted model cases. Full selection on the same settled source: 68 failed, 2125 passed, 419 skipped, two warnings; failed node IDs are unchanged. Port SHA256 is `33a53585985b45391f7c5f5c4fd8d1e863b62b6e458f038fc9ead1e8edb2299c`; tests `21b6326427767ef943c8734890af1d740dc1515529fd93cbf4914eadcabd5258`. Concrete transactional replay, recursive admitted-value JSON encoding, coherent/no-bootstrap reads, membership, sanitization and actual backend/browser gates remain downstream. Seven of 92 tasks are complete; T008–T092 remain unchecked. Nothing is integrated or shipped.

### T008 acceptance — 2026-10-04

Additive PostgreSQL schema independently accepted after fix round1: spec compliant, task quality Approved. Actual local PostgreSQL selection passed all43 schema/access cases; sixteen populated canonical table counts/digests match before install, after install and after reapplication. Ordinary non-superuser owner writes/default UUID generation work; effective client/PUBLIC access and TRUNCATE refusal are observed, not inferred from RLS flags. No canonical rewrite or fabricated historical events.

Original local-DSN full selection:77failed2533passed45skipped2warnings359.27s, retained unchanged. Its five new guide/packaging consumer failures were fixed surgically; amended covering180passed1skip26.27s. Final exact-source no-DSN selection:68failed2125passed462skipped2warnings63.57s, with no new failed node. Four PostgreSQL T004 failures and all43 new schema cases are skipped in that last selection, not fixed or revalidated there. Independent scoped re-review accepted both I1/I2; original schema files remain hash-identical. Migration SHA256 `d3d460e090f03b8ca2fc6a0498b8ca1a8397816a7f6f43b4ed54525ca9192dbd`; fixdiff `8044b87e4646dda7df177e4ca8dc23c36154d0fea52efa25b8604fc23ca6788f`. Saved task report/review/re-review remain ignored `.handoff/spec014/` evidence.

T008 Minor M1 inherited warnings remain T087/final-review work. T009–T015/T023 retain SQLite schema/runtime parity, actual atomic replay/revision ordering, physically no-bootstrap coherent reads, canonical reference admission and public sanitization. Hosted Supabase, wheel/Compose/browser/UAT and integration are not established. Eight of92 tasks complete; T009–T092 remain unchecked. Local changes are uncommitted/unmerged, not shipped.

### T009 acceptance — 2026-10-04

Explicit additive SQLite setup independently accepted after fix round1: spec PASS, task quality Approved. Real file and initialized-memory constraints, per-connection FK enforcement, defaults, insert/update/delete behavior, prerequisite refusal and no-progress-bootstrap legacy read controls pass. Sixteen populated canonical table counts/digests remain identical after setup and reapplication; NULL unknown time/metric values remain unknown. Existing legacy snapshot still invokes canonical lazy setup and is unsuitable for the dedicated viewer.

Independent review found embedded NUL suffixes bypassed SQLite UUID/digest/key checks. All56 new INSERT/UPDATE regressions failed before correction, then passed with four built-in constraint guards. Original145 cases remain unchanged; final covering400passed55skipped13.16s includes all201 schema cases. Sole amended frozen no-DSN full selection:68failed2326passed462skipped2warnings80.81s, identical failed/skipped node identities to the original T009 run. These failures/skips are not accepted runtime or backend coverage. Scoped re-review closed I1 without new breakage. SQLite source SHA256 `cef6c765da06e5354e2f4983f743e9cd6b086225e0bbf9308c1c1ec3396da0d7`; tests `103dec03a6457ae375a99c4c80224fb8773cb1aa72d015751fc8f4081be9bffb`; fixdiff `4efeaafa145dd5812715d98f5ea24a5e7ef2470504e982d31e0579d37a855c85`.

Inherited warnings retain T087/final review. Obsolete experimental progress-table constraints are not repaired by CREATE-time setup: T012–T014 retain explicit missing/old-schema refusal, and T084/integration retains schema rehearsal. T010/T011/T015 retain actual atomic facts/events/receipts, revision ordering, replay and backend parity; T023 retains canonical membership/outward sanitization. Minimum-runtime, browser/UAT and shipping gates remain open. Nine of92 tasks complete; T010–T092 remain unchecked. Work is local, uncommitted/unmerged and unshipped.

### T010 acceptance — 2026-10-04

SQLite atomic probe publication accepted after independent review and fix round1 scoped re-review.
Actual immutable facts, mission revision, typed event and original receipt commit together;
unchanged T004 SQLite rollback/order/retry cases pass. Reordered replay retains the original receipt
after a later revision; conflicts, manifest completeness and legacy empty compatibility are covered.
Review reproduced a public journal writer ending an unsettled shared-memory publication; common
mutation ownership through settlement and lifecycle close fixed the consumer-chain bypass. Eight
valid RED controls became GREEN, with two original replay controls also passing. Accepted progress
DDL and all previously reviewed test bodies remain structurally unchanged.

Final covering:506passed79skipped9.29s. Sole amended full:62failed2373passed463skipped2warnings90.14s;
failed node identities remain unchanged, not all-suite GREEN. Source SHA256
`bc66d7a5d9538d945813b1508b9ffff4e0ab17b2ea0586eeadcfffcd54a7287b`; writer tests
`956e722172e1ce6639a1c6112ffdb5cfc81f8931eef2740341bcebbc20171443`; scoped re-review
`781b3d844eb66ecd36d21bf35fa9c4f7bad28cd9ff5d6fb2a4ad2e0baa87ee0d` closes I1 with no new breakage.
Every PostgreSQL/read-boundary/projection/old-schema/minimum-runtime/browser/UAT/integration gate
remains assigned to its later owner. Inherited warnings and instruction drift remain T087/final.
Ten of92 tasks complete; T011–T092 remain unchecked. Local work remains uncommitted/unmerged/unshipped.

### T011 acceptance — 2026-10-04

PostgreSQL atomic publication accepted after independent task review and test-only fix1 scoped
re-review. Facts, row-locked mission revision, event and original receipt share one actual
transaction. Rollback, deferred commit refusal, cancellation settlement, connection reuse,
conflict refusal and reordered replay are observed on the dedicated local PostgreSQL backend.
Review I1 exposed a concurrency test that could pass through INSERT uniqueness without testing
the existing-row revision lock. Two deterministic existing-row publication/replay controls fail
under the no-FOR-UPDATE mutant and pass unmodified; scoped re-review closes I1/M1 with no new findings.

Amended covering:231passed3skipped157.58s; all23 owned PostgreSQL cases pass. Sole amended full:
62failed2813passed46skipped2warnings570.76s, wrapper exit1 with completed cleanup. Exact failed and
skipped node lists remain identical to the original full; this is not all-suite GREEN. Original
covering677passed7skipped retained an outer wrapper exit2 after pytest/cleanup; that historical
runner error is not relabelled success. Corrected immutable covering runner exits0.
Source SHA256 `10103cc0b4f297b678bd91e7d6101c3c7b353bd1dc1fbe22bd1bdf6f06467dc0`;
tests `62b5278b6081ec911b621313ec503628cd23953546efa2debca756bb470b684c`;
scoped review `ee88b6f7b9670788fefe688f947d40f2d4781dc062927fa136e3b271f3f18fed`.

Original three PostgreSQL T004 nodes remain skipped; new physical controls cover the writer
obligations, not skipped runtime coverage generally. Dedicated no-bootstrap/coherent readers and
journal ownership rewrite races remain T012–T015; canonical membership/outward allowlists T023;
old-schema rehearsal/minimum runtimes T084/T087/final; browser/connector/UAT T086/integration;
inherited failures/warnings/instruction reconciliation T087/final. None is waived. Eleven of92
tasks complete; T012–T092 remain unchecked. Work remains local, uncommitted/unmerged/unshipped.

### T012 acceptance — 2026-10-05

Test-only read-boundary design accepted after independent review and scoped fix1 re-review.
Forty owned cases comprise ten executed real-engine controls and thirty missing-reader-API RED
requirements. SQLite file/private-memory and PostgreSQL fixtures, physical read-only observers,
legacy bootstrap characterization, schema/scope/page/coherence/lifecycle assertions are present.
No dedicated reader exists yet; assertions after absent API lookup remain unexecuted. This
acceptance approves failing tests, not no-bootstrap runtime or backend parity.

Review I1 corrected captured closed-memory connection assertions; I2 freezes reader ownership
before writer scheduling; I3 retains original caller PostgreSQL pool identity/liveness and guards
unauthorized close instead of accepting factory recreation. Four added real controls execute these
mechanisms. Scoped re-review closes all three without new findings. Covering202collected:
172passed30expectedfailed8.59s, no skips/errors/warnings. Sole amended full2961collected:
92failed2823passed46skipped2warnings373.44s, outer exit1 with actual cleanup. Exact all92failure
lines and46skip reasons match the original T012 full; inherited62failure lines match T011fix1.
Nothing is suppressed or relabelled all-suite GREEN. Failed pre-admission launcher is retained
separately from the one admitted original full; no observed suite was restarted.

Test SHA256 `21d2a5c4aaf482d19494cfbded16ad513fbaa0547b2a9a2f3848c34307873f9f`;
incremental fix `e9bb47355bb4124fe72ccbacc59305f39e5f52c768054babd7377a2535784ef6`;
scoped review `ed38018743a35f0363d3d8dcca343c19233f057f62272b773fa4126be80a2de2`.
Minor M1 unknown/missed/future cursor resync controls remain T013/T014/T015 and final review.
Actual reader execution, cross-loop/cancellation/lifecycle parity and unknown values remain
reader/parity gates; outward allowlists T023; minimum runtimes/inherited failures/warnings and
instruction reconciliation T084/T087/final; wiring/browser/UAT/integration/shipping remain open.
Twelve of92 tasks complete; T013–T092 remain unchecked. Local work is uncommitted/unmerged/unshipped.

### T013 acceptance — 2026-10-05

Dedicated SQLite file/private-memory reader accepted after independent task review and scoped
fix1 re-review. File reads use existing-file mode=ro/query_only and one pinned transaction;
initialized memory copies the actual owner database under its existing mutation/lifecycle lock
through settled backup, then reads a dedicated pinned view. No lazy schema initialization,
caller close, collector/credential lookup or stored-data repair occurs. SQLite-managed WAL/SHM
coordination is allowed under the recorded agent clarification; filesystem immutability is not
claimed. Exact selected journals, bounded stable pages, actual membership counts/high-water,
cursor resync, NULL facts, committed WAL and lifecycle/cancellation controls execute on real stores.

Independent review I1 reproduced a SQL-accepted malformed outcome leaking a domain exception.
Four explicit canonical validation exceptions now return typed UNAVAILABLE/READ_UNAVAILABLE;
ten physical file/memory negatives across outcome, qualification, manifest, Brief and claim
move from10RED0.66s to10GREEN0.62s without weakening schema or changing corrupted data.
Scoped re-review closes I1 with no new breakage. Covering514collected:501PASS9PGreaderRED4SKIP
34.11s, no warnings/setup errors. Owned boundary70cases:58SQLitePASS (including7legacy controls),
3PGphysical controlsPASS and9futurePGreaderRED. These three PG controls do not prove T014.

Sole amended full2991collected:71FAIL2874PASS46SKIP2warnings327.72s, actualEXIT1 and cleanup.
Root read terminal and compared all71FAILED and46SKIP reason lines against original T013;
inherited62FAILED also match accepted T012fix1 exactly. No suppressed/renamed failures or skips,
no full-suite GREEN. Source SHA2560642ee5b2d0be287cc0e23ad1288ee513a75ba36bafe01cbe49484dc3895253f;
tests2f319cae6f4d5f83f95f1d6d188f4b622eada143aafbe3b187dadeb57592e00b;
incrementalfix65b1b8a10f6d0257e88028fdcb34e009f9db49a1a55bc36c0f9a82747c9bb1c0;
scopedrereview07cfbd238ae3e3facb04ae7608e1445095b6751603c9a09c0bf44152e0092ee0.
Accepted repositories/port/domain remain hash-identical to their prior task receipts.

Minor M1 inherited coroutine warnings remain T087/final. T014/T015 retain PostgreSQL reader,
cross-loop resource ownership, parity and original three PG fault/scheduling skips. T023 retains
outward mission/run/frame allowlists/masking; minimum runtime/old-schema rehearsal T084/T087;
wiring/viewer/browser/UAT/integration/shipping remain later explicit gates. None is waived.
Thirteen of92 tasks complete; T014–T092 remain unchecked. Local work is uncommitted/unmerged/unshipped.

### T014 acceptance — 2026-10-05

Dedicated PostgreSQL reader accepted after independent spec-compliance and quality review,
both Approved with no Critical/Important/Minor findings. Side-effect-free construction captures
store identity only; each load owns a separate invoking-loop AsyncConnection and one actual
read-only repeatable-read transaction before schema/canonical SELECTs. Entire lifetime is held
through settlement/close under repeated cancellation; original caller pool is preserved.
No bootstrap, setup, stored-data repair, new dependency, MCP signature or connector-tier change.

Actual boundary90PASS15.64s, covering534collected530PASS4SKIP34.13s, EXIT0/readiness/cleanup,
no warnings/setup errors. Original SQLite cases remain, all20newPG controls execute, including
cross-loop ownership/PIDs, actual read/close cancellation, write refusal, exact selected/null
run, native unknowns, coherent competing-commit views, cursor resync and malformed domain state.
Source SHA2564b1e2f879065bec71a609908d0ca53c4487fb32452966fdde98de96156474481;
tests10eadbc4bec62e7e7bd5fbc2442b5b1114053563b9efa76b0f92227a218df540;
incremental review67c76ecb8a6e30b5d62f502db8efc2212bb05eefaa2501579ddc6523bcafec94;
report2cff9c3d14968dc4dd323381ff95b986718f63fe54244b652e3c8f4ffdfefb67;
independentreview32bf9c8f24447a221a8ff03f388993e52ffab04f90f6064315c3de8001958b99.
Root read actual report/review/terminal logs and verified frozen/predecessor hashes.

Review cannot-verify boundaries resolved by task mapping, not presumed complete: T015 retains
three original PostgreSQL fault/order skips and private-memory separate-store non-applicability;
T023 retains outward membership/sanitization, later viewer tasks DOM/motion/integration. Dynamic
cancellation controls pause actual reads and close; open/transaction-exit intervals are covered
structurally by the same settlement lifetime, not separate physical pause controls. Retain this
limit for T015/lifecycle/final verification. Python3.11 minimum runtime, broader regression,
inherited warnings/RED, packaging/hosted/UAT/integration/shipping remain later explicit gates.
No duplicate all-project run was required for T014; focused/covering success is not full GREEN.
Fourteen of92 tasks complete; T015–T092 remain unchecked. Local work is uncommitted/unmerged/unshipped.

## T015 acceptance — 2026-10-05

Original legacy PostgreSQL event/fact refusal and contended commit-order nodes execute and pass;
the foundation covering gate records718PASS2SKIP77.64s with actual cleanup. Both skips are exact
backend non-applicability, not PostgreSQL gaps. A physical journal ownership rewrite reproduced
incompatible successful readback; the approved same-pinned whole-history lineage guard changes
36 failing ownership/cursor controls to39 passing cases, retaining multi-run mission events.
Initial independent review found one Important cleanup-unwind defect in the new journal race.
Two bounded physical early-error controls reproduced55P03 and orphan fixture DDL; one inner
finally correction preserves original assertion/cancellation and clears trigger/function.
Post-fix affected gate151PASS0SKIP35.70s with cleanup/no warnings; scoped rereview confirms
ADDRESSED, no new breakage. Pre-fix718-covering and amended151-direct are distinct revisions.

Final report48eccaf03c0df313080c278fa3cff850ce8bd676253494003cdd102fb6df98de;
foundation6b9f6573aba8bb0a72814f55fbe5bc826a861a2ff47b5114f70ed1dbe136b0a2;
initial review7e527c559c89b8feeab7a61b4f033d17cf41a6b4028024543fbf703e502c7ad6;
scoped rereview5eb4da88544d08fc2cc32b085c99fe25dee6f9b2051354821dbe5478bfd4c599.
Root read actual terminal evidence and reports, verified tested/current hashes and unchanged
producer/domain/port/schema hashes. Readerccb53b23..., boundary7f5339b9..., progress1e19c3d3....
Malformed-lineage variants and opening/transaction-exit dynamic cancellation remain T081/T089;
performance T083, minimum runtime/full regression T087, outward scope T023/T081 and actual UAT/
acceptance/integration T090–T092 remain open. No historical broad RED is waived.15/92 accepted;
T016–T092 remain unchecked. Local work remains uncommitted/unmerged/unshipped.

### T016 acceptance — 2026-10-05

Test-design gate accepted after independent initial review and two scoped fix reviews.
Initial five Important findings: four addressed in R1; the zero-delta preservation residual
addressed in R2, with no new breakage. Actual use cases and canonical SQL readbacks cover
arrival/membership, state, qualification and claim facts/events, selective physical faults,
exact state reasons and identical qualification/claim retries on disposable SQLite file,
SQLite memory and PostgreSQL. No runtime source/schema change belongs to this task.

R1 source14b0a7fb...:66 executed,36 expected missing-producer RED,30 PASS,zero skips,12.75s.
Final source253333a8... adds three backend no-op preservation controls:69 collected,
6 selected,3 PASS/3 unchanged positive-delta missing-receipt RED,63 deselected,2.27s.
Both retained runs include local readiness and PostgreSQL scratch cleanup receipts.
The remaining63 nodes were not rerun on the final hash; historical evidence is not relabeled.
Report0b440ed3..., R1 review0086df73..., R2 review02c83702..., R2-only patch09e53231....
No current producer atomicity/replay-with-present-receipts, terminal-kind installation,
projection, security, minimum-runtime, broad integration, live UAT or shipping is inferred.
Those remain T019–T023/T081/T084/T087/T089–T092. Canonical16/92; T017–T092 unchecked.

### T017 acceptance — 2026-10-05

Tests-only gate accepted after independent initial review and scoped R1 re-review.
All four Important test gaps addressed: distinct selected non-null runs, DEBUG logging
of successful payloads and refusals, duplicate/override CSP rejection, and admission-based
three-second deadline bounds excluding four seconds. No new fix-diff breakage identified.
Final source77f7311e764e323dab19f1897de4bf20bf919dba39594b85e857f38339b0e2b1;
report e4f15e7155e2f4a74a904b3f35c8c1df52ac33570c467c0e9e0838204526157f;
scoped review90e8a33bf86b19dc0a3b0eac77bea784bbad6109e4e4d9c852ea53ffa4a15eaa;
original-base fix patch618ea051d65eda09edac7a9997738b307981f899f42e0db42f72dc1114024691.

Original revision:90 call-phase missing-listener RED/9 unchanged Task Relay anchor PASS.
Earlier R1 e51ec142...:104 collected28 selected,17 call-phase API-absent RED/11 pure
assertion-readiness PASS,76 deselected,zero errors/skips,0.15s. Final revision:104 collected,
4 selected logging cases,4 call-phase API-absent RED,100 deselected,zero errors/skips,0.14s.
Root read actual report/review/log/outcomes and verified tested/frozen/current hashes.
No final whole104-node run or HTTP/auth/security/timing behavior is claimed. Actual typed
provider-readiness fixtures are not listener proof. No product source/schema change or stub.
Unchanged Minor short-expiry stability and HEAD root-CSP/refusal controls remain T024/final
review. Real listener T024, lifecycle T025, projection/zero-write integration T030, browser
T027–T029/T066, security T081, regression/minimum-runtime T087 and final acceptance/
integration T089–T092 remain unchecked. Canonical17/92; T018–T092 unchecked.
Local work remains uncommitted/unmerged/unshipped.


## Session 2026-10-05 — Checkout consolidation and T018 acceptance

Owner confirmed Spec 014 implementation and then required all work to return to the primary
checkout and redundant worktrees to be removed. The active path is now
`/Users/fioenix/Projects/fn-ignis`, branch `codex/ignis-relay-checkout`, HEAD
`e543ccbf30b4745ad9fd83ab09cc2dcf012beff8` plus uncommitted imported implementation and
T018 corrections. The original owner checkout changes are retained in recovery files/stash;
TypeSafe guidance and retired-plugin removal were reconciled with mission-bound guidance.
Four old worktrees have verified local recovery archives; the continuation worktree has a
native Codex archive. Git reports exactly one checkout.

T018's independent review found an observer lifetime deduplication false negative and substring
count assertions. The first correction exposed a nested-subtree double-counting false positive;
the second correction selects the deepest added ancestor while preserving repeated insertion
occurrences. A real installed isolated Chromium instrument test checks direct insertion, reused
node reinsertion and a prebuilt subtree under two newly inserted ancestors. Packet/history totals
now use dedicated exact count anchors. Independent read-only review accepts the corrected RED
test design with no remaining blocking finding in that scope.

Fresh focused verification on the primary checkout: **23 passed, 33 failed, zero skipped**.
The 23 passes are the browser instrument control, 11 existing HTML builder cases and 11 repository
convention cases. All 33 failures are prerequisite RED: one absent maintained template and
32 absent typed builder seams. No product browser negative has executed beyond those absent
prerequisites; T018 accepts test design, not viewer behavior, UAT, full-suite GREEN or shipment.
See `.handoff/spec014/t018-corrected.xml`, `t018-corrected-outcomes.json` and
`continuation-t018.handoff.md`. T019–T092 remain unchecked. No product migration, live connector,
client configuration, release metadata or GitHub write occurred in this continuation.


### T019 acceptance — 2026-10-05

SQLite narrow fact/event transactions accepted after independent review and executed controls.
Collection state, observations/membership, reattachment/pruning, qualification and claim commits
share physical fact/event/revision transactions. Pruning also records actual trigger-driven claim
status changes with consecutive ordinals under the same revision. Canonical references and selected
run/workspace scope are read from storage; analysis frames are rechecked within the write transaction.
Silent legacy saves remain unchanged; actual T016 producer wiring remains T021/T022.

Initial review exposed cancelled/concurrent same-object replay and missing pruning; physical controls
reproduced the defects before correction. A Market cascade fixture then exposed a missing ledger-gate
receipt; correction and scoped re-review close all blocking findings. Final 56 direct SQLite
file/private-memory cases pass, including selected physical fact/event denials, cascade rollback,
replay identity, stale-frame refusal and cancelled/concurrent sighting retries. Covering602:
591PASS11SKIP0FAIL0ERROR,11.35s. Ten skips need a real PostgreSQL test DSN; one is independent
private memory stores. Ruff and whitespace checks pass.

Final full3319:2501PASS231FAIL587SKIP0ERROR2warnings. All231 failing node identities match the
preceding isolated full run (which already included T019 changes, not a pre-change baseline).
Missing HTTP/projection/producer/template behavior and retained environment/runtime/doc checks remain
named in the handoff; no full-suite GREEN. Exact source/test hashes, commands, incremental patch,
review disposition and complete failure names are retained in `.handoff/spec014/t019/`.

COLLECTION_STATE_CHANGED was already required by T016 but absent in the model/schema allowlists;
T019 adds this internal kind to the model, fresh SQLite bootstrap and unshipped SQL027. No installed
DB was upgraded; old-schema CHECK refusal remains atomic, compatibility rehearsal remains T084.
PostgreSQL parity, minimum runtime, UAT, integration and shipping are unverified. Nineteen of92
accepted; T020–T092 open. Work remains local/uncommitted on primary checkout `codex/ignis-relay-checkout`.


### T020 acceptance — 2026-10-05

Equivalent PostgreSQL collection state, observations/membership, reattachment/pruning, qualification
and claim fact/event operations accepted after independent review and physical verification.
Events retain canonical source/observation identity; revision/facts/events roll back together.
Cancelled/concurrent same-object retries retain committed identities without another arrival;
pruning and actual cascade-triggered gate changes share a revision with consecutive ordinals.

Review found a legacy-writer frame race and duplicate batch references. Both were reproduced RED
and corrected; scoped re-review leaves no actionable finding. Fixed-order canonical table fences
precede journal/revision locks, including the existing outcome publisher. Analysis uses SHARE ROW
EXCLUSIVE; collection/probe use ROW EXCLUSIVE. Cross-mission analysis blocking is an explicit cost,
not a performance claim. Duplicate judgments preserve the legacy count while recording one fact
reference. The unfenced-frame mutant fails two cases; removing the early probe gate produces an
actual PostgreSQL DeadlockDetected. Neither mutant changes product source.

Final direct32PASS0FAIL0SKIP30.07s. Final covering273PASS0FAIL0SKIP0ERROR125.058s;
related unit146PASS0FAIL0SKIP2.799s. T016 producer chain: 33 PASS, 36 FAIL, 0 SKIP, 0 ERROR; 24.587s.
All36 failing node names match the historical T016 fix2 failure set. T016 failures remain producer
integration work for T021/T022, not adapter acceptance or full-suite
GREEN. Exact logs/XML, tested source hashes, incremental patch, review dispositions and cleanup
receipts are in `.handoff/spec014/t020/`. Ruff/whitespace checks pass. Existing-schema compatibility,
minimum runtime, full regression, UAT, integration and shipment remain open. No hosted DB or installed
schema was changed. Twenty of92 accepted; T021–T092 open. Local/uncommitted work is parked at this
accepted task boundary in primary checkout `codex/ignis-relay-checkout`.


### T021 acceptance — 2026-10-05

Owner goal explicitly assigns completion of T021. Journal-bound collection state, observations,
membership reattachment/pruning and outcomes use the accepted fact/event boundary through the
narrow ICollectionRelayWriter port and configured workspace facade. Unscoped legacy writes,
separate cluster writes and journal projections retain their contracts; no globally atomic pass,
filesystem event fallback, signature, source-authority, schema, dependency or release change.

Before implementation the actual collection selection had24FAIL12PASS. Final original T016
producer cases have57PASS12FAIL; combined with18 added cases,75PASS12FAIL0ERROR0SKIP27.893s.
Exact node comparison proves all24 T021 failures are now PASS; the12 residual failures are the
unchanged T022 qualification/claim receipt cases. Physical fact/event denials, no-op preservation,
pruning rollback and earlier committed arrivals retain canonical identity on all three backends.

Independent P2 reproduced cancellation during terminal commit causing a forbidden FAILED rewrite
and contradictory journal. Correction retains canonical terminal settlement and original exception;
entire failure cleanup read/write settles even under repeated cancellation. New physical terminal
commit/rollback, repeated cancellation, vocabulary failure and late outcome-event refusal controls
pass on SQLite file/memory and PostgreSQL. Scoped re-review leaves no actionable finding;
independent SQLite12PASS. Full run exposed two legacy host test gates still waiting on update_mission;
the gate now pauses the actual commit_collection_state writer without changing any assertion.
Independent gate review confirms no weakening and independently reruns two SQLite cases PASS.
Final host/workspace/T021/convention regression137:135PASS2SKIP0FAIL0ERROR51.973s. Both skips are
SQLite-thread-only controls on PostgreSQL, not missing PostgreSQL fact/event coverage.

Full project pytest on final product code before host test gate adaptation:
3369total3148PASS201FAIL10ERROR10SKIP2warnings542.96s, actual exit1; local PostgreSQL scratch cleanup
verified. Remaining recorded failures:93 HTTP,58 projection,33 browser,12 T022,2 host gate timeouts
subsequently resolved, and3 inherited environment/public-doc checks. Ten clean-install setup errors
inherit isolated configuration without IGNIS_ENV_FILE; no bootstrap acceptance is claimed. Exact
node names, skip reasons, source revisions, warnings and dispositions remain in the handoff.
This full result is not renamed GREEN or relabeled as a full rerun after the gate correction.

Ruff and whitespace pass; T020 adapter/test predecessor hashes unchanged. Final hashes, patches,
XML/logs, three review records and requirement audit are in `.handoff/spec014/t021/`. T022, full-feature
regression/minimum runtime T087, old-schema T084, UAT and integration T090–T092 remain open. No hosted
DB or live social session was accessed.21/92 accepted; T022–T092 unchecked. Work is explicitly parked
at this accepted local/uncommitted task boundary on primary checkout `codex/ignis-relay-checkout`.


### T022 acceptance — 2026-10-05

Both analysis submissions route through the additive IAnalysisRelayWriter and WorkspaceRepository atomic delegates; legacy internal save consumers and public use-case/tool signatures remain unchanged. New typed stale subclasses under the existing Invalid* families specialize only the four existing SQLite/PostgreSQL frame-fence raises. Early catches preserve CONFLICT/STALE_FRAME and zero submission facts/events/revision. Generic foreign-evidence, conflicting-rewrite and malformed-claim responses stay distinct. The existing postcommit frame-change test now gates after physical commit and retains every original permission/history assertion. No schema, dependency, connector-tier, version, client-setting or generic SQL capability change.

Fresh RED:12FAIL18PASS39deselected8.92s at the original analysis producer boundary; transaction-window repair controls6FAIL0ERROR0SKIP12.26s before fix. Final scoped314PASS0FAIL0ERROR0SKIP68.83s covers original69 producer tests,6 new race controls, qualification/claim units, Market mission chain, conventions and both adapter suites. Independent R1 review closes sole P2, no new actionable findings; reviewer separately executed20 SQLitePASS and checked nine matching final source hashes. Parent executed actual PostgreSQL parity; no reviewer-independent PostgreSQL claim.

Final full project:3375total,3168PASS187FAIL10ERROR10SKIP2warnings598.10s,exit1; local PostgreSQL scratch cleanup verified. All36 original producer failure IDs now pass. No new failed/error node versus T021;12 T022 nodes and the2 previously corrected host cancellation nodes are resolved. Remaining187 failures:93 absent HTTP listener,58 absent projection,33 absent viewer-template builder, and3 inherited isolated-settings/public-doc checks. Ten clean-user-journey setup errors retain isolated child configuration without IGNIS_ENV_FILE. Exact node identities/disposition and original skip reasons are preserved in ignored task evidence. No clean-install, minimum-Python, full-suite GREEN, viewer/UAT or integration acceptance.

Completion audit and canonical ledger are settled:22 accepted,70 future tasks open. T022 is implemented, reviewed and locally verified; changes explicitly parked at this task boundary. No commit/push/merge/deployment/release occurred. T023 coherent allowlisted projection is next; do not start it under the completed T022 goal.


### T023 acceptance — 2026-10-05

The consuming module implements explicit typed full-corpus projection functions and one-read snapshot/inspection use case. Direct projection requires the supplied committed high-water including ordinal; the adapter path retains the exact coherent read request, counts, selected journal, event pagination/resync and evidence offset. Inspection accepts only an observation on that selected membership page, without a global lookup or implicit scan. Channel coverage preserves declared unknowns separately from measured EMPTY_NO_DATA/zero and recorded operational notes. Attention context and Market evidence associations remain distinct; v1 qualification direction stays unknown. Partial pages do not derive an evidence frame or claim permission; T032/T034 retain those gates.

Outward fields use existing typed allowlists plus frozen channel DTOs. Text is sanitized, source navigation rejects unsafe/credential-bearing URLs, serialized JSON is bounded to1MiB UTF-8 without truncation, and huge finite integer metrics avoid float overflow. Independent P2 identified non-object canonical metadata escaping as AttributeError; six behavioral RED cases now return exact typed UNAVAILABLE through an explicit Mapping check, and re-review closes the finding. No remaining Important/Critical finding.

Final scoped verification:369PASS0FAIL0ERROR0SKIP29.65s across T005, domain/port, all132 read/projection backend cases and conventions. Reviewer independently161PASS. Full pytest:3394total3246PASS128FAIL10ERROR10SKIP2warnings432.99s; no new failed/error node, no disappeared prior node, all369 scoped nodes PASS in full. All58 original T005 failures now PASS; one inherited public-doc failure also resolves from the preceding commit repair. Remaining failures:93 future HTTP,33 future browser,2 inherited isolated-settings assertions;10 inherited clean-user bootstrap errors,10 disclosed skips and2 inherited unawaited-AsyncMock warnings. Every full node/disposition is retained in local verification records. Ruff/diff checks pass.

Canonical ledger23/92,69 later tasks open. T023 is implemented, reviewed and locally verified, explicitly parked at this task boundary; no T023 commit/push/merge/deployment/release occurred. T024 is next and remains outside this completed goal. No social session, credential, tool signature, dependency, client configuration or persisted evidence transformation changed. Full-feature GREEN, browser/UAT/minimum-runtime and integration remain unaccepted.

### T024–T025 local acceptance — 2026-10-05

The separate loopback transport enforces exact host/origin, GET/HEAD, raw8192-byte request and1MiB UTF-8 response limits, explicit finite scope, process4/per-capability1 read admission and3s response deadlines. Authorization is also tracked; expiry is rechecked before mint. Independent T024 review closed two P2s with genuine socket RED regressions. Initial transport/model/convention203PASS; subsequent T025 final123PASS rechecks all106 transport cases after settlement changes.

FastMCP owns lazy read-only composition, opens no listener/storage at startup, borrows only initialized memory storage or configured file/PG identity, and cancels/revokes before waiting for actual settlement. Cancelled shutdown regression was genuine RED; await_settled plus unbounded shutdown settlement fixes ownership while observer wait_closed deadlines preserve pending reads. Independent real-lifespan probe retains a read beyond5s and releases only after cleanup. Physical SQLite/memory/PG reads and fresh provenance check133PASS; no scratch PG database retained. A permanently stuck underlying cleanup can delay shutdown; it must never be mislabeled settled.

Full3396 result3340PASS36FAIL10ERROR10SKIP2warnings resolves93 HTTP failures. It overlaps T025 source editing; one source-inspection assertion used stale function line positions and fails in that mixed run, then passes in a fresh process. Do not treat it as final immutable US1 verification or a green suite. Full evidence stored t024/full.xml; original t023/full.xml restored from hash-matching full-accepted.xml after correcting launcher output destination. Remaining browser/config/clean-install gates retain prior dispositions. Canonical25/92;T026–T031 still required for US1, no commit/integration/UAT/release claim.

### T026–T027 local acceptance — 2026-10-05

Only open_mission_relay/get_mission_relay_snapshot are added to FastMCP. Required selected scope/deadline/page inputs use typed explicit allowlists and lifespan injection. Browserless snapshots open no socket; shared process4 read admission,3s deadline and true cancellation settlement apply to HTTP and MCP. Initial5 API/registration RED; final237PASS (17tools,106HTTP,7lifecycle,10existingMCP,86models,11conventions). Independent130PASS plus freshrevocation1PASS. Review P2 late successful MCP return after revocation reproduced through actual client, then fixed with shared closed guard; expiry rechecked before listener creation.

Maintained mission_relay.html/default builder use original unmodified FINOLABS theme, light product roles, escaped text and script-safe tojson, explicit UTC expiry and sibling read targets without opaque capability disclosure. Four malformed route shapes produced4RED, then exact fullmatch fixed them. Final18PASS:13builder,2defaulttheme,3isolated390/768/1440 no-script/font-blocked browser cases; independent13-unit recheck and screenshot inspection. Offline test distinguishes Chromium runtime-execution disable from HTML parser scripting flag, and verifies actual visible identity/count/evidence facts and page overflow independently. No browser installed, live session or new external resource used.

T028 navigation/inspection, T029 refresh/events, T030 real transport integration and T031 stable-source US1 gate remain open; the temporary transport shell is not the final viewer. Canonical27/92, goal active; no commit/push/merge/release/UAT/shipment acceptance.

### T028–T029 local acceptance — 2026-10-05

T028 independently reviewed navigation, authority identity, recorded source availability and safe selected-page role inspection;17 scoped browser cases and13 template cases passed. T029 closes the once-only finite refresh/receipt surface: final71PASS13.57s, independent71PASS11.39s with zero skips. Two independently reproduced P2s now have durable RED regressions and corrections: inspection serializes behind the pending refresh without losing selection; incomplete or mismatched event pages cannot advance the cursor. Four independent probes cover successful revision advancement plus inspection, missing receipt rejection, two-page continuation exactly once and hidden late-response refusal. Recent receipt retention is disclosed and bounded to page_size≤200 and1MiB. Full browser coverage includes expiry/pause/reduced motion, exact counts, role separation and no synthetic throughput. Reviewer frozen hashes match current template/browser-test files; evidence .handoff/spec014/t029/{gate-final.xml,review-final.xml,review.handoff.md}. Canonical29/92; T030/T031 still required for US1. No commit, integration, real-mission UAT or shipment acceptance.

### T030 local acceptance — 2026-10-05

The real capability HTTP root now reads its selected scope through the same owning-loop budget and renders the maintained typed FINOLABS document. The temporary shell is removed. Dynamic CSP hashes cover inline JSON, script and style bytes; only pre-existing Google Fonts origins are admitted. Expiry is rechecked after rendering. Actual FastMCP Client→HTTP→isolated Chromium tests run against disposable canonical SQLite file, private memory and PostgreSQL: identity, coherent global counts, page continuation, inspector, unchanged refresh, unavailable research and withheld synthesis. Bootstrap/component/credential traps remain zero; whole schema/table state is unchanged. PostgreSQL repeatable-read read-only coherence is checked separately inside each real reader call, not across unrelated read transactions. Missing/old/denied storage refuses before bootstrap. Coordinator139PASS25.73s; independent frozen-source139PASS26.09s, no skips; actual post-render deadline probe403/CAPABILITY_EXPIRED. Evidence .handoff/spec014/t030/{verified.xml,review.handoff.md}. Source inventory287 files matches reviewer. T031 still pending; no commit, merge, real-mission UAT or shipment acceptance.

### T031 / US1 internal slice acceptance — 2026-10-05

Final gate on frozen current source covers all36 US1 and original mission/Task Relay regression files:1348PASS3SKIP0FAIL0ERROR in224.93s. The287 Python/template hashes match before/after; runner confirms zero leftover disposable PostgreSQL databases. Two skipped PostgreSQL parametrizations concern a SQLite-only thread-settlement control whose SQLite cases pass; the third release-banner assertion has no unreleased-state premise. These skips are disclosed, not counted as passing. Final Ruff and git diff --check pass.

Independent final audit accepts every T024–T031 requirement and all three US1 scenarios with no open finding. The last corrections preserve exact selected-journal STARTED and canonical mission state, render Idle only for recorded PENDING, and retain legacy Unknown. Actual FastMCP→HTTP→isolated Chromium transition controls on SQLite file/private memory/local PostgreSQL prove new observations and support/contradiction qualification animate once with their stored provenance/roles; refresh/reload do not duplicate arrival/count, and guarded viewer phases leave whole physical storage unchanged. Coordinator correction gate259PASS0SKIP; independent state/real-transition gate18PASS0SKIP15.91s. Evidence: .handoff/spec014/t031/{scoped.xml,scoped-status.json,final-source-before.json,reviewer-final.xml,review.handoff.md,completion-audit.json} and .handoff/spec014/us1.handoff.md.

The earlier repository-wide run was intentionally interrupted for the final acceptance corrections; its retained pre-idle artifacts are intermediate history, not full-suite GREEN. T031 requires US1 plus existing mission/Task Relay regressions, fulfilled by the stable36-file gate. Unsupported research activity remains unavailable and strategic permission withheld for this internal slice. Canonical31/92; all US1 tasks accepted locally. T032–T092, real-mission UAT, later full-feature/performance/minimum-runtime/security gates remain open. Work is explicitly parked uncommitted/unmerged on codex/ignis-relay-checkout at HEAD9eae76a plus the verified dirty US1 changes; no commit, merge, deployment or release occurred in this goal.

### T032 test-design acceptance — 2026-10-05

Canonical Market fixtures establish real persisted PERMITTED and same-frame WITHHELD rows. Exact original binding, unknown500/3.5 versus known-zero0/0, requested-journal mismatch, selected-run STARTED/RUNNING/FAILED/CANCELLED, changed corpus history, paginated full-frame and canonical specific qualification Gap assertions have independent review. Coordinator9RED3PASS0ERROR0SKIP0.69s; reviewer9RED3PASS0ERROR0SKIP0.74s. These are test-design acceptance and future T034 implementation obligations, not gate permission PASS. Setup-only failures were corrected before the final receipt; no product code changed for T032. Evidence .handoff/spec014/t032/{red-r2.xml,reviewer-r2.xml,review.handoff.md}. Canonical32/92; T033 next.

### T033 test-design acceptance — 2026-10-05

Five browser negatives require visible current claims before a network, foreign mission/run, reordered cursor or incompatible-frame read. They retain the exact last successful receipt, require a newer failed attempt receipt/reason, remove current permission without stage-navigation resurrection and retain labeled history. Test-local native fetch/JSON boundary and stable-inspector MutationObserver measure removal under50ms; independent parent-replacement control proves the observer survives correct DOM replacement. Independent5API-contractRED47deselected0ERROR0SKIP1.06s with installed isolated Chromium. Typed gate is absent, so stale behavior is not yet executed; T034/T036/T037 remain obligations. Review accepted corrected design; evidence .handoff/spec014/t033/review.handoff.md and reviewer XML/log. Canonical33/92.

### T034 implementation acceptance — 2026-10-05

Typed gate consumes the canonical complete Market corpus and latest selected journal in the same no-bootstrap read-only transaction, while outward pages remain bounded. Exact canonical frame, current question qualifications, strategic sufficiency and persisted PERMITTED rows/bindings govern permission. Incomplete runs remain PENDING/unavailable; selecting an older completed journal returns HISTORY/WITHHELD; changed ledger rows stay labeled history. Unknown metric annotations hide placeholder metric/growth while preserving known zero. Independent P1 nested Gap privacy bypass was reproduced and corrected with an explicit sanitized Gap allowlist; canonical machine reasons/counts remain intact. Final seven-file gate396PASS0SKIP38.87s, PostgreSQL scratch cleanup verified; independent13PASS0SKIP0.97s plus actual newer-STARTED-history refusal probe. Ruff/diff-check pass. Evidence .handoff/spec014/t034/{final.xml,privacy-red.xml,review.handoff.md}; browser stale/rendering T035–T037 remains unverified. Canonical34/92.

### T035 local acceptance — 2026-10-05

T035 persistent header keeps selected identity, successful read and separate failed attempt/reason. Coordinator73PASS5deselected10.01s; independent73PASS5deselected9.99s, no failures/errors/skips. Genuine missing-attempt RED retained; T033 five stale claim cases await T036/T037. Evidence .handoff/spec014/t035/{verified.xml,review.handoff.md}.

### T036 local acceptance — 2026-10-05

T036 exact stored ledger claims render bindings, limits and revision conditions; otherwise actual Gap Report retains missing evidence, probe, authority and cost. No-script fallback retains these facts and fits390px. Three independent P2s reproduced then corrected (obsolete stage copy, incomplete offline Gap, digest overflow). Final77PASS5deselected13.51s; independent77PASS5deselected11.80s, no failures/errors/skips. Evidence .handoff/spec014/t036/{final3.xml,review.handoff.md}; five T037 stale controls remain open.

### T037 local acceptance — 2026-10-05

T037 failed/incompatible reads remove displayed current permission synchronously, keep exact successful receipt and separately label prior claims as SUPERSEDED History. Client validates gate/frame/Brief/binding-owner and shape before accepting responses. T0335 genuine behavioralRED nowPASS; coordinator82PASS16.25s, independent82PASS13.10s plus4 malformed-gate negatives PASS. Evidence .handoff/spec014/t037/{verified.xml,review.handoff.md}. No real-mission UAT acceptance.

### T038 local acceptance — 2026-10-05

T038 actual FastMCP selected-scope tool and capability HTTP inspector refuse foreign observation, unknown observation and foreign journal with exact SCOPE_MISMATCH. EMPTY_NO_DATA0, DEGRADED and later declared unmeasured channel null stay distinct; committed corpus/storage unchanged and bootstrap traps silent. Coordinator shared15PASS5.68s (T0383); independent shared15PASS6.43s (T0383), no skips, verified PostgreSQL scratch cleanup. Evidence .handoff/spec014/t038/review.handoff.md and t039/reviewer-final.xml.

### T039 local acceptance — 2026-10-05

T039 actual pinned read-only store gates verify page1/full corpus frame equality, exact complete observation/source identity and every projected Market role/direction/relation/question fingerprint; scoped Demand inspection hides unknown500/3.5 placeholders and unknown publication. Canonical PERMITTED control and changed corpus/newer STARTED/unknown metric negatives retain exact historical bindings without permission. Independent12PASS across SQLite file/memory/PostgreSQL, shared15PASS6.43s, no skips and zero leftover PostgreSQL test databases. Coordinator strengthened SQLite8PASS0.93s; original combined15PASS5.68s precedes assertion strengthening and is not final parity proof. Evidence .handoff/spec014/t039/{reviewer-final.xml,identity-final-local.xml,review.handoff.md}.

### T040 local acceptance — 2026-10-06

US3 T032–T040 accepted locally. Exact-frame permission, actual Gap/missingness and immediate stale removal verified through canonical stores, actual MCP/HTTP and isolated Chromium. Broad US1/US3 plus mission/Task Relay gate1390PASS3SKIP0FAIL0ERROR237.65s,149 frozen hashes; three known conditional skips disclosed. A final one-line receipt-directory setup amendment has separate3PASS0SKIP17.86s verification; all other148 hashes unchanged. Latest local read-to-display samples3.1msSQLite-file/1.3msmemory/2.7msPostgreSQL are not real-mission UAT or p95 proof. Final independent T040 review accepted; zero disposable PostgreSQL databases left. Evidence .handoff/spec014/us3.handoff.md and t040/{scoped.xml,final-readback.xml,final-source-settled.json,review.handoff.md}. T041–T092 remain open.

### US3 advisory checkpoint settlement — 2026-10-06

The owner approved the exact sanitized payload before one TypeSafe request against implementation revision `6e7662b7988624e2da33dcb05bd5fe970ba64884`. Actual model `jev-1.13.0` returned `SUPPORTED` for local goal alignment and the honest status boundary, and `NO_REPORTED_LOCAL_REPAIR` for the reported remaining gap. Request latency was 0.468s with 1313 input / 160 output tokens; question version `us3-goal-alignment-v1`. Payload SHA256: `eb034c0dc8fc21ab908e6212b6189fafa445fef049bf2761626eef8a8c7b7893`.

The agent compared these advisory answers with the canonical US3 goal and retained executed-test/review evidence; no additional local repair was identified. Confidence is not correctness, acceptance or authority. All 149 settled source/test hashes still match; no implementation/test changed or test suite was rerun for this evidence-only settlement. Evidence: `.handoff/spec014/us3-goal-alignment-result.handoff.md` and `us3-typesafe-result.json`. US3 remains locally accepted, 40/92 tasks; real-mission UAT, remaining stories, full-feature integration and shipment remain pending. T041 was not started.

### T041 test-design acceptance — 2026-10-06

The future consuming domain API contract collects 93 cases; all fail explicitly because `ignis.domain.research_work` is absent, with zero setup errors/skips. This accepts test design only, not executed lifecycle/authority behavior. Initial independent review found an invalid expired-receipt fixture and missing transition fences, cancellation/terminal admission and start-receipt identity controls. The correction fixes all four; scoped independent re-review accepts specification compliance and quality with no new breakage. Final source SHA256: `eeeaac0a2466cecb7004fafa6600f4120a64c3b72d687b690554e7a0a99eb5af`. Evidence: `.handoff/spec014/us4/t041/{task-report.md,pytest.xml,correction-review.handoff.md}`. T043 and later transactional consumers must turn the designed negatives into observed behavior; US4 and real host UAT remain unaccepted.

### T042 local acceptance — 2026-10-06

T042 test-design accepted after independent review and two scoped correction reviews. Final source SHA-256: `41d4d3288067a5ea15ef6b429221a8c964727acda8f78ee68fe4327f5da5fea7`. Exact final receipt: 54 collected, 6 physical controls passed, 48 explicit absent-API failures, 0 errors and 0 skips. Physical canonical setup and unsafe-read controls execute on SQLite file/private memory/local PostgreSQL; future atomic result/history/event/contention assertions do not execute until adapters exist. Safe original receipt replay, exact event identities, immutable finding revisions, canonical input/source identity and no unsafe rejected-body retention are designed assertions, not verified implementation. Evidence .handoff/spec014/us4/t042/{task-report.md,fix2-final-pytest.xml,fix2-final-source.py,fix2-review.handoff.md}. Original 51-case XML/log was overwritten; original frozen source/review hash remain, historical run is report-only. No product schema/provider dispatch or shipment accepted.

### T043 local acceptance — 2026-10-06

T043 immutable assignment/work/input/authority/activity/operation-specific command models and pure guards accepted after independent correction review. Final isolated gate: 131 passed, 0 failures/errors/skips (93 unchanged T041, 27 durable controls, 11 conventions). Named correction RED reproduced 10 assertion failures with 17 negative controls passing before the coherent fix. Exact nested types block serializer overrides. Identity/version/epoch/fence checks remain separate from new-execution authority: bound stop/terminal closure receipts do not reopen ended or expired research. START/RESUME/ACTIVITY remain fenced; COMPLETED still requires an admitted result. Source SHA-256: b6100f2652f1709bb80e438cb798e54d4e06549b89bed55f20bcde8091cf12fa. Tests SHA-256: 21e9072a35af1f16e475a99e557645398d4eedea7b2aac698d739100ad1d8d8a. Evidence .handoff/spec014/us4/t043/{task-report.md,fix1-red.xml,fix1-green.xml,correction-review.handoff.md}. Typed handoff parser, privacy sanitization, transactional CAS/original receipts, persisted termination/epoch/host integration, host overlap and shipment remain later tasks; no provider/storage invoked.

### T044 local acceptance — 2026-10-06

T044 immutable handoff/finding revision records and exact binding validation accepted by independent specification and quality review. Exact targeted receipt: 158 passed, zero failures/errors/skips (27 finding controls plus accepted work/controls/conventions). Constructors preserve unknown frame/Brief and unknown recorded time without calling a clock; enclosing finding/work/handoff/inputs and observation-source coverage must match exactly. Explicit DESCRIPTIVE/STRATEGIC_CANDIDATE types carry no automatic strategic permission. Final source SHA-256: c7b4ecb2bab4b1afeb17fc303356b422b84640e08920ff81cd1874b37812e6f7; tests: 5b4f9f967b00ad2b949b9f1c7890815fc342ce5e6f8b5c18d8aaf8f3ac0c92fb. Evidence .handoff/spec014/us4/t044/{task-report.md,green.xml,review.handoff.md}. T045/store must retain submitted-content equality while separately persisting actual transaction metadata; caller recorded_at is not HARNESS_OBSERVED. Canonical source ownership/membership, append-only persistence, masking, claim permission, integration and shipment remain unverified at this task.

### T045 local acceptance — 2026-10-06

Atomic typed recording port accepted after independent fix-round-1 review: 189 domain/port/convention tests passed, zero failures/errors/skips (2.00s). Ten focused behavioral RED controls preceded correction of provenance, cursor uniqueness, overlapping immutable source identity and metadata bindings. HANDOFF_READY was restored to the approved domain state set with a constructor/projection regression control. Submitted timestamps remain distinct from HARNESS_OBSERVED transaction metadata. Evidence: .handoff/spec014/us4/t045/task-report.md and fix1-{red,green}.xml/fix1-review.handoff.md. This establishes local structural contracts, not adapter transactions, exact replay execution, viewer integration, host UAT or shipment.

### T046 local acceptance — 2026-10-06

Owner-only additive PostgreSQL research schema accepted after independent fix-round-1 review: 46 tests passed, zero failures/errors/skips/warnings (32.60s); scope 21 actual schema, nine packaging, eleven conventions and five affected progress controls. Guarded local runner freshly verified zero disposable databases. Physical controls prove exact ordered immutable input/source identities, membership-pruning history preservation, authorized mission-root cascade, safe observed metadata/receipts, owner-only role denial and permanent collection finalization with a real lock waiter. Initial review reproduced two P2s; one coherent correction passed behavior-specific RED-to-GREEN and preserved legitimate initial population/state-version-fence transitions. Evidence: .handoff/spec014/us4/t046/task-report.md, fix1-green.xml and fix1-review.handoff.md. No SQLite/adapters/current-frame admission/replay execution, all43-progress rerun, installed-wheel migration, host UAT or shipment claim.

### T047 local acceptance — 2026-10-06

T047 core SQLite lifecycle implemented and independently reviewed: 339 scoped offline tests passed (189 domain/port/conventions, 56 physical SQLite lifecycle, 94 existing read-boundary), zero failures/errors/skips; 77 PostgreSQL cases deselected. Separate parent actual PostgreSQL schema companion: 65 passed, zero failures/errors/skips, disposable database cleanup verified. Frozen eight-file inventory and clean review: .handoff/spec014/us4/t047/{source-sha256.json,settled.xml,pg-companion-fixed.xml,review.handoff.md}. Atomic admission, original safe refusal/retry, physical rollback/CAS/settlement, immutable bindings, masking and first-START assignment activation verified. T048 PostgreSQL adapter, T049 results, service/viewer/actual-host UAT and shipment remain open. Broad unit attempt aborted on an existing GitHub network call; no full-unit GREEN claimed.

### T048 local acceptance — 2026-10-06

T048 PostgreSQL core lifecycle parity accepted after independent fix-round-1 review. Final current-source gate:118 actual PostgreSQL tests passed (32 core/physical including six canonical/mission lock-wait clock regressions,22 schema,14 generic progress,50 reader), zero failures/errors/skips/warnings,107.94s; guarded disposable cleanup verified. Fresh conventions:11 passed. Prior245 offline cases remain separately identified historical verification of unchanged SQLite/domain/port bytes. Review found transaction-start time could admit expired authority/activity after physical lock waits; six behavioral RED became PASS with one repair separating fresh admission clock from transaction metadata/receipt time. Source and receipts: .handoff/spec014/us4/t048/{fix1-source-sha256.json,fix1-final-pg.xml,fix1-review.handoff.md}; original frozen review retained under pre-review/. T050 result storage/racing results, service/viewer/actual-host UAT, full-unit gate and shipment remain open.

### T049 local acceptance — 2026-10-06

T049 SQLite result persistence accepted after independent source/evidence review. Final current-source scoped offline gate416PASS125deselected0FAIL/ERROR/SKIP/warnings16.83s:189domain/port/conventions36unchangedT042SQLite33resultcontrols56lifecycle8genericprogress94SQLiteReader. Separate parent actualPG schema companion66PASS0FAIL/ERROR/SKIP/warnings40.04s (23research schema43progress), guarded cleanupzero. Exact seven-file freeze,27source hashes and full diff verified; T041/T042 unchanged. Atomic handoff/finding/event/receipt, ordered canonical source references, rollback/CAS/history/currentness, safe ACK and completion/masking verified. The two-correction file-CAS architecture checkpoint mapped repeated pre-admission progress DDL; schema-presence/conditional-install repair passed the unchanged reproducer before subsequent work. Optional NULL-time and independent handoff tuple-order schema companions verified. First implementation had no contemporaneous source hash; exact checkpoint/final sources retained. Detached nice(5) launch produced no test proof; final actual supported session settled. Evidence: .handoff/spec014/us4/t049/{source-sha256.json,final-offline.xml,pg-companion.xml,review.handoff.md}. PostgreSQL result/ACK parity remainsT050; service/viewer/host UAT/full-unit/shipment not accepted.

### T050 local acceptance — 2026-10-06

T050 native PostgreSQL result/ACK/completion parity accepted after independent source/evidence review. Separate executed gates:137PGPASS204deselected0FAIL/ERROR/SKIP135.61s (18T04232T04823native14generic50reader),66schemaPASS0FAIL/ERROR/SKIP50.99s,416offlinePASS125deselected0FAIL/ERROR/SKIP22.27s. Later test-only plain-owner evidence closure:updated24nativePG+11conventions35PASS0FAIL/ERROR/SKIP29.69s; product and17other source hashes unchanged. No overlapping total or fresh138 claim. Independent final read-only cleanup verified0disposableDB/0runtime-owner-role. Exact4ownedcopies18sourcehashes40evidencehashes/full patch reviewed. Actual result CAS/wait graph, reached late fault rollback/original retry, ordered immutable source/history/currentness, native result/ACK under NOSUPERUSER/NOBYPASSRLS verified. T042 assertions unchanged; one backend-aware finally guard added. Private snapshot observer kwargs forwarding retains exact one-read/PID/row-lock controls, including nonempty histories. Initial RED was retrospective, cover1 source identity incomplete, setup/selection failures and18 inherited T042 lint diagnostics disclosed; product/new/native lint passes. Evidence .handoff/spec014/us4/t050/{task-report.md,source-sha256.json,final-pg.xml,final-schema.xml,final-offline.xml,final-owner-closure.xml,cleanup.log,review.handoff.md}. Service/MCP/viewer/actual-host UAT/full-unit/shipment remain open.

### T051 local acceptance — 2026-10-06

T051 adds the strict typed recording service without changing the accepted pure parser, domain, port or adapters. Six-field stable assignment identity and expected Manifest/Brief bindings preserve exact retry; no public host authorization/provenance/record time is admitted. Adapter-owned held transactional admission, masking and original receipts remain authoritative; safe failures are ephemeral. Frozen final offline gate396PASS75deselected0FAIL0ERROR0SKIP22.04s (54parser/error,28actualSQLite service,189domain/port/conventions,36T042,56lifecycle,33result) and separate guarded nativePG32PASS64deselected0FAIL0ERROR0SKIP39.51s (14actualservice,18T042) passed without warning summaries. Zero temporary DB/roles independently verified. Exact3owned and18source hashes/copies/full diff match. Genuine bounded parser behavior RED preceded implementation; module collision, overbroad backend spy and socket denial are disclosed setup/instrumentation history. Expanded T052 lifecycle, actual MCP authorization/registration, coherent viewer, hostUAT and broad full-unit remain unaccepted. Evidence: .handoff/spec014/us4/t051/{task-report.md,review.handoff.md,source-sha256.json,evidence-sha256.json,review.diff,final-offline.xml,final-pg.xml,cleanup.log,final-readback.json}. Independent read-only review accepted with no findings; parent verified exact source/evidence identity before commit.

### T052 local acceptance — 2026-10-06

T052 verifies the already implemented public service lifecycle through actual SQLite file/shared-memory and PostgreSQL stores without adding duplicate service admission. Frozen final gates117PASS53deselected13.32s (106newSQLite lifecycle+11conventions),385PASS75deselected17.04s disjoint regression and53PASS106deselected54.18s nativePG all have0FAIL/ERROR/SKIP and no warning summary. Covers cancellation pending versus acknowledged stop, exact own-old epoch/version/fence/execution cessation after terminal/new grant without reviving current authority, all four research terminal dispositions versus five new-admission operations, deadlines, collection COMPLETED with independent grant, first activation once, finite HOST_REPORTED activity and actual unrejected result completion without mandatory ACK. Every exercised product behavior was pre-existing GREEN; setup string-status and test formatting corrections are disclosed, not product RED/fixes. Independent review accepts spec/quality with one deferred minor: strengthen stale-activity response exact disposition/reason assertion at new test lines391–394; final branch review must triage it. Exact25source/14evidence hashes/copy/diff verified; zero disposableDB/runtime-role cleanup. Native host stopped/execution, MCP/viewer, UAT/full-unit/shipment remain unverified. Evidence .handoff/spec014/us4/t052/{task-report.md,review.handoff.md,source-sha256.json,evidence-sha256.json,final-offline.xml,regression.xml,final-pg.xml,cleanup.log,final-readback.json}.

### T053 local acceptance — 2026-10-06

T053 adds the record-only MCP tool with injected Context, actual server/session/stdio owning lifespan eligibility and exact initialized component/repository creation-loop ownership. Unverified transports refuse UNAUTHORIZED_HOST; no public JSON flags, lazy bootstrap, provider/host dispatch or borrowed-owner close. A recording-only pre-handler name/str-dict middleware fixes actual Pydantic input_value privacy leak without changing other tools or signatures. Stable typed service/held adapter guards and original receipts remain authoritative. Frozen final boundary37PASS0FAIL/ERROR/SKIP8.33s; regression506PASS2localhost-setupFAIL30.31s with exact2listener cases separately2PASS1.14s, not a fresh508GREEN run. Minimal failclosed scaffold preceded actual stdio REFUSED-versus-APPLIED RED; functional code followed; original frameworkRED and exact scaffold bytes/chronology retained. Foreign input fixture inconsistency and zsh launch/socket setup failures are disclosed separately. Independent task review accepts without findings;25source hashes/frozen3files/full diff and actual stdio proof verified. Parent canonical contract companion independently reviewed SUPPORTED; its bytes are outside frozen25 inventory and ownedsource remains exact. Actual new MCP proof is stdio/SQLite; PGfullchain, liveHTTP/SSE, viewerintegration, nativehostreasoning/UAT, fullsuite and shipment remain pending. Evidence .handoff/spec014/us4/t053/{task-report.md,review.handoff.md,contract-review.handoff.md,parent-doc-sync.handoff.md,source-sha256.json,final-readback.json,actual-stdio-proof.json,final-command.txt}.

### T054 local acceptance — 2026-10-06

Coherent optional research read/projection independently accepted after one schema compatibility correction. SAME held connection/corpus/high-water decodes explicit mission-current research while selected-run US3 permission remains unchanged; masked finite host activity, exact identities/history/dependency currentness and canonical permitted Claim Ledger narration are exposed, strategic aggregate text withheld. Real SQLite/PostgreSQL reader view/type regressions reproduced 4/2 behavioral failures and then passed; no read DDL/bootstrap or broad canonical-error conversion. Post-fix frozen source: 777 scoped offline, 153 actual PostgreSQL, 66 schema and 34 MCP consumer cases passed separately with zero failure/error/skip. All 19 source/runtime and 25 evidence hashes, nine owned copies and full tracked/new diff verified; final independent cleanup found zero disposable databases/runtime-owner roles. Original pre-fix receipts retained separately. Independent schema-fix and parent relay contract companion reviews supported. File/WAL pinned transaction and private-memory immutable backup races remain distinct. Local branch acceptance only; UI T055, expanded recording-to-viewer T056, actual host UAT T057/T058, T084 installed upgrade and shipment remain unverified. Evidence: .handoff/spec014/us4/t054/{task-report.md,postfix-readback.json,schema-fix-review.handoff.md,parent-contract-review.handoff.md}.

### T055 local acceptance — 2026-10-06

Actual recorded research UI locally accepted after independent spec/quality review with no blocking findings. Dynamic masked assignments/work/handoffs/ACKs and finding history preserve mission-current versus selected-run scope, finite at-read HOST_REPORTED activity, unknown capacity/schema, canonical deduplicated counts and exact upstream narration/withdrawal. UI text enters textContent. The existing browser fixture cursor/inspection identity companion preserves original foreign-response checks. A genuine automatic-refresh focus/open-detail RED was corrected with stable presentation-only keys; no corpus/text/permission cache. Current frozen final scopes:78 browser cases and165 separate convention/read/projection/MCP/HTTP consumer cases passed with zero failure/error/skip. Nine hashes and three owned copies match. Actual SQLite file/private-memory input feeds maintained Chromium through simulated GET; screenshots390/768/1440 and keyboard/reduced-motion are narrow proof, not native all-backend research recording or full accessibility/FPS. T056 native chain, T057/T058 host execution/currentness UAT and shipment remain separate. Evidence: .handoff/spec014/us4/t055/{review.handoff.md,final-browser.xml,final-consumers.xml,source-sha256.json}.

### T056 local acceptance — 2026-10-06

Actual stdio MCP recording/get/open through initialized SQLite file and guarded local PostgreSQL to coherent HTTP and maintained Chromium independently accepted. Six native cases per backend cover lifecycle/finite activity/expiry/old-epoch cessation, original applied/refused receipts, exact scope/widening refusal, current canonical narration and withdrawal/failed-refresh clearing. Final current-source gate:12 native and11 convention cases passed, zero failure/error/skip79.46s. All26 source/runtime and37 evidence hashes and owned copy verified; independent cleanup found zero disposable databases/runtime-owner roles. No product edits. Historical fixture setup failures retained separately; no private-memory native, fresh physical race rerun, host specialist UAT, security/a11y/FPS or shipment claim. Evidence: .handoff/spec014/us4/t056/{task-report.md,review.handoff.md,final.xml,final-readback.json}.

### T057 local acceptance — 2026-10-06

Actual owner-authorized native specialists executed a two-task overlap and separate truly sequential scenario on the declared host. Parent observed both native tasks running; four source-bearing analyst outputs completed. Supplementary actual-clock parallel overlap30s is not sole execution proof. Second sequential dispatch followed observed first completion and actual handoff/ACK. Actual stdio recording/ACK/end and coherent loopback HTTP readback revision21 independently verified four completed work/handoff/finding/ACK records, exact unchanged agent prose/input/source pairs and canonical8/8 counts. All44 frozen source/evidence hashes match. Isolated synthetic corpus only: YouTube NOT_REQUESTED/zero real collection; local fixture membership separate, original eight IDs preserved through backed-up canonical plan setup. No strategic permission or real-market/customer validation. Selected-run US3 frameNULL remains separate from mission-current research frame. No product changes/new suite run; four native executions/readback are this UAT. T058 revision/history/post-read display remains pending. Evidence: .handoff/spec014/research-host-uat.handoff.md and us4/t057/{task-report.md,review.handoff.md,source-evidence-sha256.json}.

### T058 local acceptance — 2026-10-06

Actual native specialist revised the original descriptive finding after the ninth synthetic counterevidence record on a new canonical frame. Exact native-authored source-bound result admitted as revision2/predecessor1 by stdio at26, ACK27/END28; current9/9counts, prior1historical/noncurrent and no strategic permission. Fresh-page actual successful automatic HTTP read high-water28/read_at2026-10-06T07:14:58.483100Z to exact maintained Chromium DOM68.523ms single sample supports literal SC013. Initial baseline8render156.521ms; retained-page120s wait timed out BEFORErevision2recorded and is explicitly not successful mutation/display evidence or behavioral RED. No retained-page continuity, SLA/p95/provider/end-to-end latency claim. Original obsolete APPLIEDreceipt7 replay unchanged all42physicaltable hashes; version2remained current. All39source/evidence hashes plus44priorT057hashes match. Independent task review found no blocking issue. Native controller sessionexit0, ownsocketabsent and capabilityHTTPconnectionrefused;5COMPLETEDwork/3assignments,4unique findings/5revisions; isolated store/recovery retained. Synthetic engineering UAT only, not real-market/customer/source-readiness validation. No product changes/broad suite rerun/main integration/shipment. Evidence: .handoff/spec014/us4.handoff.md and us4/t058/{task-report.md,review.handoff.md,source-evidence-sha256.json}.


### T059 — lifecycle behavioral regression test-design acceptance

Accepted locally as test design; this does not close US2 implementation, integrated T067 or UAT. Eleven new maintained-template browser cases measure native fetch admissions and CSS transform/opacity changes sampled on animation frames, distinguishing sampler callbacks from product motion. Active-packet controls cover motion-only pause with continued authorized refresh, refresh pause, synthetic visibility, inspectable pagehide, finite expiry, and held native-response JSON delivered after suspension. A physical-page-close companion records subsequent request absence. Exact GET/snapshot admission rejects mission mutation attempts; underlying mission execution continuity is not inferred from inert HTTP fixtures.

Current-source browser/conventions gate:75PASS46.46s,0failure/error/skip. Seven isolated rendered-document mutations produced16 intended behavioral AssertionError cases; every control rejected the specific continued motion/read, coupled pause, late UI or mission-write defect. The unmodified product was observed GREEN, not an invented implementation RED. Independent spec/code/security-impact review recorded in `.handoff/spec014/t059/code-review.handoff.md`; evidence, source hashes, commands and verification limits are in `.handoff/spec014/t059/task-report.handoff.md`. No product/template/tool/client/config change. Commit only this accepted task; T060+ remains open and final whole-PR review plus exact-head CI remains required before any merge.

### T060 — accessibility behavioral regression test-design acceptance

Ten installed-Chromium cases cover keyboard-only stage/evidence inspection, painted focus, independent controls, successful refresh focus, reduced-motion movement and unavailable external resources. Scoped final receipt contains9 accessibility PASS and1 genuine behavioral RED, plus11 convention PASS, with no setup error or skip. The RED reaches refreshed exact counts2/1 then loses focus on the selected evidence control; T063 remains open to repair it. No assertion is weakened or expected failure hidden. Initial fixture/assertion setup defects are excluded from behavioral RED evidence.

Nine isolated rendered-document negative modes reject12 intended behavioral AssertionError cases. The resource control is persistent bad count rendering under measured external-resource blocking, not proof of conditional fallback handling. Independent spec/code/security-impact review and exact source/receipt binding are retained in `.handoff/spec014/t060/code-review.handoff.md` and `task-report.handoff.md`. Test-design acceptance is not implementation GREEN, complete WCAG certification, real-mission UAT or shipment. No product changes; T061–T065 and story/full-suite/distribution gates remain open.

### T061 — independent viewer controls implementation acceptance

Existing maintained-template implementation satisfies T061 without product edits: separate motion/refresh state and buttons; motion pause removes moving packets while authorized reads continue; refresh pause stops reads and movement while retaining the recorded snapshot; resuming does not start/cancel/repeat mission work. Fresh installed-Chromium browser/convention gate:75PASS,0FAIL,0ERROR,0SKIP (64 browser plus11 conventions), including applicable T059 assertions measuring fetches, movement, exact counts and receipt identities. Four fresh isolated rendered-document mutations produced4 intended AssertionError failures for surviving/admitted motion, refresh coupling and mission-write attempts.

Independent spec/code/security-impact review accepts the no-product-change outcome. Template/test hashes and exact receipts are retained in `.handoff/spec014/t061/{task-report.handoff.md,code-review.handoff.md,scoped.xml,mutation-results.json}`. This accepts only T061; T060 evidence-focus RED remains for T063. T062+ and whole-story/full-suite/distribution/UAT/shipment gates remain open. No tool/client/config/authority change or push.

### T062 — viewer suspension and late-delivery implementation acceptance

Existing maintained implementation satisfies T062 without product edits: visibility/deadline/closed/refresh-pause guards prevent automatic reads and packet motion; suspension clears timers/packets, aborts reads and increments generations; late native response.json settlement cannot replace suspended UI. Valid resume uses baseline resync and never replays history as fresh intake or invokes mission controls. Fresh task-scoped gate:25PASS,0FAIL,0ERROR,0SKIP,32.688s (14 lifecycle/browser plus11 conventions). Three isolated rendered-document mutation modes reject12 intended behavioral assertions for retained motion, resumed automatic reads and late UI application across four suspension boundaries.

Visibility/pagehide/expiry are controlled synthetic signals/browser-clock advances. A separate actual page.close companion observes no subsequent request over2300ms; removed DOM motion is not measured. Unfrozen late-delivery positive control, exact snapshot counts and read-only resume/no-replay assertions pass. Independent spec/code/security-impact review and immutable source/receipt evidence are retained in `.handoff/spec014/t062/{task-report.handoff.md,code-review.handoff.md,scoped.xml,mutation-results.json}`. This accepts only T062; T063 evidence-focus RED remains. Native host visibility/BFCache, integrated underlying mission continuity (T067), whole-story/full-suite/distribution/UAT/shipment remain unverified. No product/tool/client/config/authority change or push.

### T063 — semantic evidence focus implementation acceptance

Successful refresh now preserves exact keyboard focus on surviving inspector/timeline evidence controls through root-scoped identity restoration at synchronous rerender time. No title fallback, canonical evidence copy, request-start focus cache or focus transfer to another control. Existing semantic stage buttons, visible focus, restrained status announcements and Research summary/expanded-detail preservation remain intact. Retained T060 focus assertion is unchanged. Pre-fix5-case consumer run:3PASS2behavioralFAIL,0ERROR0SKIP; first correction5PASS. Final applicable consumer/convention gate:122PASS,0FAIL,0ERROR,0SKIP,59.97s pytest summary (13accessibility,64browser,20Research-browser,14template,11conventions). Four isolated rendered-document mutation modes reject5 intended assertions for lost focus, newer focus stealing, wrong identity and assertive announcement.

Independent spec/code/security-impact review, immutable source/receipt binding and inspected actual fixture-render screenshot are retained in `.handoff/spec014/t063/{task-report.handoff.md,code-review.handoff.md,scoped.xml,mutation-results.json,evidence-focus-after-refresh.png}`. This closes the local T060 evidence-focus RED, not complete accessibility/WCAG, real mission UAT or shipment. T064+ and whole-story/full-suite/distribution gates remain open. No motion/refresh/suspension/authority/tool/client/config change or push.

### T064 — reduced motion and resource fallback implementation acceptance

Existing maintained implementation satisfies T064 without product edits: reduce disables element/pseudo animation/transitions, rejects new packet motion and clears existing packets while preserving finite authorized refresh and keyboard/static inspection. Local product tokens and font stacks preserve rendering under blocked external font resources. Fresh browser/accessibility/convention gate:88PASS,0FAIL,0ERROR,0SKIP,46.51s pytest summary (46.509s XML;13accessibility,64browser,11conventions), including T063 focus and T061/T062 lifecycle consumers. Four fresh isolated rendered-document modes reject4 intended assertions for packet/pulse/script-camera leakage and corrupt counts under blocked resources; the bad-count control is unconditional and does not prove conditional resource error handling.

Independent spec/code/security-impact review, source/receipt hashes and inspected actual reduced-resource rendering are retained in `.handoff/spec014/t064/{task-report.handoff.md,code-review.handoff.md,scoped.xml,mutation-results.json,fallback-probe.json,reduced-resource-fallback.png}`. Actual font stylesheet request is blocked; document.fonts settles with no registered web font. Reduced-mode probe measures zero running animations/packets, exact2/1refresh facts and exact keyboard inspection identities. Computed preferred font stack is not proof of which OS font rendered. No comprehensive WCAG/native UAT/performance/full-suite/shipment claim. T065+ and story/distribution gates remain open. No product/tool/client/config/authority changes or push.

### T065 — measured responsive layout implementation acceptance

Existing maintained layout satisfies T065 without product edits. Three new canonical-SQLite-backed browser cases stress synthetic long evidence/Research projection content at390/768/1440, use keyboard stage/evidence/detail controls, verify exact identities/counts and individual motion/refresh/pagination visibility, and reject page overflow, internal text/ancestor clipping and inaccessible work. Final consumer/convention gate:125PASS0FAIL0ERROR0SKIP,65.46s pytest summary(65.425s XML). Document widths390/768/1440 match viewports with13Research controls and no clipped essential content. Four isolated rendered-document modes produce12 targeted behavioral AssertionError cases. Setup/API/import failures and stale-receipt attempts are excluded from RED evidence; final negative XML is unique per run.

Independent spec/code/security-impact review, immutable source/receipt hashes, measurements and baseline captures are retained in `.handoff/spec014/t065/{task-report.handoff.md,code-review.handoff.md,source-settled.json,scoped.xml,mutation-results.json,layout-390.json,layout-768.json,layout-1440.json}`. Synthetic stress copies do not claim persisted long prose; GET authority, focus/reduced-motion/lifecycle consumers remain GREEN. Existing FINOLABS tokens and approved mock reference unchanged. T066 visual walkthrough expressly remains open; no pixel/mock parity, full WCAG/native UAT/full-suite/performance/shipment claim. No product/tool/client/config/authority change or push.


### T066 — approved rendered visual correction acceptance

PO accepted the bounded restored direction after independently inspecting final 390/768/1440 overview and controlled-motion pixels against the approved mock: compact persistent authority header, dominant connected research network, adjacent desktop Synthesis context and compact event strip. Canonical source/work/finding identities, missingness, read-only authority, exact recorded input links and explicitly labeled method paths remain intact. Reviewed template SHA256 a1a6cb460f0228547b227dfaf1d623b96f691e36a6614cabeb2ce7a56e8a0671 and visual-test SHA256 42a0e58e55101431cb9954e0d1f7dc20503bf3ca136439db56acf4dfcaf86d4c are unchanged at settlement.

Final consumer/convention gate:137PASS0FAIL0ERROR0SKIP,93.557s XML; separate rendered walkthrough:3PASS0FAIL0ERROR0SKIP,13.427s XML; controlled local-font probe:1PASS. Four negative controls reject exactly3/3/1/1 intended assertions with zero setup errors/skips. Independent final code/security-impact reviews report no actionable remaining findings. Evidence and immutable bindings are retained in `.handoff/spec014/visual-uat.handoff.md` and `t066/correction/source-settled.json`. Earlier capture-only refusal is historical and superseded by owner-authorized correction and explicit PO acceptance.

Acceptance is local engineering visual acceptance of the approved direction, not pixel parity, actual brand-font delivery, real-market/native UAT, complete WCAG, full-suite/minimum-runtime verification or shipment. Motion receipts are explicitly synthetic; no illustrative mock metrics become evidence. T067–T092 remain open; T087 and final whole-PR/CI/integration gates remain required. No push/merge/release/deploy/version/protection or TypeSafe transmission.


### T067 — integrated viewer lifecycle boundary acceptance

PO accepted local T067 for the declared bounded engineering hosts at verified source revision1a803d8e6c9d9d68d5574feda13bc056a5aa33d0. Four actual native stdio/SQLite/HTTP/Chromium151 scenarios verify motion pause preserves authorized reads, while refresh pause, physical close and finite expiry admit zero new viewer reads. Supported consumer/convention gate:92PASS0FAIL0ERROR0SKIP87.125s XML. Separately labeled controlled active-packet regression supplies a motion positive; native research-only animation is inactive.

The missing actual hidden gate is now independently verified on installed Chrome154.0.8037.98 in a fresh isolated temporary profile, localhost CDP no_defaults=True and dedicated default context. Native document state transitions visible→hidden→still-hidden through admitted host handoff→visible, without getter/event overrides, renderer freeze or CSP weakening. Final hidden gate:1PASS0FAIL0ERROR0SKIP10.169s XML. Viewer snapshot requests1→1 and actual reader method admissions5→5 during the hidden interval; independent assigned host computation0→5window→6final and public MCP handoffRUNNINGv2→HANDOFF_READYv3. The sixth full-list reader entry is explicit post-window verification. Exact source/work/handoff identities and SQLite recovery integrity/bindings were verified read-only.

Independent code/security-impact re-reviews support exact final probe/host receipts, with cleanup finding resolved and re-reviewed. Evidence is bound in `.handoff/spec014/us2.handoff.md`, `t067/source-settled.json` and `t067/host-investigation/source-settled.json`; failed historical evidence remains unchanged in `t067/partial-frozen/`. No product/test edits were required. Local acceptance covers deterministic synthetic engineering host execution and method-entry admission counters, not transaction telemetry, injected cleanup-failure proof, real-market/native assistive-technology/full-suite/performance or shipment. T068–T092, minimum-supported T087 and whole-final-revision review/fresh CI/integration gates remain open. No TypeSafe transmission, push/merge/release/deploy/version/protection/client/global configuration change.


### T068 — historical test-design acceptance and T074 runtime verification

At the historical T068 checkpoint, PO accepted bounded test design only at source SHA256 abf412fbe065e87bf9b49eb0e4e6b72f7d20fa6c74b1e09aa69149ddb5ea176d against base ebfae23136553c979aaac8c07197df603f1c0c70. Independent final code/security-impact reviews accept the same source; initial auth-counter, race-after-admission, terminal-state and quota-masked cost findings were corrected and re-reviewed. Direct physical child/manifest/reservation identity readback and recorded query/cost scope including actual Brief falsifiers were also reviewed. At that checkpoint, public execution retained exactly four approved arguments; internal recording/load/DI seams and exact reason tokens were proposed for T070–T075, not implemented contracts at that time.

Evidence:83 cases collected;14 defective assertion controls rejected;11 convention cases passed with54 missing-API failures and29 missing-DSN PostgreSQL skips,8.29s. Separate authority companion:20PASS0FAIL0ERROR0SKIP,0.10s; Ruff and new-file whitespace check passed. Refusal assertions require exact reasons, zero independent session initialization/probes/child execution and unchanged physical state. Same/different-key duplicate and common-gate/two-connection admission plus held-probe replay assertions require one canonical child/reservation. Interrupted execution preserves unresolved identity/budget and checks quota-only/cost-only refusal independently. Parent COMPLETED remains terminal.

That historical acceptance did not establish behavioral RED: all54 failures identified the then-unavailable follow-up API before admission setup.29 missing-DSN skips did not establish PostgreSQL parity. Simultaneous dispatch is not executed transaction contention; BaseException interruption is not an OS crash/reopen experiment; physical identity readback does not prove physical reservation cost/state. The historical unfrozen broad attempt reported282FAIL3236PASS918SKIP45ERROR2warnings,292.15s, including sandbox/browser/dependency failures; it is not final-revision GREEN. No runtime authorization/admission/atomicity/recovery, integration or shipment acceptance.

Final source/review/receipts and settlement are retained in `.handoff/spec014/t068/{review-ready.handoff.md,code-review.handoff.md,security-review.handoff.md,hashes.txt,source-settled.json}`. Ledger68/92; T069–T092 remain open. No T069/runtime/domain/schema/MCP work, new TypeSafe payload, push/merge/deploy/release/version or owner-file change. Commit covers only the owned test and this ledger; subsequent work awaits PO dispatch.


Current runtime verification through accepted T074 supersedes the historical API-absence limitation above: final source-bound T06855 offline and29 PostgreSQL cases passed, zero failure/error/skip, with all18 exact refusal controls and physical child/reservation/journal/original-retry/held-probe race/one-ingress assertions preserved. Canonical typed facts replace provisional setup seams without a production dictionary authority shim. The historical READ-only negative restores exact SQL028 CHECK/trigger enforcement; prior teardown failure remains retained as a failed gate. Current evidence: `.handoff/spec014/t074/{fixture-final.handoff.md,fixture-frozen-offline.xml,fixture-frozen-postgres.xml,po-acceptance.handoff.json}`. Runtime acceptance remains synthetic and bounded; no real provider/session, T075 measured reconciliation, related-view runtime or US5/shipment acceptance is implied.


### T069 — child-frame isolation test-design acceptance

PO accepted bounded test design at final source SHA256 d3aa2821e8fb6d2066859a899ad2eced1e5e5d8b92691a49cf98e2c82d702187 against base41410b551bed7bfa48e89350cfb0db9ba4dfb3a9. Both independent final code/security-impact reviews accept this exact source. Current canonical parent/child/foreign fixtures have distinct frame/run/observation/claim identities and one shared source at distinct observation times. Parent-to-child and child-to-parent permission borrowing, foreign observation inspection and implicit composite membership/permission are separately negated. Child selection retains its canonical frame, counts and exact claim/finding bindings; labeled related summaries never grant detail or execution authority. Successful and refused inspections are included in zero executor/connector/credential counters and physical-state preservation assertions.

Final receipts:30 cases collected;17 corrupt assertion controls rejected in1 aggregate passing test,1.60s;18 missing-API failures,13 passes and10 PostgreSQL skips,8.46s.13 passes comprise2 existing canonical fixture controls and11 convention cases. Separate existing gate/projection/research consumer regression:128PASS15SKIP,5.89s. Ruff and new-file whitespace check pass. Future owner-recorded result-link and related-result projection seams remain proposed; no passing follow-up implementation was injected.

Acceptance is test design only. Missing API is not behavioral RED; direct selected-reader membership tests assume upstream authorized child selection, not HTTP/host capability security. Credential lookup traps do not cover every future session initializer; physical-state equality is not proof of no transient rolled-back SQL. No related-view runtime, PostgreSQL parity, native UI, full-suite/minimum-runtime, integration or shipment acceptance. An initial claim/finding binding fixture error was corrected from the authoritative projector contract; it is not product RED and no contemporaneous frozen initial-source receipt is claimed.

Final source, six contract/consumer/ledger bindings, reviews, commands/receipts and limits are retained in `.handoff/spec014/t069/{review-ready.handoff.md,code-review.handoff.md,security-review.handoff.md,source-settled.json,hashes.txt}`. Ledger69/92; T070–T092 remain open. Commit covers only the owned test and this ledger. Prior accepted T068 source and unrelated owner dirt are preserved. No runtime/schema/model/template/MCP change, T070 start, push/merge/release/deploy/version/protection/global configuration or new TypeSafe payload. Subsequent work awaits PO dispatch.

### T070 bounded domain/port acceptance — 2026-10-08

Owner approved local commit and T071 progression directly. Typed follow-up relationship,
reservation and child-only result models plus the separate additive IResearchFollowUpPort
preserve existing consumers and the exactly-four-field public execution DTO. Independent code
and security reviews accepted the final five-file candidate after correcting the mission-bound
child Brief fingerprint. Fresh scoped199PASS,0FAIL/ERROR/SKIP; seven corruption controls reject
12bad assertions; Ruff and diff check passed. Reviews and hashes in
`.handoff/spec014/t070/`. T068/T069 test sources remain unchanged.
Unknown/partial usage retains allocation; final settlement depends on future store-verified
measurement and writer closure. No storage/admission/executor/viewer/MCP implementation,
PostgreSQL parity, final full-suite/CI, integration or shipment acceptance.
T071–T092 remain open. Commit covers only the five reviewed files and this ledger.

### T071 additive schema acceptance — 2026-10-09

PO accepted six frozen schema/test/doc/spec paths after independent code and security reviews. Expanded migration/security gate:105PASS1 intentional SQLite PG-role skip,219.01s. Fresh current-port SQLite/PostgreSQL schema plus convention gate:66PASS1 same intentional skip,43.607s; these overlap and are not added together. PostgreSQL16.14 dedicated loopback container identity verified; stale ignored test port reconciled without changing the server or credentials. Fresh cleanup confirms zero disposable databases and zero test roles. Canonical row counts/digests, isolated uniqueness, reciprocal reservation FK, immutable history/usage and actual client privilege refusals verified. Ruff/diff checks passed. Evidence and thirteen reviewed bindings: `.handoff/spec014/t071/`. Schema only; no admission/executor/viewer/real-UAT or shipment acceptance. T072–T092 remain open. Unrelated owner edits preserved.

### T072 SQLite admission acceptance — 2026-10-09

Delegated PO accepted the NULL-corrected eleven-path candidate at inventory98cfe2e5018b159ed77663b13dec1f510ab0c95a60b6f32c4911026524eec174 after final independent code/security reviews. Fresh final offline300PASS73deselected0FAIL/ERROR/SKIP34.51s; independent PO81PASS30deselected0FAIL/ERROR/SKIP18.33s overlaps and is not added. Physical races, rollback, current guarded authority, exact original retry recovery, all-epoch conservative scalar/resource budgets and parent/evidence preservation verified. All nine new PK components refuse NULL; fresh NOT NULL and reapply INSERT guards preserve unresolved legacy rows without rewriting. Prior insufficient ownership corrections stopped at an independently reviewed architecture checkpoint; failed controls/receipts retained. PostgreSQL030 schema/RLS27PASS and typed fixture11PASS are separately scoped prerequisites, not runtime parity. Cleanup verified zero disposable DBs/roles. Current source/review/PO evidence in `.handoff/spec014/t072/`. No real capability provider/session, executor, PostgreSQL admission, UAT, CI/minimum-Python, integration or shipment acceptance. T073–T092 remain open; commit includes only accepted eleven paths and this ledger.


### T073 accepted native PostgreSQL admission

Delegated PO accepted inventory f3fdbeaf055e33ff0bdcc9c615647ccbba2c006a418377f43b24b944e65a3daf (seven candidate paths) after independent final code/security reviews and exact source-hash checks. Native admission16PASS, existing PostgreSQL consumer5PASS, shared SQLite regression300PASS, all zero failure/error/skip; overlapping PO16PASS PostgreSQL and81PASS SQLite/schema/convention are not added. Fresh post-PO cleanup confirms zero disposable databases/roles. Actual distinct-connection contention, immutable retry recovery, guarded generation publication, cancellation settlement, expiry/write rollback, all-epoch scalar/resource conservation and physical-history corruption controls verified. PostgreSQL uses native async transactions; shared pure predicates preserve SQLite parity. Missing real async provider refuses. Evidence: `.handoff/spec014/t073/` including `po-acceptance.handoff.json`. No real session, collection/executor, minimum-Python/full-suite, US5 UAT, integration or shipment acceptance; T074–T092 remain open.


### T074 accepted bounded deterministic child execution — 2026-10-09

Delegated PO accepted the fifteen-path candidate at inventory 51baf93275f3836887bb7c3ab2347a89a686162314c071d7e6323ca6b9acb2f2 against base 111f2affdd2390fffce152a4786ffc5a4b1eaee1 after whole-candidate independent code and bounded security reviews. Actual current scoped gates: 25 focused executor/workspace, 55 T068 offline, 29 T068 PostgreSQL, 4 native PostgreSQL workspace, 439 existing consumers and 11 conventions, all zero failure/error/skip. Independent PO 91 offline cases passed with 33 PG cases deselected, zero failure/error/skip; these overlap and are not added. Fresh post-PO read-only cleanup at 2026-10-09T09:47:14.898270+00:00 verified zero temporary databases/roles. All fifteen current hashes matched; unchanged SQL028/029/030 support was separately verified.

Canonical typed current authority and exact deterministic plan checks precede credential lookup/ingress. Actual child writer and durable canonical journal prevent repeated dispatch across keys, competing connections, cancellation and reopen; settlement-owned setup cleanup preserves exact ownership despite lost acknowledgement or finalization failure. Interrupted child allocation remains conservative UNRESOLVED with original amounts/resources/receipts retained; parent terminal state and evidence remain unchanged. Original 18 negative controls and physical one-child/one-reservation/one-ingress assertions are verified. Initialization self-lock, credential ordering, retry identity, ownership cleanup, resource-proof/interruption and historical READ restoration defects have retained reproductions and passing scoped controls. Ambient SOCKS failures were resolved only in the test process environment; failed historical gates are not relabeled green.

Evidence and exact commands/native exits, source/review bindings and PO decision: `.handoff/spec014/t074/{review-ready.handoff.md,final-source.json,code-review.handoff.md,security-review.handoff.md,consumer-isolated-native-receipt.handoff.md,workspace-postgres-final-receipt.json,po-acceptance.handoff.json,po-cleanup-final.handoff.json}`. T068 is now runtime-verified in this scope; T069 remains test-design acceptance only. Synthetic trusted verifier/ingress only; absent real provider refuses. No measured settlement/reconciliation T075, MCP T076, child viewer T077/T078, real UAT, minimum-Python/full-suite/CI, integration, US5 completion or shipment acceptance. Already-started opaque plugin work may finish after expiry; no internal HTTP fencing or prompt cancellation guarantee. T075–T092 remain open. Unrelated owner edits preserved; commit covers only accepted fifteen paths plus this ledger and is owned by the parent.

### T075 accepted conservative reconciliation — 2026-10-09

Delegated PO accepted seven-path inventory38ccfafc1b5a18b3d6c6d1cb812ce20c5b7f4e4b1e7ce425032158e793b671e3 after independent current-source code/security reviews and direct receipt verification. Final serial gates:245 offlinePASS and63 actualPostgreSQLPASS, zero failure/error/skip; portable normal/alternate crash controls each1PASS overlap those gates and are not added. Owned job PID/PGID receipts confirm exit0/reaped; interrupted prior failures remain retained.

Canonical coherent child/journal/writer history controls terminal classification; naive/mixed timestamps refuse without rewriting history. Admitted late failures retain original relationship/run, while conflicting changed-epoch retries disclose no prior identity. Cancellation/crash, unknown usage and unsupported legacy SETTLED keep original allocations and never fund a new probe or sibling. No authentic complete usage producer or measured SETTLED/release claim is introduced.

PO cleanup disposition preserves the interrupted database and anon/authenticated shared roles with unproven ownership. Fresh read-only evidence confirms zero NEW test databases and zero client sessions; one retained database scheduler remains. This is bounded owned-job cleanup, not total-zero cluster cleanup, and is not a T075 behavior blocker. Evidence: `.handoff/spec014/t075/{review-ready.handoff.md,resumed-source.json,resumed-settlement.json,code-review.handoff.md,security-review.handoff.md,resumed-cleanup.json,resumed-role-state.json,po-acceptance.handoff.json}`. Python3.14.8 scoped verification only; no full suite/minimum-Python/CI/live provider/UAT/integration/shipment acceptance. Ledger75/92; T076–T092 open. Commit covers the seven accepted paths plus this ledger; unrelated owner work is preserved.

### T076 accepted bounded MCP follow-up — 2026-10-09

Delegated PO accepted the nineteen-path candidate at inventory534970bfbd1ea9ffe722047088c13af17756c42386a64cd567dbd2cc75b0a2d6 against base6a06616e7f60a247e248e6d26b9819f392ab6a69 after independent final code/security reviews and all actual source-hash checks. Final serial gates:262 scoped offlinePASS and19 native PostgreSQLPASS, zero failure/error/skip; earlier focused runs overlap and are not added. Owned finite job groups reaped exit0, all task job receipts settled. Actual stdio delegates accepted child execution through four public arguments, separate held source/session capability and borrowed owner resources. Argument/scope/epoch/provider refusals precede auth/collection, immutable admitted identity and original/alias recovery retain one ingress, actual owned cancellation settles journal/writer without releasing unknown spend. Canonical synthetic fixture identity correction preserves exact plan digest rather than weakening permission. Public catalog48 and current migration030 consumers are synchronized; historical counts remain dated.

Fresh attributed cleanup preserves the PO-approved old database and shared restricted roles, with zero NEW databases/roles/client sessions; baseline scheduler remains. Evidence: `.handoff/spec014/t076/{review-ready.handoff.md,final-source.json,final-settlement.json,owned-jobs-settled.json,code-review.handoff.md,security-review.handoff.md,database-baseline.json,cleanup-final.json,po-acceptance.handoff.json}`. Synthetic private capability/offline ingress only; no actual provider/UAT, measured SETTLED/release, full suite/minimum-Python/CI/build/integration/shipment claim. Ledger76/92; T077–T092 open. Commit includes only nineteen accepted paths plus this ledger; AGENTS.md stages only the task-owned47→48 amendment, preserving pre-existing owner edits.


### T077 accepted scoped child-result projection — 2026-10-10

Delegated PO accepted twelve changed paths at final inventory5b90e7b4609e8d964f94ca920f49d053f15088ae769c96ee1aceef84e8fbc573 (one unchanged follow-up contract context anchor) against base51d3d21de492d3b37d4fc0cefa6c5126d0566892. Exact current-source independent code/security reviews have no remaining actionable findings. Final serial gates:432 offline and82 actual PostgreSQL PASS, zero failure/error/skip; focused historical runs overlap and are not added. All thirteen owned jobs reaped; source unchanged through final gates. Original admitted relation proof applies at every event head, exact recorded finding scope remains separate from current child permission, and receipt-only contiguous revisions use explicit resync without fabricated events. Partial optional schema preserves valid canonical reads with unknown coverage; missing required eventless proof and corrupt receipts refuse. T069 is now runtime-verified in this bounded scope.

Fresh cleanup preserves the approved old database, restricted shared roles and scheduler, with zero NEW databases/roles/client sessions. Evidence: `.handoff/spec014/t077/{review-ready.handoff.md,final-source.json,final-settlement.json,code-review.handoff.md,security-review.handoff.md,cleanup-final.json,po-acceptance.handoff.json}`. Synthetic provider fixtures only; no real-provider/native GUI UAT/full suite/minimum Python/CI/build/integration/shipment claim. Ledger77/92; T078–T092 open. Commit covers only twelve accepted changed paths plus this ledger; owner AGENTS and unrelated files remain preserved.


### T078 accepted recorded child-reference viewer — 2026-10-10

Delegated PO accepted three frozen paths at inventory04b069ffe16af63bc7640749437d9f2be093d619c33e60aec1135037e7ba535a against base65d6e1c99e60279be37d1c123166a6df07ee7244 after exact-source code/security reviews with no remaining actionable findings. Final serial gates:93 isolated Chromium cases and336 read/UI consumer cases PASS, zero failure/error/skip;10 PostgreSQL cases deselected. Source unchanged through gates; all six owned jobs reaped. Failed fixture and accessible-name locator receipts remain retained separately. Viewer renders historical child scope and exact finding revisions as inert references alongside the existing selected-parent Gap Report; unknown scope/coverage, malformed refresh and stale withdrawal remain explicit. Child inspection requires an independently selected scope; no parent-to-child capability, execution or navigation grant.

Fresh cleanup preserves approved old database/shared restricted roles/scheduler with zero NEW databases/roles/client sessions. Evidence: `.handoff/spec014/t078/{review-ready.handoff.md,final-source.json,final-settlement.json,code-review.handoff.md,security-review.handoff.md,inspection-checkpoint.handoff.md,cleanup-final.json,po-acceptance.handoff.json}`. Maintained DOM uses typed synthetic payload and inert scoped GET transport, not real-provider/native client UAT. No full suite/minimum Python/CI/build/integration/shipment claim. Ledger78/92; T079–T092 open. Commit covers only three accepted paths plus this ledger; owner AGENTS and unrelated work preserved. T079 dispatch is read-only prerequisite preflight only.


### T080 bounded backend-parity increment — partial acceptance (2026-10-10)

PO accepted the test-only expansion of three public MCP controls: pre-admission refusal, missing independent execution provider, and owned caller-cancellation/lifespan-close settlement. Actual scoped runs passed four PostgreSQL and four SQLite cases with zero failures, errors or skips; backend-excluded cases were deselected. Frozen source was unchanged across both backends, and independent code/security review found no actionable issues. These controls use synthetic authority and do not establish real-mission UAT or acceptance of every follow-up/lifecycle negative.

Evidence: `.handoff/spec014/t080/{public-pg-pilot.xml,public-pg-variants.xml,public-file.xml,final-settlement.json,sqlite-settlement.json,final-review.handoff.md,po-bounded-acceptance.handoff.json}`. The initial SQLite configuration-import failure executed no behavioral cases; its receipt is retained as `public-file-setup-failure.json` and was resolved in the ignored isolated runner. All owned process groups were reaped. PostgreSQL cleanup evidence remains the observation at `2026-10-10T04:14:49.641951+00:00`: zero new databases/roles/client sessions with the approved old baseline preserved; the SQLite companion performed no PostgreSQL operation and does not refresh that observation.

T079 real authorized mission/provider trace and remaining T080 lifecycle acceptance stay open. T079 and T080 remain unchecked, ledger remains 78/92, and US5 remains incomplete. No full-suite, CI, shipment or real credential/quota/API validation is claimed. Commit only the bounded test change and this partial-acceptance note; preserve unrelated owner work.


### T080 executor parity increment — partial acceptance (2026-10-10)

PO accepted the test-only executor parity increment. Actual PostgreSQL missing-provider pilot and false-proof/metadata group passed 1+5 cases; affected SQLite controls passed 6 cases. All selected cases had zero failures/errors/skips; backend-excluded cases were deselected. Eight frozen source/consumer hashes remained unchanged, all three finite90s owned process groups exited0 and were reaped, and independent code/security source review plus actual receipt review found no actionable issues.

Missing/false proof controls enter the full executor and assert exact refusal before credential-runtime resolution, zero health/auth/search calls and unchanged complete physical state. Tier/revision/paid/sampling drift controls enter the guarded registry against a persisted approved plan; synthetic runtime resolution occurs once before exact metadata rejection with zero health/auth/search and unchanged state. This is registry-boundary parity, not full-executor late-drift or real-provider UAT.

Evidence: `.handoff/spec014/t080/executor-parity/{pilot.xml,postgres.xml,sqlite.xml,frozen-source.json,runtime-settlement.json,source-review.handoff.md,runtime-review.handoff.md,po-bounded-acceptance.handoff.json}`. Fresh PostgreSQL cleanup observed `2026-10-10T06:05:27.018365+00:00` preserved the approved pre-existing baseline with zero new databases/roles/client sessions. SQLite performed no PostgreSQL operation. T079 actual authorized mission/provider trace, native PostgreSQL process-death/reopen recovery and complete T080/US5 acceptance remain pending. T079/T080 remain unchecked; ledger78/92. No real credential/session/quota/API, broader-suite, CI, release or shipment acceptance is claimed.


### T080 native PostgreSQL process-death increment — partial acceptance (2026-10-10)

PO accepted the test-only pre-ingress native PostgreSQL process-death/reopen control. Actual single pilot passed with zero failures/errors/skips; all seven frozen source/consumer bindings remained unchanged. Parent independently verified persisted child/reservation, STARTED journal, held writer and exact resource allocations before terminating only the newly test-owned child process group. Child PID/PGID5543 exited-9 (SIGKILL) and was reaped; finite90s outer PID/PGID5540 exited0 and was reaped. Independent source code/security and runtime receipt reviews found no actionable findings.

Fresh native reopen original/alias recovery retained original child/run/reservation, STARTED journal and writer, parent terminal state/evidence and unchanged resource/scalar allocation. Reservation remained conservative UNRESOLVED with encumbered(2,2), no measurement receipt or known spend; fresh auth/probe counts were zero. This accepted boundary is process death before ingress, not mid-probe crash settlement, writer reclamation, measured budget release or real-provider UAT. Existing SQLite controls and product code remained unchanged.

Evidence: `.handoff/spec014/t080/process-death/{frozen-source.json,pilot.xml,pilot-owner.json,child-owner.json,durable-marker.json,runtime-settlement.json,source-review.handoff.md,runtime-review.handoff.md,po-bounded-acceptance.handoff.json}`. Fresh PostgreSQL cleanup observed `2026-10-10T06:20:24.931358+00:00` retained the approved pre-existing baseline with zero new databases/roles/client sessions. All owned processes were reaped and the shared slot released. T079/T080 remain unchecked, ledger78/92, US5 incomplete; actual authorized mission/provider/revised-synthesis trace and remaining complete acceptance stay pending. No broader-suite, CI, release or shipment claim.


### T080 execution acquisition parity increment — partial acceptance (2026-10-10)

PO accepted the test-only parity controls for cancellation during hold_execution acquisition, incomplete execution resource proof and unavailable execution provider/guard. Actual native PostgreSQL pilot and companions passed1+3 cases; affected SQLite controls passed4 cases, zero failures/errors/skips across selected cases. Backend-excluded cases were deselected. Nine source/contract bindings remained unchanged; independent source/code/security-impact and runtime evidence reviews found no actionable issues. All three serial finite90s owners exited0 and were reaped.

These full-executor controls assert unchanged complete physical state/follow-up inventory, no held token leak and zero runtime-resolution/health/auth/search before admission. They cover hold_execution acquisition rather than earlier hold_current admission or later workspace journal/claim cancellation. Capability failures are synthetic offline negatives, not real source permission or UAT.

Evidence: `.handoff/spec014/t080/acquisition-parity/{source-before.json,pilot.xml,postgres.xml,sqlite.xml,runtime-settlement.json,source-review.handoff.md,runtime-review.handoff.md,po-bounded-acceptance.handoff.json}`. Fresh PostgreSQL cleanup observed `2026-10-10T06:32:32.229818+00:00` preserved approved baseline residue/shared roles with zero new databases/roles/client sessions. No PostgreSQL operation occurred in the file companion; all owned jobs settled and slot released. T079/T080 remain unchecked, ledger78/92, US5 incomplete. Complete negative coverage disposition and T079 real authorized mission/provider/revised-synthesis trace stay separate. No broader-suite, CI, release or shipment claim.


### T080 final both-backend negative acceptance (2026-10-10)

PO accepted the consolidated local follow-up/terminal authority-negative coverage: compatible previously reviewed invariants plus the final exact-phase controls. `test_cancelled_journal_setup_settles_before_execution_token_release` and `test_missing_actual_child_brief_refuses_before_journal_and_ingress` passed exactly two native PostgreSQL and two SQLite-file cases, zero failures/errors/skips. Journal cancellation retains bounded owned settlement, held execution token until settlement, FAILED journal/no writer, UNRESOLVED original allocation/recovery and terminal-parent preservation. Missing child Brief retains exact REFUSED/SCOPE_MISMATCH and no journal/ingress. Nine source/consumer bindings remained unchanged during execution; independent source/security-impact and runtime receipt reviews found no actionable mismatch. Counts from prior gates overlap and are not added.

Evidence: `.handoff/spec014/t080/final-phase-parity/{postgres.xml,sqlite.xml,source-before.json,runtime-settlement.json,source-review.handoff.md,runtime-review.handoff.md,po-acceptance.handoff.json}` and consolidated `.handoff/spec014/us5.handoff.md`. Both finite 90-second owned groups exited zero and were reaped. Fresh cleanup observed `2026-10-10T06:49:12.077256+00:00`: zero NEW databases/roles/client sessions, approved retained baseline preserved. Earlier partial-acceptance notes remain historical; this disposition supersedes their T080-pending status.

T080 checked; ledger79/92 (T001–T078 plus T080). T079 remains unchecked and US5 INCOMPLETE: actual authorized mission/provider/source/session trace, child qualification and revised synthesis remain separate. Synthetic engineering acceptance grants no real credential/session/quota authority and establishes no full suite, CI, shipment, mid-probe crash or authentic measured settlement/release claim. Commit only the two accepted paths; preserve unrelated owner work.


### T079 private provider bridge — bounded offline engineering acceptance (2026-10-10)

PO accepted an opt-in private bridge composed with the host's existing owner verifier and held revocable capability lease; it creates no capability proof or default activation. Exact owner-confirmed mission/work/epoch/frame/source/plan and run bounds fence credential ingress. Shared conservative process-run accounting caps search/readiness/metrics/retry calls without refunding uncertain attempts, clamps video sampling, and checks actual geo/language/run-start window before provider dispatch. Private YouTube client/clock seams retain public signatures and default behavior. Header and streamed body consumption remain inside remaining run/lease authority; cancellation settles and closes streams, and private credential-bearing requests are scrubbed before outer HTTP diagnostics.

Final scoped offline verification: `scope-final.xml`88PASS0FAIL/ERROR/SKIP (36 bridge,41 existing YouTube,11 conventions), fake credentials and stub transport only. Owned 90-second group PID/PGID47868 exited zero and was reaped. Independent source/code-security review resolved credential exposure, header/body deadline and actual request-scope findings; behavioral REDs and earlier failed receipts remain historical. Exact source/review/receipt bindings and PO disposition: `.handoff/spec014/t079/offline-bridge/{scope-ready.handoff.md,scope-review.handoff.md,scope-final.xml,scope-final-owner.json,po-offline-acceptance.handoff.json}`. No repeated unchanged tests are claimed for ledger/commit settlement.

This accepts the bounded offline bridge increment only. Seven-day purge/storage/cache deletion, durable accounting recovery, actual trusted host/key binding, full persisted parent→gap→child qualification/revised synthesis and real UAT are not implemented or verified by this increment. Retention refusal/expiry/close hooks require host lifecycle handling; they do not establish deletion or complete enforcement of all mission caps. No real activation, grant, secret lookup, provider/network call, paid spend, full-suite/CI or shipment claim. T079 remains unchecked, T080 checked, ledger79/92 and US5 INCOMPLETE.

### T079 durable accounting and enrolled retention — bounded offline acceptance (2026-10-10)

Persist immutable run bounds and monotonic shared call accounting before credential resolution/provider dispatch; reopen refuses missing, changed or closed history without resetting spend. Private run-owned cache and registered artifact purge preserves minimal audit/counter tombstones and unrelated files. Artifact ownership enrollment commits before file creation; deterministic full-write interruption controls verify subsequent reopened expiry purge, while initial enrollment failure creates no payload.

The enrollment control produced three behavioral failures before one correction; the final narrow bridge/YouTube/quota/convention gate passed 105 tests with zero failures/errors/skips. The finite 90-second runner exited zero and was reaped. Independent bounded code/security review found no actionable defect for the measured scope; ten source/consumer hashes match the final receipt. Evidence: `.handoff/spec014/t079/durable-retention/enrollment-repair/{ready.handoff.md,red.xml,green.xml,green-owner.json,final-source.json,review.handoff.md,po-offline-acceptance.handoff.json}`.

This supersedes the prior increment's accounting/private enrolled-purge implementation gaps only. Purge remains host-invoked; host-off automatic cleanup, canonical retention enrollment, actual process-kill/partial-write cleanup and contention are not established. Trusted live host/key binding, the authorized YouTube-only mission trace, child qualification and revised synthesis remain open. Unavailable other sources are not an acceptance gate for that mission. T079 remains unchecked, T080 accepted, ledger79/92 and US5 INCOMPLETE; no live activation, full-suite/CI or shipment claim.

### T079 host activation — bounded offline engineering acceptance (2026-10-10)

Implement a private root-owned revocable controller with exact owner scope, canonical plan/frame bindings, live registry checks and durable accounting authorization. Persisted constraints do not restore allowed leases after restart. Enroll a separately owned isolated canonical SQLite store for explicit expiry deletion; preserve immutable ownership receipts and atomically publish deletion-only recovery dispositions without restoring writers or source authority.

Independent code/security review identified synchronous commit/revocation publication and failed-purge recovery defects. Deterministic controls reproduced them; the final bounded activation/bridge/convention gate passed 67 tests with zero failures/errors/skips, finite 90-second owner exit zero and reaped. The recovery checkpoint and second correction preserve original receipt bytes under write/fsync errors, retry exact owned deletion and recover completion-audit failure after unlink. Independent repair review found no actionable issue in the frozen closure. Evidence: `.handoff/spec014/t079/secure-activation/{po-engineering-acceptance.handoff.json,repair/second-ready.handoff.md,repair/second-final.xml,repair/second-final-owner.json,repair/second-source-final.json,repair/second-review.handoff.md}`.

This accepts engineering only. The local driver is source-only; real provider/key readiness, confirmed compatible Market Brief, canonical creation/assignment runtime, native integration and actual parent-gap-child qualification/revised synthesis remain unverified. Canonical IDs are host-generated state, not owner-supplied prerequisites. No actual crash/filesystem-race or host-off automatic purge claim. T079 remains unchecked, T080 accepted, ledger79/92 and US5 INCOMPLETE. No live activation, full-suite/CI or shipment acceptance.

### T079 root composition and startup retention recovery — partial offline engineering acceptance (2026-10-10)

The delegated PO accepted the exact seven-path candidate bound by `.handoff/spec014/t079/secure-activation/consolidated-readiness/startup-repair/source-final.json`. Private root composition now bootstraps the confirmed parent into isolated canonical SQLite, preserves the faithful tutorial Brief and bounded parent query, and registers generated workspace metadata for ownership-checked expiry cleanup. A typed sealed-startup failure retains the original closed, expiry-only recovery disposition; deletion retries preserve original identity and do not restore a writer or source authority. Recovery remains process-local, not serialized restart or host-off cleanup.

Final affected verification: **60 PASS, zero failures/errors/skips/deselections**, XML13.787s; finite90s owner PID/PGID53626 exited0 and was reaped, with all owned runner PIDs absent at settlement. Independent whole-candidate code/security review found no actionable issue and verified101 matching hashes. Evidence: `startup-repair/{corrected.xml,corrected-owner.json,settled-all-owned-process.txt,source-final.json,review.handoff.md,po-acceptance.handoff.json}` under the directory above. Setup/API-oracle failures, genuine physical cleanup RED, unknown-cause timeout and stale59PASS/1FAIL retry regression remain historical evidence; they are not final-revision PASS claims.

The exact faithful PO Brief binding was exercised through MockTransport only. **DESCRIPTION_NOT_RETAINED** remains: the existing YouTube connector drops returned descriptions, so full approved title/description evidence is not retained. Native runtime is uninstalled; actual host/provider/key readiness and live parent-gap-child qualification/revised synthesis remain unverified. This isolated SQLite composition has no Supabase dependency; global Supabase readiness was not checked or changed. T079 remains unchecked, T080 accepted, ledger79/92 and US5 INCOMPLETE. No live source execution, full-suite, CI, release or shipment acceptance.

T086 accepted on 2026-10-14 at HEAD 0bb84b0e3cf3337223196e52a859afcfa482e8bc against the pre-implementation baseline e543ccbf30b4745ad9fd83ab09cc2dcf012beff8 (product-identical to 031962946fa00623cf2bb3557722f67504c14942). Separate processes serialized the full MCP Tool objects of both revisions through list_tools() only (baseline sha256 7f9dcc698a23f1077ace89ffb19f3ff8c0e29a8799923aa99740ec9b1ea131b5, current f5049b246c0868f3fdfe6967418e5f9f4f01f839ccdb8c8f14f40e885d221ab9, diff d1e8179c616aa6b9c151f017bf810475b50baeea4a25a792356f9079abbdb54b). The current 48 tools are the original 44 plus exactly get_mission_relay_snapshot, open_mission_relay, record_mission_research_work and execute_mission_follow_up; none was removed. 43 original tools are identical in every serialized field, including input and output schemas. The 44th, propose_research_workspace, differs only in its description, which documents the owner-approved caller-owned .fnignis storage (spec.md clarification, commit 6872d7d). README.md and README.vi.md list the four additions beside the retained catalog, openclaw.json and AGENTS.md state 48 tools, and server.json keeps its historical 0.7.0 manifest; no version string or client configuration changed. Both dumps used the same installed fastmcp 4.0.4/mcp 2.2.0, so this proves source-level public-schema compatibility, not historical runtime serialization or the deployed image. Count and catalog tests and the repository conventions were reused at identical bytes. Evidence: .handoff/spec014/schema-readiness/{receipt,schema-independent-review,final-review}.handoff.md. T085 remains partial, and the other open gates and shipment are unaffected.

T088 accepted on 2026-10-14 as a completed convergence assessment, not feature acceptance. The independent R2 review `.handoff/spec014/convergence-review/convergence-assessment-r2-review.handoff.md` accepts the frozen R2 assessment of source 4531e05 (`freeze-r2.sha256`): all 29 FR, 17 SC, 16 scenarios, 15 edge cases, the plan, data-model, contract and constitution obligations, and all 125 clarifications are individually assessed. Genuine findings and acceptance gaps map to existing open tasks, so no task is appended. The consolidated LEAD review `.handoff/spec014/review.handoff.md` records the later dispositions at 1ea2095: the root recovery and stale test-oracle corrections are accepted, and two Minor documentation findings remain. Unexecuted acceptance (current PostgreSQL parity, minimum runtime, full regression, real viewer/follow-up trace, integrated display measurement) stays partial or unknown under T079–T087 and T090; T089 remains conditional on finding disposition.

T089 accepted on 2026-10-14 as completed diff/code and security review with validated findings fixed, not feature acceptance. The consolidated review `.handoff/spec014/review.handoff.md` covers all 185 changed files between e543ccbf and 4531e05 by static code and security-impact review (no proprietary scanner) and records each finding with its tested revision. Every validated in-scope finding was fixed, rerun and independently accepted on exact bytes: R-ROOT-01 root recovery at 22887ab (136 focused passes); I-TEST-01, I-TEST-02 and M-TEST-03 test oracles at 16eba9b; N-TEST-04 packaging oracle at 1ea2095; M-DOC-01 and M-DOC-02 documentation at 24eecb4; and the R-TQ-1/R-TQ-2 CLI test harness at 4c0967c (16 focused passes). The membership-delta browser consumer (U-CL008) is verified, and the private-ledger stable-replacement question is parked by the parent as an unvalidated threat-model limitation. Short-expiry margin, a narrow packet assertion and a timing label remain disclosed method limits. Current PostgreSQL parity, minimum runtime, full regression, performance and real viewer/follow-up acceptance stay under T079–T087 and T090.

T085 accepted on 2026-10-14 as completed guidance work, not feature acceptance. `specs/014-evidence-factory/quickstart.md`, `docs/USER_GUIDE.md` and the localized `docs/USER_GUIDE.vi.md` were audited against the installed implementation across the caller-root, storage, configuration, retention, source-operation, native MCP, fallback-labelling and executable-instruction journeys. The corrections are bound to current source and to the existing 48-tool schema receipts. They state the caller `.env` rules and refusal codes, the admitted report path, all seven channel states, representative atomic source calls with their missingness limits, the Threads `SELF_ONLY`/`NOT_PERMITTED` access boundary, and an isolated-settings pytest pattern. That pattern was executed from its documented text (11 and 8 passes, with a plain isolated control failing closed); repository and public-doc conventions pass. Provisioning, full-suite and server-start commands remain documented and statically verified, not executed in this task, and the UAT scenarios remain procedures.

### T093–T094 R2 preflight and seam spike — 2026-10-19

Self-verified by the executing agent from recorded evidence; no independent review was run for these two documentation and spike tasks. No product code changed.

- T093: `.handoff/spec014/r2-preflight.handoff.md`. Claude Code negotiates MCP `2026-07-28` (three logs); Codex's version was not observed. `IGNIS_CALLER_ROOT` is set nowhere checked. The Relay canvas work is not parked, so T104 stays blocked.
- T094: `.handoff/spec014/r2-spike.handoff.md` and `r2-spike/spike-result.json`, six in-process cases. Middleware can return `InputRequiredToolResult` and read the retried `ListRootsResult` (case C); legacy connections refuse it (case F), so the era gate uses `ctx.session.protocol_version`. Clients that cannot answer a roots request fail the call themselves (cases D, E), which leaves the "retry without roots" fallback in `contracts/caller-root.md` unreachable for the FastMCP client. The owner then decided (2026-10-19) that a configured root on a modern connection is used without asking; the contract, data model and T095/T096/T098 were updated accordingly.

### T095–T096 caller root on MCP 2026-07-28 — 2026-10-19

- T095: `tests/unit/test_caller_root_modern_protocol.py`, written first. Initial RED: 14 failed, 2 passed (NOT_ADVERTISED and legacy controls); every failure was the current `ROOTS_RPC_UNAVAILABLE` path, not setup.
- T096: `src/ignis/infrastructure/caller_storage.py`. Modern connections, detected through `ctx.session.protocol_version` in the SDK's `MODERN_PROTOCOL_VERSIONS`, use a configured `IGNIS_CALLER_ROOT` directly; otherwise they return `InputRequiredToolResult` and validate the retried `ListRootsResult` through the shared `_single_root_path`. Legacy, NOT_ADVERTISED and refusal formats are unchanged.
- Mutants caught: always ask (4 failures), skip the `request_state` check (1), route modern through the legacy branch (14).
- Independent review: no blocking finding. Important finding 1 (modern UNKNOWN capability sent a forbidden `roots/list`) was reproduced RED and fixed. Important finding 2 (no in-process MCP client per era) is T097's scope. Minor findings were recorded in `contracts/caller-root.md`. A non-`file`-scheme URI and a `..` URI cannot reach the server through a typed `ListRootsResult`, so they were replaced by remote-host, query and fragment cases.
- Final run: 123 passed, 19 skipped (PostgreSQL without `IGNIS_TEST_POSTGRES_DSN`) across the new file, the four existing caller-root suites, the snapshot/research-work/follow-up MCP suites and conventions. The new test file is clean under ruff; `caller_storage.py` keeps its 11 pre-existing E701 findings.
- Environment note: during this work `uv run` resynced `.venv` to runtime-only packages; it was restored with `uv sync --locked --inexact --extra dev --extra browser` (Python 3.14.7, previously 3.14.8). The branch as a whole fails CI's `ruff check src/ tests/` on pre-existing files; that is not caused by T095–T096.

### T097 caller root through a real MCP client — 2026-10-19

- `tests/integration/test_caller_root_modern_mcp.py`: a real in-process FastMCP client calls `get_mission_relay_snapshot` and `list_research_missions` on the Attention relay fixture. Cases: client roots on 2026-07-28 and legacy without a configured root; configured root winning over client roots on 2026-07-28 with zero roots requests; legacy configured-versus-client mismatch refusing `ROOT_SCOPE_MISMATCH`; a modern client without roots refusing `CONFIGURED_ROOT_REQUIRED`; a modern client that cannot answer failing client-side with no storage read.
- Result: 12 passed on SQLite file and memory; 6 PostgreSQL cases skipped without `IGNIS_TEST_POSTGRES_DSN`, which is not parity. Against the pre-T096 middleware the same file gives 6 failed (all 2026-07-28 success cases) and 6 passed (legacy and refusal controls).
- Observations: the generic relay fixture's default-surface mission read `READ_UNAVAILABLE` through this path while the Attention fixture read `OK`; existing MCP snapshot tests also use the Attention fixture. Not investigated further. Self-verified; no independent review for this test-only task.

### T098 live Claude Code probe — 2026-10-19

- Evidence: `.handoff/spec014/r2-claude-code-probe.handoff.md`, with the request logs of a temporary logging wrapper and probe server under `.handoff/spec014/r2-spike/`. Claude Code desktop app, negotiated MCP `2026-07-28`; read-only tools only.
- With `IGNIS_CALLER_ROOT` set: `list_research_missions`, `list_research_workspaces` and `get_mission_relay_snapshot` on the real mission `29cb1c03…` all succeeded, each in a single round with no roots request. SC-018's configured-root path is met on this host.
- Without it: Claude Code answers the `InputRequiredResult` roots request and retries, but the call refused with `ROOT_COUNT_INVALID`, inferred from the session's two working directories. **Open owner decision**: how a multi-root answer selects the caller root; until then SC-018's client-roots path is unmet for multi-folder sessions.
- Process note: `/mcp` Reconnect did not move this conversation's tool calls to the restarted server; only a full app restart did. Earlier "Step A" refusals came from the pre-T096 process and are recorded as invalid measurements.
- Cleanup pending: restore `.mcp.json` (remove the wrapper) after the owner chooses whether to keep `IGNIS_CALLER_ROOT`. Self-verified; no independent review.
