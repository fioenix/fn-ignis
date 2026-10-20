# Implementation Plan: Ignis Relay — Observable Research Mission

**Branch**: `codex/ignis-relay-checkout` | **Date**: 2026-10-19 | **Spec**: [R2](spec.md)

**Status**: R2 re-plan approved by the owner on 2026-10-19 ("Duyệt plan R2 của Spec 014"). The owner-approved R1 plan (2026-10-04) and its execution history remain in this file's git history at `b455322`. The task ledger in [tasks.md](tasks.md) (83/92 on 2026-10-14) predates R2 and must be regenerated with `speckit-tasks` after this plan is approved. No product code changes in this phase.

## Summary

Outcome: a person follows a real mission, and sees why a conclusion is permitted or withheld, through a tracking artifact their own agent generates. Ignis supplies a truthful bounded snapshot and the `ignis-track` guidance. Claude Code, the primary host, can actually call the mission tools.

R2 changes three things relative to R1:

1. **Retire the built-in viewer.** Remove the `open_mission_relay` tool, the loopback HTTP listener, the `mission_relay.html` template and its builder, and the automatic dashboard start after run admission. Keep the relay runtime owner that serves snapshot reads and caller scopes.
2. **Add `ignis-track`.** One maintained guidance text, served as MCP prompt `ignis_track` and resource `fn-ignis://guide/ignis-track`, and mirrored to `.agents/skills/ignis-track/SKILL.md`. It tells agents how to read the snapshot, which display rules hold, when to regenerate and where the artifact may go.
3. **Use the folder the agent was opened in as the caller root.** Server-initiated `roots/list` is forbidden on MCP 2026-07-28 (SEP-2577), which is why Claude Code got `ROOT_REQUIRED category=ROOTS_RPC_UNAVAILABLE`. After T098 the owner chose the server's startup folder as the root, with `IGNIS_CALLER_ROOT` as an optional override (research R2-6).

Kept from R1 as delivered: progress facts and events committed with their data, coherent no-bootstrap readers on both backends, the allowlisted projection, `get_mission_relay_snapshot`, research-work recording and gap-linked follow-up.

## Technical Context

**Language/Version**: Python >= 3.11; minimum-version CI remains required.

**Primary Dependencies**: Installed FastMCP 4.0.4 and `mcp` 2.2.0 (with `mcp_types`). No new dependency. R2 removes the standard-library loopback HTTP viewer; Jinja2 stays for maintained reports.

**Storage**: Unchanged. No migration, no table removal. Viewer-only state was process-local and disappears with the listener.

**Testing**: pytest across `tests/`. In-process MCP client tests that negotiate both the 2026-07-28 and a legacy protocol version. One live probe from Claude Code for SC-018, recorded under `.handoff/`. PostgreSQL parity cases need `IGNIS_TEST_POSTGRES_DSN`; a skip is not parity.

**Target Platform**: Local MCP server over stdio. Hosts render artifacts; Ignis renders none for tracking.

**Project Type**: Existing agent harness. R2 removes a product surface and adds guidance; no new runtime service.

**Performance Goals**: R1's 50 FPS and five-second display goals are retired. Snapshot bounds stay as implemented: page size 1–200, serialized response at most 1,048,576 bytes, typed refusal on overflow.

**Constraints**: No polling or background refresh (FR-007). Local-file default and consent before publication (FR-031). Tool count goes from 48 to 47; the removal of `open_mission_relay` is the only signature change and is owner-approved. No connector tier, schema or persisted-evidence change.

**Scale/Scope**: One explicitly selected mission per snapshot read; related child missions keep separate scope.

**Unknowns resolved in [research.md](research.md)**: whether FastMCP 4.0.4 middleware can return `InputRequiredResult` for any mission-scoped tool (R2-5, needs a spike before implementation); whether Claude Code answers a `ListRootsRequest` inside `InputRequiredResult` (R2-5, needs a live probe; the configured-root fallback covers a negative result).

## Constitution Check

Pre-design and post-design checks are design checks, not runtime acceptance.

| Principle | Status | Obligation |
|---|---|---|
| I — Mission-bound autonomy | Pass | Snapshot reads happen only on a user request or an agent milestone inside its turn; reading never starts collection. |
| II — User-controlled connectors | Pass | No connector, session or quota change. |
| III — Evidence and falsification | Pass | The snapshot already carries claim gate, frame pending reason, channel outcomes and unknowns; the guidance forbids inferring missing states or rendering withheld claims as permitted. |
| IV — Deterministic report builders | Pass (amended) | Constitution 2.1.0, amended 2026-10-19 per R2-4: the template rule governs Ignis research reports; tracking artifacts follow the shipped `ignis-track` rules, which the amended IV now names. |
| V — Simplicity and type safety | Pass with obligation | Removing a tool is an intentional breaking boundary: every consumer is listed in Project Structure and each must be updated or removed with proof. The guidance is one source served three ways, not three copies. |
| VI — Migration and release | Pass | No migration. Rollback is restoring the removed files from git; retained tables are untouched. |

Product reasoning: outcome is the user's ability to follow a mission and see the claim gate; design targets Claude Code first because that is where the owner works and where the current refusal sits; critical thinking is enforced by display rules that forbid inferring support, demand or liveness.

Post-design re-check: all principles pass against constitution 2.1.0.

## Project Structure

### Documentation

```text
specs/014-evidence-factory/
  spec.md                    # R2 requirements and clarifications
  plan.md                    # This R2 plan
  research.md                # R1 decisions plus R2-1..R2-5
  data-model.md              # R1 records; tracking artifact and caller-root resolution added
  contracts/tracking.md      # New: snapshot use and ignis-track delivery
  contracts/caller-root.md   # New: root resolution by protocol era
  contracts/relay-viewer.md  # Retired in R2; kept as history
  contracts/research-work.md # Unchanged
  contracts/follow-up.md     # Unchanged
  quickstart.md              # R2 validation guide
  checklists/requirements.md # Re-validated after R2 clarify
  tasks.md                   # To be regenerated by speckit-tasks
```

### Source changes (proposed, not made in planning)

Remove (viewer consumers found by repository search on 2026-10-19):

```text
src/ignis/infrastructure/mission_relay.py                  # loopback HTTP listener
src/ignis/infrastructure/templates/html/mission_relay.html # viewer template
src/ignis/infrastructure/templates/html_builder.py         # build_mission_relay_artifact only
src/ignis/interfaces/mcp/server.py                         # open_mission_relay tool and handler,
                                                           # listener creation, started_dashboard
                                                           # and the run_started dashboard hook
tests/unit/test_mission_relay_http.py
tests/unit/test_mission_relay_template.py
tests/integration/test_mission_relay_browser.py, _visual.py, _accessibility.py,
  _responsive.py, _research_browser.py, test_mission_follow_up_browser.py,
  test_mission_follow_up_viewer.py, and viewer cases in _lifecycle.py, _security.py
```

Modify:

```text
src/ignis/interfaces/mcp/server.py           # ignis_track prompt and resource
src/ignis/infrastructure/caller_storage.py   # modern-era root resolution (contracts/caller-root.md)
src/ignis/interfaces/mcp/guides/ignis_track.md  # new packaged guidance source
.agents/skills/ignis-track/SKILL.md          # mirror of the packaged guidance
.hermes/tools.json, hermes_manifest.json     # tool catalog 48 -> 47
scripts/wheel_mcp_smoke.py                   # expected tool count
README.md, README.vi.md, docs/USER_GUIDE.md, docs/USER_GUIDE.vi.md
tests/unit/test_public_mcp_contract.py, test_public_distribution_contract.py,
  test_mission_relay_mcp_tools.py, test_caller_relay_read_composition.py
tests/integration/test_mission_relay_mcp.py, test_mission_relay_us3_readback.py,
  test_research_work_mcp.py, test_clean_user_journey.py
```

Packaging needs no `pyproject.toml` change: the wheel ships all of `src/ignis`. The existing distribution asset check must instead prove the wheel contains the guide and no viewer template.

Keep `_MissionRelayRuntime` and its `read_service` and `caller_scopes`: the snapshot tool and the caller-storage middleware depend on them. Renaming it is out of scope.

## Delivery slices

1. **Caller root on modern protocol** (FR-032, SC-018). Spike first: prove middleware can return `InputRequiredResult` and read `input_responses`; then implement and test both eras; then the live Claude Code probe. Delivers value on its own: every mission tool works from Claude Code.
2. **`ignis-track` guidance** (FR-007, FR-008, FR-014, FR-030, FR-031; SC-002, SC-003). Packaged guide, prompt, resource, SKILL mirror with an equality test, and an audit that every display rule maps to a snapshot field or a typed refusal.
3. **Viewer retirement** (FR-006, FR-013). Remove the listed consumers, update catalogs and docs to 47 tools, and prove no remaining reference.
4. **Acceptance** (SC-001, SC-004–SC-018). A real mission tracked from Claude Code at two or more milestones with artifact-to-snapshot readback, plus the still-valid R1 gates.

Disposition of open R1 tasks for `speckit-tasks`:

| R1 task | R2 disposition |
|---|---|
| T079 real follow-up UAT | Keep; evidence is the tracking artifact instead of the viewer. |
| T081 end-to-end security | Narrow to snapshot and artifact surfaces: cross-mission and child scope, masking, bounds, publication consent. Drop Host/Origin/CSP/browser cases. |
| T082 lifecycle races | Keep. |
| T083 desktop FPS | Drop. |
| T084 schema parity | Keep. |
| T087 regressions | Keep, against the R2 tree. |
| T090 acceptance | Rescope to R2 FR/SC. |
| T091, T092 PR and merge | Keep, owner-gated. |

The uncommitted Relay canvas work in the main checkout serves only the retired viewer. Park it on its own branch before slice 3; do not merge it.

## Integration and approval gates

1. Owner approves this R2 plan. Done on 2026-10-19.
2. `speckit-constitution` executes the IV amendment. Done: constitution 2.1.0 on 2026-10-19.
3. `speckit-tasks` regenerates `tasks.md`.
4. Implementation follows the slices; live probes and real missions use only current authority.

Before calling R2 integrated: converge against FR-001–032 and SC-001–018, resolve or explicitly accept review and security findings, attach the Claude Code probe and real-mission tracking evidence, merge a focused PR and verify post-merge checks in the canonical backlog. No release or version is selected here.

## Complexity Tracking

| Item | Why it is needed | Cost and expiry |
|---|---|---|
| Startup-folder root with an optional override | One rule for every host and protocol era; replaces the T096 client-roots paths. | Hosts that start servers outside the opened folder need `IGNIS_CALLER_ROOT`; the startup-folder refusal (filesystem root, home or a parent of it, shared, sticky or foreign-owned directories) and identity pinning are the only guards. |
