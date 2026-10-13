# Validation Guide: Ignis Relay

**Status**: The four additive tools (`get_mission_relay_snapshot`, `open_mission_relay`, `record_mission_research_work`, `execute_mission_follow_up`) and their storage, viewer and follow-up runtime are implemented on this branch. Each has scoped, independently reviewed local engineering verification. That is not feature acceptance: real follow-up UAT, end-to-end security, PostgreSQL lifecycle parity, integrated performance, schema rehearsal, guidance/catalog synchronization, full regressions, review and integration remain open gates in [the Spec 014 task ledger](tasks.md), which is the only acceptance authority. This guide does not check off tasks.

**Historical setup status (2026-10-04)**: Setup T001–T003 ran existing baselines on 2026-10-04: 217 passed, 58 PostgreSQL cases skipped. T004/T005 RED deliverables have independent review; T006 models are in progress. Dedicated local PostgreSQL testing has begun; no live research mission, workflow migration or benchmark was run.

## Prerequisites

- Owner-approved technical plan and generated implementation tasks before coding.
- Use the authoritative current checkout of the feature branch, or a worktree the owner designated, with its locked `.venv` environment. Do not overwrite the owner's uncommitted work or client configs.
- A real, validated caller root for mission tools. Mission-scoped MCP calls (tool names containing `mission` or `research_workspace`, `confirm_market_brief`, or calls carrying `mission_id`/`workspace_id`) are admitted only through one validated caller root. When the client's MCP capabilities declare roots support, it must return exactly one existing absolute `file://` directory root; an empty, multiple, invalid or unavailable roots list is refused, and if `IGNIS_CALLER_ROOT` is also configured the returned root must match it exactly. The configured `IGNIS_CALLER_ROOT` (an absolute directory set at server startup and unchanged since) is used only when those capabilities explicitly declare no roots support. An unknown capability is refused. Each refusal fails with `ROOT_REQUIRED`. For an admitted call, canonical storage defaults to local SQLite at `<root>/.fnignis/canonical.sqlite3`. An explicit literal `DATABASE_URL` in an owner-only `<root>/.fnignis/.env` (see `src/ignis/infrastructure/templates/caller.env.example`) can instead select another SQLite file inside the root or a PostgreSQL database; caller configuration, logs, reports and research files stay under `<root>/.fnignis/` either way. `record_mission_research_work` additionally requires the local stdio transport.
- Explicit database setup outside the viewer. SQLite is default; PostgreSQL is a separately authorized test backend. A missing schema must produce an unavailable viewer, never bootstrap it.
- A real selected mission and explicit finite research assignment, with host capability and sources/budget recorded. Actual social session use or development database writes need applicable current authorization; this document is not that permission.
- Named concurrency-capable host for actual overlapping research work, plus a sequential-capacity test. Record real host receipts and manual evidence; mocks alone do not satisfy concurrent-team UAT.

## Regression commands

Validation scope matches CI: run the whole `tests/` tree, not `tests/unit/` alone, and report the actual outputs, revision, skips and unavailable gates rather than checking boxes from this guide.

```bash
.venv/bin/pytest tests/
```

PostgreSQL cases run only when `IGNIS_TEST_POSTGRES_DSN` points at a disposable test database (CI provides a service database). Without it they skip, and a skip is not PostgreSQL parity. Never print the DSN.

The pre-feature baseline regressions from setup remain available as narrow checks:

```bash
.venv/bin/pytest tests/unit/test_repo_conventions.py
.venv/bin/pytest tests/unit/test_host_browser_relay.py tests/unit/test_host_browser_search.py tests/unit/test_mission_claims.py tests/unit/test_evidence_qualification.py
.venv/bin/pytest tests/integration/test_workspace_concurrency.py tests/integration/test_mission_bound_idle.py tests/integration/test_host_browser_search_mcp.py tests/integration/test_host_browser_mission.py tests/integration/test_evidence_grounded_market_mission.py
```

Run backend-specific integration procedures from the repository's existing test setup; do not put a credential-bearing connection string into command output. Capture skip reasons. The above regressions do not alone prove new feature acceptance.

### Spec 014 suites

These narrow suites exist on this branch. Select them with the same `.venv/bin/pytest` invocation; each passing run is engineering evidence for its own scope only, and open acceptance stays in [tasks.md](tasks.md).

- Progress persistence and coherent reads: `tests/integration/test_mission_progress_persistence.py`, `tests/integration/test_mission_relay_read_boundary.py`, `tests/unit/test_mission_relay_projection.py`, `tests/unit/test_mission_relay_port.py`.
- Relay viewer, MCP and HTTP: `tests/integration/test_mission_relay_mcp.py`, `tests/integration/test_mission_relay_lifecycle.py`, `tests/integration/test_mission_relay_us3_readback.py`, `tests/unit/test_mission_relay_mcp_tools.py`, `tests/unit/test_mission_relay_http.py`.
- Viewer rendering, accessibility and responsive layout (Chromium): `tests/integration/test_mission_relay_browser.py`, `tests/integration/test_mission_relay_accessibility.py`, `tests/integration/test_mission_relay_responsive.py`, `tests/integration/test_mission_relay_visual.py`, `tests/integration/test_mission_relay_research_browser.py`.
- Research work recording and lifecycle: `tests/unit/test_research_work.py`, `tests/integration/test_research_work_persistence.py`, `tests/integration/test_research_work_lifecycle.py`, `tests/integration/test_research_work_mcp.py`, `tests/integration/test_research_recording_mcp_boundary.py`, `tests/unit/test_research_recording_mcp_runtime.py`.
- Gap-linked follow-up: `tests/integration/test_mission_follow_up.py`, `tests/integration/test_mission_follow_up_viewer.py`, `tests/integration/test_follow_up_mcp.py`, `tests/integration/test_follow_up_execution.py`, `tests/integration/test_follow_up_settlement.py`.
- Caller-root admission: `tests/unit/test_caller_storage_native.py`, `tests/unit/test_configured_caller_root.py`, `tests/unit/test_caller_root_diagnostics.py`, `tests/integration/test_follow_up_caller_middleware.py`.

Several of these use `relay_case`/`postgres` parametrization, and some write sanitized screenshots or receipts under `.handoff/`; run them from a disposable copy when existing evidence must be preserved. The scenario 8 end-to-end security suite is not yet present.

**Historical setup evidence**: Setup evidence is in ignored `.handoff/spec014/preflight.handoff.md` and `baseline.handoff.md`. The credential-free runner clears ambient environment, explicitly isolates a local SQLite env source and verifies inert Settings before invoking pytest. Root test quarantine removes `IGNIS_ENV_FILE`, so launching plain pytest with the isolation switch still set causes a later Settings import to fail closed; do not bypass the quarantine or restore real credentials. All 58 observed skips require `IGNIS_TEST_POSTGRES_DSN`; this baseline does not verify PostgreSQL or SC-012 host overlap.

## Feature scenarios

**Historical RED setup (superseded by implementation)**: The T004 test file is `tests/integration/test_mission_progress_persistence.py`. It calls real `record_probe_outcomes`, verifies durable rows, injects SQLite database write refusal and forces different-command transaction contention. After independent review and correction, SQLite-only observation was 6 behavioral failures, 2 passing controls and 8 missing-DSN skips. A subsequent actual run on SQLite and dedicated local PostgreSQL observed 10 failures, 3 passes and 3 PostgreSQL harness skips. The remaining skips require PostgreSQL fault injection and lock/commit scheduling, not a DSN. These were missing-runtime RED results at the time, not a GREEN/parity gate.

T005 was `tests/unit/test_mission_relay_projection.py`: at that time 59 cases collected, 58 failed at the named absent projection API and one existing sanitizer control passed. No downstream projection masking, refusal or missingness branch had executed. Minor review coverage notes (UTF-8 byte bounds and exact typed key allowlists) were then assigned to T006/T023/T081. The instruction at the time was to re-evaluate all actual behavior once implementation existed: initial API RED was not security acceptance, and the new tests had to become GREEN under the later implementation without xfail or suppressed failures. Current acceptance of those tasks is governed by [tasks.md](tasks.md).

1. Select a real mission with no active research, call `open_mission_relay` with an explicit finite deadline, then inspect all six responsibilities. Compare before/after storage and spies: no mission/schema/seed writes, collector/auth/model calls or quota use. Repeat with missing schema and both databases.
2. Execute explicitly authorized collection outside the viewer. Verify committed events and outcomes reach the five columns; roll back a failing write and prove it emits no durable result event. Reconnect/reorder responses and verify no duplicate arrivals/counts. Measure update time from successful coherent read, not connector start.
3. Record an explicit research assignment; the capable host actually performs two overlapping work items sharing an observation. Trace host receipt → work → evidence-bearing handoff → finding revision. Repeat sequentially. Connector concurrency and synthetic lifecycle commands are not substitutes.
4. Submit counterevidence/alternative explanation and a finding revision. Inspect prior version and limitations. Submit obsolete/mismatched work and verify no current status. Submit a strategic candidate without current permission; show gap/withheld, never a commercial verdict. Failed refresh/current-input change removes permission immediately.
5. Record a gap-linked bounded follow-up, invoke `execute_mission_follow_up`, inspect its separate child frame and resulting labeled finding. Assert parent remains terminal, retries/racing calls create no duplicate probe and child permission is never presented as parent permission. Exhaust authority or change source/credential/scope: zero unauthorized work.
6. Exercise collection completion while assigned analysis remains valid; separately end/cancel/fail/expire/insufficient research. New starts/follow-ups are refused after termination. Writer ownership without actual activity produces unknown, not endless pulsing.
7. Pause motion (refresh still valid), pause refresh, hide, close and expire. Inspect timer/read/animation counters and late-response refusal. No new automatic reads after the boundary; an already admitted read may settle without UI application or writes. Underlying research is not cancelled by viewer controls.
8. Attack read capabilities, Host/Origin, expiry, cross-mission/child access, unsafe text/URLs, oversized pagination and shutdown races. Inspect DOM/JSON/logs for credentials, protected content and reasoning. Existing writable Task Relay stays unchanged.
9. Capture actual 390/768/1440 screenshots, keyboard and reduced-motion walkthrough, no-font/offline content checks and 30-second FPS measurement with machine/browser/workload declared. Confirm approved light hierarchy rather than merely checking that a file opens.

## Requirement-to-validation coverage

| Design obligation | Requirements | Acceptance |
|---|---|---|
| Five columns/six responsibilities; stage explanations; restrained FINOLABS encoding | FR-001–004, FR-011, FR-018, FR-026 | SC-001, SC-003, SC-006, SC-015 |
| Real selected mission, truthful metadata/unknowns, no presentation-triggered work | FR-005–006, FR-009, FR-012–013, FR-015 | SC-004, SC-008–009 |
| Keyboard, independent pause, reduced motion, bounded visible refresh | FR-007–008, FR-016 | SC-002–003, SC-005–007, SC-009 |
| Coherent revisions, durable events, idempotent animation, stale permission | FR-010, FR-014, FR-024–025 | SC-008, SC-010–011, SC-013 |
| Real work, host provenance, handoffs/findings, no new agent platform | FR-019–022, FR-027 | SC-011–013 |
| Gap follow-up, distinct termination and cumulative authority | FR-023, FR-029 | SC-014, SC-017 |
| Mission access, safe typed masking, no hidden reasoning | FR-017, FR-028 | SC-016 |

All FR-001–029 and SC-001–017 are covered; mapping is a design check, not executed PASS.

## Evidence and shipping record

Store temporary run/review material in `.handoff/`; runtime exports in ignored `reports/`; never commit credentials, raw protected content or local generated screenshots by default. Attach sanitized visual/runtime evidence to review as appropriate. Record tested revision, commands, observed outcomes, skipped/unavailable checks, host overlap proof, backend coverage and UAT limitations.

After converge and review, focused PR integration and post-merge readback settle canonical backlog. Release requires its own approval and version gate. Do not close the spec for only slice 1 or report local success as shipping.
