# Validation Guide: Ignis Relay

**Status**: R2 (2026-10-19) validation guide, drafted with the R2 plan. R1 delivered four additive tools on this branch; R2 keeps `get_mission_relay_snapshot`, `record_mission_research_work` and `execute_mission_follow_up`, retires `open_mission_relay` and the viewer, adds the `ignis-track` prompt and resource, and adds caller-root resolution for MCP 2026-07-28+ clients. None of the R2 changes is implemented yet. [tasks.md](tasks.md), once regenerated, is the only acceptance authority; this guide does not check off tasks.

**Historical setup status (2026-10-04)**: Setup T001–T003 ran existing baselines on 2026-10-04: 217 passed, 58 PostgreSQL cases skipped. T004/T005 RED deliverables have independent review; T006 models are in progress. Dedicated local PostgreSQL testing has begun; no live research mission, workflow migration or benchmark was run.

## Prerequisites

- Owner-approved technical plan and generated implementation tasks before coding.
- Use the authoritative current checkout of the feature branch, or a worktree the owner designated, with its locked `.venv` environment. Do not overwrite the owner's uncommitted work or client configs.
- A real, validated caller root for mission tools, resolved as in [contracts/caller-root.md](contracts/caller-root.md). Legacy-protocol clients that declare roots support must return exactly one existing absolute `file://` directory root; MCP 2026-07-28+ clients are asked for roots through `InputRequiredResult` and otherwise use the startup-configured `IGNIS_CALLER_ROOT` (absolute directory, set at server start, unchanged since). An unknown capability is refused. Each refusal fails with `ROOT_REQUIRED`. Canonical storage defaults to local SQLite at `<root>/.fnignis/canonical.sqlite3`; an explicit literal `DATABASE_URL` in an owner-only `<root>/.fnignis/.env` (see `src/ignis/infrastructure/templates/caller.env.example`) can select another SQLite file inside the root or a PostgreSQL database. `record_mission_research_work` additionally requires the local stdio transport.
- For a single-source question or a Threads source, read [the user guide](../../docs/USER_GUIDE.md) sections 2–3 first: they describe representative atomic calls, their missingness limits and the Threads `SELF_ONLY`/`NOT_PERMITTED` access boundary.
- Explicit database setup before tracking. SQLite is default; PostgreSQL is a separately authorized test backend. A missing schema must produce a typed unavailable snapshot, never bootstrap it.
- A real selected mission and explicit finite research assignment, with host capability and sources/budget recorded. Actual social session use or development database writes need applicable current authorization; this document is not that permission.
- Named concurrency-capable host for actual overlapping research work, plus a sequential-capacity test. Record real host receipts and manual evidence; mocks alone do not satisfy concurrent-team UAT.

## Regression commands

Validation scope matches CI: run the whole `tests/` tree, not `tests/unit/` alone, and report the actual outputs, revision, skips and unavailable gates rather than checking boxes from this guide.

```bash
.venv/bin/pytest tests/
```

PostgreSQL cases run only when `IGNIS_TEST_POSTGRES_DSN` points at a disposable test database (CI provides a service database). Without it they skip, and a skip is not PostgreSQL parity. Never print the DSN.

### Isolated settings

The root `tests/conftest.py` replaces credentials with inert values and removes `IGNIS_ENV_FILE` before tests import Ignis. A plain run therefore still reads non-credential settings from the checkout's `.env`, and its default `DATABASE_URL` is `sqlite:///ignis.db` relative to the working directory. With `IGNIS_ENV_ISOLATED=1` set, a plain `pytest` run fails closed (`Isolated configuration requires IGNIS_ENV_FILE`) as soon as a collected test imports the settings, because the env file was removed first; tests that never import settings still run. To run with settings from a disposable file only, load the settings before pytest starts, from the repository root:

```bash
env_dir="$(mktemp -d)"
printf 'DATABASE_URL=sqlite:///:memory:\nYOUTUBE_API_KEY=\nIGNIS_ENCRYPTION_KEY=\n' > "$env_dir/isolated.env"
env -i PATH=/usr/bin:/bin HOME="$env_dir" IGNIS_ENV_ISOLATED=1 IGNIS_ENV_FILE="$env_dir/isolated.env" \
  .venv/bin/python -c 'import sys, ignis.config, pytest; raise SystemExit(pytest.main(sys.argv[1:]))' \
  -p no:cacheprovider tests/unit/test_repo_conventions.py
```

Replace the final path with the selection you need. This only isolates settings; it neither restores real credentials nor bypasses the root quarantine.

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
- Snapshot MCP read: `tests/integration/test_mission_relay_mcp.py`, `tests/integration/test_mission_relay_us3_readback.py`, `tests/unit/test_mission_relay_mcp_tools.py`. R2 removes the viewer HTTP and Chromium suites listed in [plan.md](plan.md) "Source changes".
- Research work recording and lifecycle: `tests/unit/test_research_work.py`, `tests/integration/test_research_work_persistence.py`, `tests/integration/test_research_work_lifecycle.py`, `tests/integration/test_research_work_mcp.py`, `tests/integration/test_research_recording_mcp_boundary.py`, `tests/unit/test_research_recording_mcp_runtime.py`.
- Gap-linked follow-up: `tests/integration/test_mission_follow_up.py`, `tests/integration/test_follow_up_mcp.py`, `tests/integration/test_follow_up_execution.py`, `tests/integration/test_follow_up_settlement.py`.
- Caller-root admission: `tests/unit/test_caller_storage_native.py`, `tests/unit/test_configured_caller_root.py`, `tests/unit/test_caller_root_diagnostics.py`, `tests/integration/test_follow_up_caller_middleware.py`.
- Scenario 8 security: `tests/integration/test_mission_relay_security.py` keeps its snapshot, scope and masking cases; its viewer, Host/Origin, CSP and browser cases are removed in R2.

Several of these use `relay_case`/`postgres` parametrization, and some write receipts under `.handoff/`; run them from a disposable copy when existing evidence must be preserved.

**Historical setup evidence**: Setup evidence is in ignored `.handoff/spec014/preflight.handoff.md` and `baseline.handoff.md`. The credential-free runner clears ambient environment, explicitly isolates a local SQLite env source and verifies inert Settings before invoking pytest. Root test quarantine removes `IGNIS_ENV_FILE`, so launching plain pytest with the isolation switch still set causes a later Settings import to fail closed; do not bypass the quarantine or restore real credentials. All 58 observed skips require `IGNIS_TEST_POSTGRES_DSN`; this baseline does not verify PostgreSQL or SC-012 host overlap.

## Feature scenarios

**Historical RED setup (superseded by implementation)**: The T004 test file is `tests/integration/test_mission_progress_persistence.py`. It calls real `record_probe_outcomes`, verifies durable rows, injects SQLite database write refusal and forces different-command transaction contention. After independent review and correction, SQLite-only observation was 6 behavioral failures, 2 passing controls and 8 missing-DSN skips. A subsequent actual run on SQLite and dedicated local PostgreSQL observed 10 failures, 3 passes and 3 PostgreSQL harness skips. The remaining skips require PostgreSQL fault injection and lock/commit scheduling, not a DSN. These were missing-runtime RED results at the time, not a GREEN/parity gate.

T005 was `tests/unit/test_mission_relay_projection.py`: at that time 59 cases collected, 58 failed at the named absent projection API and one existing sanitizer control passed. No downstream projection masking, refusal or missingness branch had executed. Minor review coverage notes (UTF-8 byte bounds and exact typed key allowlists) were then assigned to T006/T023/T081. The instruction at the time was to re-evaluate all actual behavior once implementation existed: initial API RED was not security acceptance, and the new tests had to become GREEN under the later implementation without xfail or suppressed failures. Current acceptance of those tasks is governed by [tasks.md](tasks.md).

1. Select a real mission with no active research. Ask the agent to track it: it reads `get_mission_relay_snapshot` and writes a local artifact. Verify all six responsibilities appear, and compare before/after storage and spies: no mission/schema/seed writes, collector/auth/model calls or quota use. Repeat with missing schema and both databases.
2. Execute explicitly authorized collection. At each milestone the agent regenerates the artifact; verify each recorded change appears once, with no duplicate arrivals or counts across regenerations and reordered pages, and that every artifact shows its `read_at` and point-in-time status.
3. Record an explicit research assignment; the capable host actually performs two overlapping work items sharing an observation. Trace host receipt → work → evidence-bearing handoff → finding revision. Repeat sequentially. Connector concurrency and synthetic lifecycle commands are not substitutes.
4. Submit counterevidence/alternative explanation and a finding revision. Inspect prior version and limitations. Submit obsolete/mismatched work and verify no current status. Submit a strategic candidate without current permission; show gap/withheld, never a commercial verdict. A failed read or current-input change withdraws permission in the next artifact.
5. Record a gap-linked bounded follow-up, invoke `execute_mission_follow_up`, inspect its separate child frame and resulting labeled finding. Assert parent remains terminal, retries/racing calls create no duplicate probe and child permission is never presented as parent permission. Exhaust authority or change source/credential/scope: zero unauthorized work.
6. Exercise collection completion while assigned analysis remains valid; separately end/cancel/fail/expire/insufficient research. New starts/follow-ups are refused after termination. Writer ownership without actual activity shows unknown, not active work.
7. Between milestones and after the agent's turn ends, count snapshot reads: zero. Interrupt the agent mid-mission: the underlying research is not cancelled, and no read follows.
8. Attack the snapshot: cross-mission and child scope, unsafe text, oversized pagination. Inspect artifacts, JSON and logs for credentials, protected content and reasoning. Attempt to publish an artifact without consent: the agent must ask first.
9. From Claude Code on a negotiated 2026-07-28 connection, call a mission tool with `IGNIS_CALLER_ROOT` set (expect the configured root, no roots request), then without it (expect a roots request; record whether Claude Code answers it), and with neither working (expect `ROOTS_REQUEST_FORBIDDEN` or a client-side failure). Record the negotiated version and which path resolved. Repeat one call from a legacy-protocol client.
10. Read the `ignis_track` prompt and `fn-ignis://guide/ignis-track` resource from an installed wheel, and compare them with `.agents/skills/ignis-track/SKILL.md`.

## Requirement-to-validation coverage

| Design obligation | Requirements | Acceptance |
|---|---|---|
| Six responsibilities in a host artifact; truthful states and unknowns | FR-001–005, FR-009, FR-015, FR-018, FR-026 | SC-001, SC-004, SC-006, SC-015 |
| No built-in viewer; snapshot plus guidance; no presentation-triggered work | FR-006, FR-012–013, FR-030 | SC-003, SC-009 |
| Generation on request or milestone; static, label-carrying content | FR-007–008, FR-011, FR-016 | SC-002, SC-005, SC-007 |
| Coherent snapshots, idempotent regeneration, stale permission | FR-010, FR-014, FR-024–025 | SC-008, SC-010–011, SC-013 |
| Real work, host provenance, handoffs/findings, no new agent platform | FR-019–022, FR-027 | SC-011–013 |
| Gap follow-up, distinct termination and cumulative authority | FR-023, FR-029 | SC-014, SC-017 |
| Mission access, masking, publication consent | FR-017, FR-028, FR-031 | SC-016 |
| Caller root on 2026-07-28+ clients | FR-032 | SC-018 |

All FR-001–032 and SC-001–018 are covered; mapping is a design check, not executed PASS.

## Evidence and shipping record

Store temporary run/review material in `.handoff/`; admitted `generate_mission_artifact` exports go to the caller root's `<root>/.fnignis/reports/` (the checkout's ignored `reports/` is only the fallback for calls without a caller root); never commit credentials, raw protected content or local generated screenshots by default. Attach sanitized visual/runtime evidence to review as appropriate. Record tested revision, commands, observed outcomes, skipped/unavailable checks, host overlap proof, backend coverage and UAT limitations.

After converge and review, focused PR integration and post-merge readback settle canonical backlog. Release requires its own approval and version gate. Do not close the spec for only slice 1 or report local success as shipping.
