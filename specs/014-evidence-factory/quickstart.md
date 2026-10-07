# Validation Guide: Ignis Relay

**Status**: Future feature acceptance guide; new tools and integrated runtime are not implemented yet. Setup T001–T003 ran existing baselines on 2026-10-04: 217 passed, 58 PostgreSQL cases skipped. T004/T005 RED deliverables have independent review; T006 models are in progress. Dedicated local PostgreSQL testing has begun; no live research mission, workflow migration or benchmark was run.

## Prerequisites

- Owner-approved technical plan and generated implementation tasks before coding.
- Use the managed feature worktree and its locked environment; do not overwrite the owner's primary checkout or client configs.
- Explicit database setup outside the viewer. SQLite is default; PostgreSQL is a separately authorized test backend. A missing schema must produce an unavailable viewer, never bootstrap it.
- A real selected mission and explicit finite research assignment, with host capability and sources/budget recorded. Actual social session use or development database writes need applicable current authorization; this document is not that permission.
- Named concurrency-capable host for actual overlapping research work, plus a sequential-capacity test. Record real host receipts and manual evidence; mocks alone do not satisfy concurrent-team UAT.

## Existing regression commands

These files currently exist. Run from repository root after implementation; report actual outputs/revision and unavailable gates rather than checking boxes from this guide.

```bash
.venv/bin/pytest tests/unit/test_repo_conventions.py
.venv/bin/pytest tests/unit/test_host_browser_relay.py tests/unit/test_host_browser_search.py tests/unit/test_mission_claims.py tests/unit/test_evidence_qualification.py
.venv/bin/pytest tests/integration/test_workspace_concurrency.py tests/integration/test_mission_bound_idle.py tests/integration/test_host_browser_search_mcp.py tests/integration/test_host_browser_mission.py tests/integration/test_evidence_grounded_market_mission.py
```

Run backend-specific integration procedures from the repository's existing test setup; do not put a credential-bearing connection string into command output. Capture skip reasons. The above regressions do not alone prove new feature acceptance. New test paths/commands belong to implementation tasks and must be updated here once they exist.

Setup evidence is in ignored `.handoff/spec014/preflight.handoff.md` and `baseline.handoff.md`. The credential-free runner clears ambient environment, explicitly isolates a local SQLite env source and verifies inert Settings before invoking pytest. Root test quarantine removes `IGNIS_ENV_FILE`, so launching plain pytest with the isolation switch still set causes a later Settings import to fail closed; do not bypass the quarantine or restore real credentials. All 58 observed skips require `IGNIS_TEST_POSTGRES_DSN`; this baseline does not verify PostgreSQL or SC-012 host overlap.

## Feature scenarios once implemented

The current T004 test file is `tests/integration/test_mission_progress_persistence.py`. It calls real `record_probe_outcomes`, verifies durable rows, injects SQLite database write refusal and forces different-command transaction contention. After independent review and correction, SQLite-only observation was 6 behavioral failures, 2 passing controls and 8 missing-DSN skips. A subsequent actual run on SQLite and dedicated local PostgreSQL observed 10 failures, 3 passes and 3 PostgreSQL harness skips. The remaining skips require PostgreSQL fault injection and lock/commit scheduling, not a DSN. These are missing-runtime RED results, not a GREEN/parity gate.

T005 is `tests/unit/test_mission_relay_projection.py`: 59 cases collect, 58 fail at named absent projection API and one existing sanitizer control passes. No downstream projection masking, refusal or missingness branch has executed. Minor review coverage notes (UTF-8 byte bounds and exact typed key allowlists) remain assigned to T006/T023/T081. Re-evaluate all actual behavior once implementation exists; initial API RED is not security acceptance. New tests must become GREEN under the later implementation; do not xfail them or suppress their failure to prepare a release.

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
