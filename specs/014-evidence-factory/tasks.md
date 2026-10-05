# Tasks: Ignis Relay — Observable Research Mission

**Input**: Approved R1 `spec.md`, owner-approved `plan.md`, `research.md`, `data-model.md`, `contracts/` and `quickstart.md`.

**Status**: T001–T038 accepted:38/92. T038 actual FastMCP selected-scope tool and capability HTTP inspector refuse foreign observation, unknown observation and foreign journal with exact SCOPE_MISMATCH. EMPTY_NO_DATA0, DEGRADED and later declared unmeasured channel null stay distinct; committed corpus/storage unchanged and bootstrap traps silent. Coordinator shared15PASS5.68s (T0383); independent shared15PASS6.43s (T0383), no skips, verified PostgreSQL scratch cleanup. Evidence .handoff/spec014/t038/review.handoff.md and t039/reviewer-final.xml. Commit each completed task; PR only after full Spec014 completion. Real-mission UAT and shipment remain pending.

**Outcome**: A real, bounded, read-only research observatory with inspectable events, actual host work/handoffs, evolving findings and one authority-bound child follow-up. Static animation, synthetic concurrency and SQLite-only success do not close this feature.

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
- [ ] T039 [US3] Run gate negatives on SQLite and PostgreSQL through `tests/integration/test_mission_relay_read_boundary.py`; verify consistent frame/role interpretation and exact canonical observation identities.
- [ ] T040 [US3] Record permission/missingness readback and measured successful-read-to-display latency in `.handoff/spec014/us3.handoff.md`; leave real-mission latency acceptance pending until final UAT.

## Phase 5 — US4: Follow real specialist work and evolving findings (P1)

**Goal**: Actual bounded host work yields inspectable handoffs and source-bound finding revisions, without installing a scheduler or model provider.

**Independent test**: Two real host work items overlap and hand off shared observations without duplicate corroboration; sequential mode stays sequential; counterevidence revises a finding; obsolete results never become current.

- [ ] T041 [US4] Add failing assignment/work state, finite authority, epoch/fence, idempotency and provenance cases in `tests/unit/test_research_work.py`; verify free-form policy/writer ownership is not new authority or liveness.
- [ ] T042 [P] [US4] Add failing atomic handoff/finding, dependency revision, shared identity and obsolete result cases in `tests/integration/test_research_work_persistence.py`; include consumer rejection and no unsafe rejected payload retention.
- [ ] T043 [US4] Define typed assignment/work/activity/command models in `src/ignis/domain/research_work.py`; make T041 model validation pass with unknown assignees and honest host capability.
- [ ] T044 [US4] Define immutable handoff/finding revisions and binding validation in `src/ignis/domain/research_findings.py`; verify support, contradiction, alternatives, limits and explicit descriptive/strategic types in T042.
- [ ] T045 [US4] Define atomic work admission/result/lifecycle ports in `src/ignis/application/ports/research_work_port.py`; verify recording cannot dispatch agents, models or connectors.
- [ ] T046 [US4] Add owner-only assignment/work/handoff/finding schema and immutable observation references in `sql/028_research_work.sql`; verify pruning mission membership cannot cascade-delete historical handoffs/findings.
- [ ] T047 [US4] Add explicit SQLite research schema and work transition CAS in `src/ignis/infrastructure/persistence/sqlite_repository.py`; make assignment/version/fence/idempotency T041/T042 persistence cases pass.
- [ ] T048 [P] [US4] Add PostgreSQL equivalent assignment/work transition CAS in `src/ignis/infrastructure/persistence/postgres_repository.py`; prove racing starts/results have one admitted version.
- [ ] T049 [US4] Commit handoff, finding revisions, completion and progress events atomically in `src/ignis/infrastructure/persistence/sqlite_repository.py`; make SQLite rollback/dependency/history T042 cases pass.
- [ ] T050 [P] [US4] Commit equivalent PostgreSQL handoff/finding/event transactions in `src/ignis/infrastructure/persistence/postgres_repository.py`; verify exact inputs and immutable observation references, not a second evidence corpus.
- [ ] T051 [US4] Implement typed command dispatch/admission in `src/ignis/application/use_cases/record_mission_research_work.py`; make T041/T042 pass with public-safe result/reason allowlists and no semantic provider invocation.
- [ ] T052 [US4] Implement cancellation-request/acknowledged-stop, terminal epoch fences and deadline admission in `src/ignis/application/use_cases/record_mission_research_work.py`; verify valid analysis after collection completion versus zero new work after research termination.
- [ ] T053 [US4] Add `record_mission_research_work` MCP handler in `src/ignis/interfaces/mcp/server.py`; verify unknown fields, foreign mission/observations and widened authority are refused with safe typed responses.
- [ ] T054 [US4] Extend coherent readers/projection with work, handoffs, findings and bounded activity basis in `src/ignis/infrastructure/persistence/mission_relay_reader.py` and `src/ignis/application/use_cases/get_mission_relay_snapshot.py`; verify dependency changes invalidate current findings without changing evidence-frame digest for a heartbeat.
- [ ] T055 [US4] Render actual lanes/handoffs, finite activity basis and finding history in `src/ignis/infrastructure/templates/html/mission_relay.html`; verify no fixed replicas, endless pulses, duplicated shared evidence or provisional strategic bypass.
- [ ] T056 [US4] Add MCP lifecycle/masking/race tests in `tests/integration/test_research_work_mcp.py`; exercise actual command-to-database-to-viewer chain, old receipts and terminated/expired authority on both backends.
- [ ] T057 [US4] Run an explicitly assigned real two-specialist overlap on a declared capable host and a separate sequential scenario; record sanitized questions/receipts/overlap/output/readback in `.handoff/spec014/research-host-uat.handoff.md` without hidden reasoning or pretending timestamps prove execution.
- [ ] T058 [US4] Verify counterevidence revision/history and <=5-second post-read display in the real host scenario, recording results in `.handoff/spec014/us4.handoff.md`; mark SC-012/013 unmet if actual host execution or freshness proof is unavailable.

## Phase 6 — US2: Inspect without being forced to watch (P2)

**Goal**: Users can inspect, pause and resume independently of mission execution, including keyboard and reduced-motion use.

**Independent test**: Motion-only pause preserves authorized refresh; refresh pause/hidden/closed/expiry admits zero new automatic reads or motion; keyboard and reduced-motion preserve all essential information.

- [ ] T059 [US2] Add failing motion/refresh separation, hide/close/expiry and late-response cases in `tests/integration/test_mission_relay_browser.py`; count actual fetches/animation frames rather than inspect labels.
- [ ] T060 [P] [US2] Add keyboard/focus, reduced-motion and unavailable-external-resource cases in `tests/integration/test_mission_relay_accessibility.py`; verify essential inspection works without hover or continuous motion.
- [ ] T061 [US2] Add independent motion and refresh controls to `src/ignis/infrastructure/templates/html/mission_relay.html`; make T059 pass without cancel/restart/collect controls.
- [ ] T062 [US2] Add visibility/expiry/page-close cleanup, aborted-read generation fencing and explicit resume/resync in `src/ignis/infrastructure/templates/html/mission_relay.html`; verify admitted reads may settle but cannot update paused/expired UI.
- [ ] T063 [US2] Add semantic stage/evidence navigation, visible focus and restrained accessible update announcements in `src/ignis/infrastructure/templates/html/mission_relay.html`; make keyboard T060 cases pass without focus stealing.
- [ ] T064 [US2] Apply reduced-motion/no-animation and font-unavailable fallback in `src/ignis/infrastructure/templates/html/mission_relay.html`; make remaining T060 cases pass with complete readable facts and zero continuous loops.
- [ ] T065 [US2] Adjust responsive stage/inspector layout in `src/ignis/infrastructure/templates/html/mission_relay.html`; verify 390/768/1440 widths retain controls and essential text without page overflow.
- [ ] T066 [US2] Capture and inspect actual rendered screenshots plus keyboard/reduced-motion walkthrough in `.handoff/spec014/visual-uat.handoff.md`; compare light hierarchy/space/motion with the approved mock, never its illustrative metrics.
- [ ] T067 [US2] Run boundary counters during pause/hide/expiry on the integrated viewer and record `.handoff/spec014/us2.handoff.md`; verify underlying research neither stops nor starts because of viewer controls.

## Phase 7 — US5: Close a research gap without exceeding authority (P2)

**Goal**: One assigned gap leads to one bounded child mission and a traceable revised finding; new/exhausted authority refuses work before probes.

**Independent test**: Trace gap → assignment → child evidence → cross-check → finding/claim-or-gap; parent stays terminal, child frame stays distinct, duplicate admission performs no extra probe, expired/new scope performs zero work.

- [ ] T068 [US5] Add failing scope/source/session/Brief/epoch/deadline/quota and duplicate-admission cases in `tests/integration/test_mission_follow_up.py`; assert actual connector-call counts and conservative unresolved reservations.
- [ ] T069 [P] [US5] Add failing child-frame isolation and related-result inspection cases in `tests/integration/test_mission_follow_up_viewer.py`; negate parent permission, foreign child access and implicit composite-frame assertions separately.
- [ ] T070 [US5] Define typed follow-up relationship/reservation/result models in `src/ignis/domain/mission_follow_up.py` and port methods in `src/ignis/application/ports/research_work_port.py`; verify no unrestricted execution-time query/credential payload.
- [ ] T071 [US5] Add additive parent/child and reservation schema in `sql/029_mission_follow_up.sql`; verify uniqueness, existing child mission ownership and canonical evidence counts remain unchanged by installation.
- [ ] T072 [US5] Implement SQLite atomic child admission and cumulative reservation in `src/ignis/infrastructure/persistence/sqlite_repository.py`; make SQLite racing/idempotency/exhaustion T068 cases pass.
- [ ] T073 [P] [US5] Implement equivalent PostgreSQL child admission/reservation in `src/ignis/infrastructure/persistence/postgres_repository.py`; prove one child admission across competing transactions.
- [ ] T074 [US5] Implement gap-linked tightened authority admission and deterministic child execution in `src/ignis/application/use_cases/execute_mission_follow_up.py`; make T068 pass while retaining parent terminal guards and existing connector authorization.
- [ ] T075 [US5] Add conservative settlement/failure/cancellation/crash reconciliation in `src/ignis/application/use_cases/execute_mission_follow_up.py`; verify uncertain child/writer/quota state cannot silently rerun collection or release allowance.
- [ ] T076 [US5] Add only `execute_mission_follow_up` MCP handler in `src/ignis/interfaces/mcp/server.py`; verify expected epoch/idempotency and refusal before any collector/client authentication initialization.
- [ ] T077 [US5] Project explicitly scoped child result and related finding revisions in `src/ignis/application/use_cases/get_mission_relay_snapshot.py`; make T069 pass without implicit parent-child evidence membership or combined permission.
- [ ] T078 [US5] Render the recorded gap-return path and labeled child result in `src/ignis/infrastructure/templates/html/mission_relay.html`; verify child inspection needs its own selected scope and viewer contains no follow-up execution button.
- [ ] T079 [US5] Run a currently authorized real bounded follow-up using existing child qualification/claim tools and record `.handoff/spec014/follow-up-uat.handoff.md`; prove revised synthesis, parent terminal state and exact child frame with observed outcomes, not synthetic replay.
- [ ] T080 [US5] Run all follow-up/terminal authority negatives on both backends and record `.handoff/spec014/us5.handoff.md`; assert zero unauthorized probes and leave skipped or incomplete lifecycle acceptance unchecked.

## Phase 8 — Cross-cutting review, UAT and integration

**Goal**: Close the full approved scope with evidence, then integrate only under owner authority; do not select a release/version.

- [ ] T081 [P] Add and run end-to-end cross-mission/child access, Host/Origin/CSP/XSS, expiry, bounds, log/DOM/JSON masking and shutdown race cases in `tests/integration/test_mission_relay_security.py`; record both negative controls and any unverified threat surface.
- [ ] T082 Complete lifecycle race/interrupt acceptance in `tests/integration/test_research_work_mcp.py` and `tests/integration/test_mission_follow_up.py`; verify collection completion does not end valid analysis and research end never admits new work.
- [ ] T083 Measure a 30-second integrated desktop sample on the declared reference machine and actual workload in `.handoff/spec014/performance.handoff.md`; verify >=50 FPS and <=5-second post-coherent-read display, plus zero idle/hidden reads and disclosed packet aggregation.
- [ ] T084 Verify all additive schema rehearsals, SQLite/PostgreSQL parity, access policy and unchanged canonical counts/digests in `.handoff/spec014/schema.handoff.md`; record actual environments/revisions and rollback retention, not a production migration claim.
- [ ] T085 Update executable new-tool/test/UAT guidance in `specs/014-evidence-factory/quickstart.md` and permanent `docs/USER_GUIDE.md`; verify documented commands and tool semantics against installed implementation rather than task promises.
- [ ] T086 Synchronize additive tool catalogs with actual registered schemas in `README.md`, `README.vi.md`, `server.json`, `openclaw.json` and `AGENTS.md`; verify the catalog is old signatures plus exactly four intended additions, without changing version strings or client configs.
- [ ] T087 Run convention, full unit, applicable integration, minimum-supported-Python and distribution asset checks; record exact commands/revision/results/skips in `.handoff/spec014/regressions.handoff.md` and verify the maintained viewer template is packaged.
- [ ] T088 Apply `speckit-converge` to implementation versus `specs/014-evidence-factory/spec.md`, `plan.md` and `tasks.md`; append genuine remaining tasks without ticking unavailable UAT or treating successful local checks as shipping.
- [ ] T089 Perform actual diff/code review and security review, record findings and tested revision in `.handoff/spec014/review.handoff.md`; fix and rerun validated in-scope findings, or explicitly park accepted/deferred blockers with owner ruling.
- [ ] T090 Assemble requirement-by-requirement acceptance, real host/follow-up receipts and rendered evidence in `.handoff/spec014/acceptance.handoff.md`; verify all 29 FR/17 SC and disclose unmet gates before requesting integration authority.
- [ ] T091 After explicit owner integration authorization, create/attach a focused PR with observed verification, risks and remaining work using `.github/PULL_REQUEST_TEMPLATE.md` when present; record actual URL/status in `BACKLOG.md`, never assume plan approval authorizes push/merge.
- [ ] T092 After explicit owner merge authorization and successful required checks, integrate and verify post-merge canonical state in `BACKLOG.md` and `specs/014-evidence-factory/tasks.md`; record deployed/activated versus parked status, leaving release/tag/version untouched without separate approval.

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

Mapping coverage is not a test result. Mark a task complete only after reading its fresh verification evidence; an implementation checkbox cannot substitute for an unmet linked acceptance gate.

## Implementation strategy and stop points

1. **First internal slice**: T001–T040 delivers real persisted evidence viewing with truthful permission/missingness. It is not release-ready by itself; motion/accessibility, actual research and follow-up still remain.
2. **Research team slice**: T041–T067 delivers source-bound work/findings with actual concurrent/sequential host evidence and usable motion controls. Host-reported and harness-observed facts remain visibly distinct.
3. **Bounded return loop**: T068–T080 delivers a gap-linked child mission without resurrecting parent collection or blending frames.
4. **Full feature**: T081–T090 closes review/UAT with fresh evidence. T091–T092 close integration under owner authority. Release is outside this task list.

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
