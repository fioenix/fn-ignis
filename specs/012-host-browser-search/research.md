# Research: Host Browser Search

## Transport

**Decision**: Explicit host-agent-mediated prepare/submit/cancel MCP protocol, initially local Codex.
**Rationale**: Ignis has no callable browser transport into Codex. The host executes deterministic
extraction through its actual supported APIs; no Python connector pretends to invoke CUA.
**Alternatives**: Direct CUA calls lack a transport; CDP/cookie export violate approved boundaries;
another headed launch flag was not repeatably reliable. MCP sampling adds unnecessary LLM collection.

Protocol feasibility is established, deployed transport is not. An actual MCP/host round-trip is the
first implementation stop gate. Unsupported hosts refuse rather than recreate a session.

## Mission Integration

**Decision**: Prepare outside a run; submit under existing writer after revision validation.
**Rationale**: `workspace_repository.mission_run` finalizes a normal return and releases its writer.
Returning awaiting-browser would falsely complete a run; keeping a context across calls creates fragile
locks. Separate collection from common ingestion in `execute_mission._execute_pass`.
**Alternatives**: No second evidence store, replacement default plugin or terminal-run restart.

Seams: `execute_mission.py` (`execute`, `_require_manifest_authority`, `_build_collection_plan`,
`_execute_pass`); `workspace_repository.py` (`mission_run`, `record_collection_plan`);
`current_evidence_frame.py` (`load_current_evidence_frame`, `frame_from_snapshot`);
`server.py` (`handle_execute_mission_ingress`). Remaining approved sources run in the same pass.

## Evidence and Replay

**Decision**: Strict validator creates existing `SearchPassResult`, `SurfaceProbeResult` and signals;
process-local ticket ownership blocks replay before persistence.
**Rationale**: Registry `_search_outcome` is too permissive for this trust boundary. Existing signals
separate publication/capture and allow provenance metadata. `save_signals` creates new observation UUIDs,
so canonical source dedup alone does not prevent repeated observations.
**Alternatives**: Reject guessed dates/metrics, inheriting requested window as observed window, silent
retries and durable-resume claims. Failed/partial searches never become measured zero.

## Extraction and Host Trust

**Decision**: Versioned packaged deterministic DOM script, bounded visible public video grid, typed JSON.
**Rationale**: Avoid private UI spill and model-generated fields; keep source URLs and actual excerpts.
Session ownership is a trusted-host responsibility verified live, not a cryptographic payload property.
**Alternatives**: No raw HTML/screenshots, semantic card parsing, remote script download or arbitrary
external dataset import. Photo/live/suggestion cards remain unsupported, visibly limited.

## Serialization

**Decision**: Existing FastMCP registration style and Pydantic boundary; no dependency upgrade.
**Rationale**: Official docs describe typed structured returns; installed-version behavior still needs
contract smoke. Current documentation is not proof of runtime compatibility.
**Alternatives**: No new-version API assumed without checking the installed server.

Consulted via Context7 on 2026-10-02:
[Official FastMCP tools documentation](https://github.com/prefecthq/fastmcp/blob/main/docs/servers/tools.mdx).

## Outcome

Architectural unknowns resolved into bounded choices. Transport deployment, extraction stability and
mission parity remain implementation gates, not research successes. No live connector, database or
credentials were accessed in this planning research.
