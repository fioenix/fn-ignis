# Caller-Root Resolution Contract (R2)

**Status**: Drafted with the R2 plan on 2026-10-19; not implemented. Requirement FR-032 and SC-018; decision in [research.md](../research.md) R2-5. Amends Session 2026-10-11 "explicitly configured startup root" only for MCP 2026-07-28+ connections.

## Scope

Applies to every call the caller-storage middleware treats as mission-scoped today: tool names containing `mission` or `research_workspace`, `confirm_market_brief`, and calls carrying `mission_id` or `workspace_id`. Public tool arguments do not change.

## Resolution

The resolution table is in [data-model.md](../data-model.md) "Caller-root resolution". Behavior per round on a 2026-07-28+ connection whose client advertises roots:

1. **First round** (no `input_responses`): return `InputRequiredResult` with `input_requests = {"ignis_caller_roots": ListRootsRequest}` and a `request_state` that binds the tool name and the connection. Do no mission work.
2. **Retry with roots** (`input_responses["ignis_caller_roots"]` is a `ListRootsResult`): validate with the legacy rules (exactly one root, `file://` scheme, empty or `localhost` host, no query or fragment, absolute existing directory, no `..`), and require equality with `IGNIS_CALLER_ROOT` when one is configured.
3. **Retry without roots**: use the startup-configured `IGNIS_CALLER_ROOT` if it is present, valid and identity-unchanged; otherwise refuse with `ROOT_REQUIRED category=ROOTS_REQUEST_FORBIDDEN`.
4. **Invalid or foreign `request_state`**: refuse; never trust echoed state that the server did not issue for this call.

Legacy connections keep `roots/list`. `ROOTS_RPC_UNAVAILABLE` stays reserved for a legacy request that actually fails.

## Refusal format

Unchanged: `ROOT_REQUIRED category=<category> roots_capability=<capability> rpc_error=<kind> owner_state=<state>`, fixed facts only and no client payload echoed. New category: `ROOTS_REQUEST_FORBIDDEN`.

## Verification obligations

- In-process MCP client tests negotiating 2026-07-28 and a legacy version, covering every row of the resolution table, invalid `request_state`, and a mismatch between returned and configured roots.
- A spike proving the middleware can return `InputRequiredResult` and read `input_responses` under FastMCP 4.0.4, before the implementation task starts.
- A live Claude Code probe recorded under `.handoff/`: negotiated version, whether roots were returned, and which path resolved. No credentials or user paths beyond the root are printed.
