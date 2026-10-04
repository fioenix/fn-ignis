# Implementation Plan: Task-Bound Host Browser Search

**Working branch**: `release/v0.8.0` | **Date**: 2026-10-02 | **Spec**: [spec.md](spec.md)
**Status**: Owner approved on 2026-10-02, including bounded localhost relay; execution in progress.
No release operation authorized.
**Workspace**: `/Users/fioenix/.codex/worktrees/evidence-grounded-reset/fn-ignis`

## Summary

Restore attributable TikTok public-search access through the owner's authorized browser without
recreating its session. Success requires an actual Ignis request, host execution, validated submission
and readback; manual browser success is insufficient.

Use an explicit host-agent-mediated handoff: prepare a bounded request, execute a packaged deterministic
DOM extractor through the host's supported browser tools, and submit typed answers. Add three public
operations without changing current signatures/defaults. Python does not call Codex CUA directly.

## Technical Context

- **Language/version**: Python 3.11+, Pydantic 2; JavaScript for deterministic public-card extraction.
- **Dependencies**: Existing FastMCP/MCP stack; no new dependency or SDK upgrade. Verify installed
  version serialization rather than assuming current documentation matches it.
- **Storage**: Existing evidence database and workspace run journal. Process-local tickets/receipts;
  no migration, durable queue, credential store or second observation database.
- **Testing**: pytest unit/contract/integration, installed-wheel MCP smoke, authorized live Chrome.
- **Platform**: Initially local Codex, authorized browser capability and one long-lived Ignis process.
  Other hosts unsupported until validated separately.
- **Performance**: Work bounded by exact query count/result limits; no background loop, polling,
  automatic retry, remote scripts or full-page transcript transfer.
- **Constraints**: Public TikTok search only; explicit finite scope/expiry. Unknown dates, counters and
  window filters remain unknown. Host orchestration may use an agent, but extraction/ETL/validation
  must not use model interpretation of cards.
- **Scope**: Tactical observations and mission integration; no comments, private UI, keyword Trends
  time series, session export, debugging port, collector fallback or release.

## Constitution Check

Checked before research and again after design. No exception proposed; implementation still must prove
these constraints. Owner approved the additive operations and task-bound localhost relay.

| Principle | Constraint and verification |
|---|---|
| I: Task-bound autonomy | Explicit finite request; terminal tickets; deterministic collection/ETL |
| II: Composable capabilities | Tactical independence; current mission shapes; unsupported hosts visible |
| III: Evidence integrity | Query/source/capture provenance; stale guards; conservative empty attestation; qualification unchanged |
| IV: Maintained artifacts | No report source added; existing maintained HTML templates remain canonical |
| V: Minimal coherent change | No dependency/migration/vocabulary constant; surgical common-ingestion refactor with parity tests |
| VI: Evidence-gated delivery | Installed MCP/host live round-trip before readiness; separate integration/release gates |

## Architecture and Lifecycle

1. `prepare_host_browser_search` validates tactical scope or confirmed mission authority, full query
   union including falsifiers, finite limits and expiry. It returns a process-bound immutable ticket
   and per-query IDs. It creates no mission run and holds no writer while waiting for the host.
2. Host uses one authorized session and task-created tab. Execute the versioned packaged extractor
   only on matching public search pages. Return allowlisted typed records and search attestation,
   never cookies, private chrome, HTML or model-generated metrics.
3. `submit_host_browser_search` validates the entire answer before writes and atomically claims the
   ticket. Mission mode acquires the existing writer and rechecks mission/manifest/Brief/plan/frame
   revisions under lock, then injects validated `SearchPassResult` into common ingestion.
4. Remaining approved non-host sources run within the same mission pass. Every manifest surface
   receives an outcome; never omit a source, truncate falsifiers, increase quotas or silently replace
   its authority. Host-path authority is request-scoped, not a registry default change.
5. Tactical submission returns observations/outcomes without mission creation or persistence. Mission
   submission reuses canonical source/observation/association storage, qualification and frame creation.
   Working source access does not confer eligibility for Market claims.
6. `cancel_host_browser_search`, expiry, rejection, failure and completion terminate tickets. Cancel
   invalidates acceptance; it cannot remotely close Chrome. Host checks before each navigation and
   cleans up task-created resources in its finally path, leaving owner tabs intact.

IDs bind a request but are not cryptographic proof of browser origin. The authorized host is a trusted
collector; session reuse/ownership must be verified through host tests, not inferred from JSON.

Exact accepted replay returns the cached process-local receipt; differing or concurrent replay refuses.
Once ingestion begins, any failure terminates the ticket. Existing run journal reports uncertain/partial
persistence; require readback before replacement. Restart loses tickets and refuses stale submissions.
No durable resume, automatic resubmission or exactly-once crash guarantee is promised.

## Project Structure

```text
specs/012-host-browser-search/
├── spec.md
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/host-browser-search.md
└── checklists/requirements.md

src/ignis/
├── application/use_cases/execute_mission.py       # Common ingestion refactor
├── application/use_cases/host_browser_search.py  # Proposed ticket orchestration
├── domain/host_browser_search.py                 # Proposed typed models
├── infrastructure/connectors/host_browser/       # Proposed deterministic validation
│   └── tiktok_search.js                          # Packaged public-card extractor
└── interfaces/mcp/server.py                      # Additive operations
tests/{unit,integration}/                          # Unit and MCP contract/integration coverage
```

Use existing layering/dependency injection. Package extractor as a wheel resource; prepare exposes
its version/exact extraction instructions. No runtime code download. Update host-facing collection
skill, tool inventories, README variants and user guide; do not impose this path on unrelated tasks.

## Implementation Sequence and Gates

1. Contract/transport spike with failing tests: actual local MCP prepare, supported host DOM execution,
   actual submit. Stop if transport requires unsafe permissions, manual re-entry or model extraction.
2. Ticket/validator tests: binding, expiry, concurrency/replay, malformed/oversized input, wrong URL,
   unknown fields/metrics, partial failure, verified empty vs degraded.
3. Surgical ingestion refactor: preserve existing execution parity; test writer/frame/manifest races,
   complete budgets and every surface outcome. Do not restart historical terminal missions.
4. Two-query session lifecycle: completion/failure/cancel preserve owner resources; no automatic fallback.
5. Sanitized full suite/conventions, installed-wheel contract smoke and extractor packaging, code/security
   review, authorized live retry and readback; integrate through the approved repository workflow.

Execution ledger: [tasks.md](tasks.md). These are work packages, not task completion claims. Stop for
an architecture checkpoint after two independent corrections leave the same end-to-end invariant red.

## Delivery Boundary and Complexity

Plan approved; production bridge not implemented/activated. Plan approval covers additive
operations, not database mutation, release or default collector replacement. Process-local tickets trade
durable resume for minimal scope; after uncertain persistence, the owner pays a readback step instead
of hidden retry risk. No constitutional exception requested.

## Execution Checkpoint: 2026-10-02

Current CUA documentation provides DOM evaluation and browser controls but no direct MCP invocation
or arbitrary JSON export. Current tool inventory has no shared-value transport between CUA and MCP.
This is a missing relay boundary, not a TikTok search failure. Do not reconstruct records in model
tool arguments or bypass the host tooling through a shell/CDP connection. T003 remains blocked.

Owner-approved amendment ("Đồng ý"): a task-bound localhost-only relay page/listener in the same
Ignis process, random request nonce, strict Host/Origin and payload validation, no third-party CORS,
no credentials, no public binding, and immediate shutdown at task termination. Host would fill the
local submission form from its in-memory extractor output via documented UI tooling. This is only
the implementation boundary. HTTP receives/stages the typed answer; MCP submit consumes it without
model reconstruction. Use a standard-library server, no extra dependency. Model/relay/tactical-tool
foundation must precede the actual T003 round-trip; mission work still waits for that gate.
