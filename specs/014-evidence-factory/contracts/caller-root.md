# Caller-Root Resolution Contract (R2)

**Status**: Drafted with the R2 plan on 2026-10-19; not implemented. Requirement FR-032 and SC-018; decision in [research.md](../research.md) R2-5. Amends Session 2026-10-11 "explicitly configured startup root" only for MCP 2026-07-28+ connections, where a configured root takes precedence over client roots (owner decision 2026-10-19 after the T094 spike).

## Scope

Applies to every call the caller-storage middleware treats as mission-scoped today: tool names containing `mission` or `research_workspace`, `confirm_market_brief`, and calls carrying `mission_id` or `workspace_id`. Public tool arguments do not change.

## Resolution

The resolution table is in [data-model.md](../data-model.md) "Caller-root resolution". On a 2026-07-28+ connection whose client advertises roots:

1. **Configured root present**: if `IGNIS_CALLER_ROOT` was set at server start, use it when it is valid and identity-unchanged, without asking the client and without comparing it with client roots. An invalid or changed configured root refuses with the existing `CONFIGURED_ROOT_INVALID` or `CONFIGURED_ROOT_CHANGED`; it never falls through to asking.
2. **No configured root, first round** (no `input_responses`): return `InputRequiredResult` (FastMCP `InputRequiredToolResult`) with `input_requests = {"ignis_caller_roots": ListRootsRequest}` and a `request_state` naming the tool. Do no mission work.
3. **Retry with roots** (`input_responses["ignis_caller_roots"]` is a `ListRootsResult`): validate with the legacy rules (exactly one root, `file://` scheme, empty or `localhost` host, no query or fragment, absolute existing directory, no `..`).
4. **Retry without roots**: refuse with `ROOT_REQUIRED category=ROOTS_REQUEST_FORBIDDEN`. A client that cannot answer may instead fail the call itself (observed for the FastMCP client in the T094 spike); the server then never sees a retry.
5. **Invalid or foreign `request_state`**: refuse; never trust echoed state that the server did not issue for this call.

Era detection uses `ctx.session.protocol_version`; a legacy connection never receives `InputRequiredResult`, because it refuses that result type (T094 case F).

Further rules (from the T096 independent review):

- **`request_state` integrity** comes from the SDK's request-state boundary, which seals the value under a per-process key and binds it to the method, tool name, an arguments digest, the server audience, the authenticated principal and a 600-second expiry. It is not bound to the session and is not single-use. That is sufficient here because the returned roots, validated with the legacy rules, are the authority; a replayed state only skips one round trip.
- **UNKNOWN capability on a modern connection** refuses with `ROOT_CAPABILITY_UNKNOWN` after the owner-lifespan check and never sends `roots/list`.
- **Era set**: "modern" means a version in the SDK's `MODERN_PROTOCOL_VERSIONS` (`2026-07-28` in `mcp` 2.2.0). A later version the SDK does not yet list falls into the legacy branch and fails closed.
- **Constraint on mission tools**: a mission-scoped tool must not return its own `InputRequiredResult` while this middleware owns `request_state`; its retry would refuse with `ROOTS_REQUEST_STATE_INVALID`. No such tool exists on 2026-10-19.

Legacy connections keep `roots/list`. `ROOTS_RPC_UNAVAILABLE` stays reserved for a legacy request that actually fails.

## Refusal format

Unchanged: `ROOT_REQUIRED category=<category> roots_capability=<capability> rpc_error=<kind> owner_state=<state>`, fixed facts only and no client payload echoed. New categories: `ROOTS_REQUEST_FORBIDDEN` and `ROOTS_REQUEST_STATE_INVALID`.

## Verification obligations

- In-process MCP client tests negotiating 2026-07-28 and a legacy version, covering every row of the resolution table, invalid `request_state`, an invalid or changed configured root on a modern connection (refuses, never asks), and the legacy configured-versus-returned mismatch.
- Done in T094: the middleware can return `InputRequiredToolResult` and read `input_responses` under FastMCP 4.0.4.
- A live Claude Code probe recorded under `.handoff/`: negotiated version, whether roots were returned, and which path resolved. No credentials or user paths beyond the root are printed.
