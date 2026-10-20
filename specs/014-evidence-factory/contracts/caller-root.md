# Caller-Root Resolution Contract (R2)

**Status**: Revised 2026-10-19 after T098 (owner decision): the caller root is the folder the agent was opened in. Supersedes the client-roots and protocol-era rules implemented in T095–T096. Requirement FR-032 and SC-018.

## Scope

Applies to every call the caller-storage middleware treats as mission-scoped: tool names containing `mission` or `research_workspace`, `confirm_market_brief`, and calls carrying `mission_id` or `workspace_id`. Public tool arguments do not change.

## Resolution

1. **Override**: if `IGNIS_CALLER_ROOT` was set at server start, it is the root when valid (absolute existing directory, no `..`, no symlinked component) and identity-unchanged; otherwise refuse with `CONFIGURED_ROOT_INVALID` or `CONFIGURED_ROOT_CHANGED`.
2. **Startup folder**: otherwise the root is the server's working directory at startup, which an agent host sets to the folder the session was opened in. It is snapshotted and identity-pinned at startup like the override. Refuse with `STARTUP_ROOT_REFUSED` when it cannot be one project: the filesystem root, the user's home directory or any parent of it (compared by file identity against both `HOME` and the account's password-database home, so a symlinked or differently spelled `HOME` still matches), a world-writable or sticky directory, or a directory the server's user does not own and another user could pre-seed with `.fnignis/`. Refuse with `STARTUP_ROOT_INVALID` when it is not a valid directory, and `STARTUP_ROOT_CHANGED` when its identity changed.
3. Client roots, `roots/list`, `InputRequiredResult` roots requests and the negotiated protocol era are not consulted.

`.fnignis/` is created inside the resolved root as before. The existing `host_workspace` and `proposed_path` checks still bind arguments to that root. `host_workspace` must be an absolute path naming the same directory by file identity, so a symlinked spelling of the root is accepted and rewritten to the pinned root before the tool runs; any other folder refuses with `CALLER_STORAGE_SCOPE_REFUSED`.

## Refusal format

Unchanged: `ROOT_REQUIRED category=<category> roots_capability=<capability> rpc_error=<kind> owner_state=<state>`, fixed facts only and no client payload echoed. New categories: `STARTUP_ROOT_REFUSED`, `STARTUP_ROOT_INVALID`, `STARTUP_ROOT_CHANGED`. The roots-request categories added in T096 are retired.

## Verification obligations

- Unit tests for each rule above, including an override that wins over the startup folder, each refused startup folder above (including home through a symlink), a replaced startup folder, one turned into a symlink, a renamed parent, and `host_workspace` given through a symlinked path.
- An in-process MCP client test showing a client that sends several roots, or none, still resolves to the startup folder, on both protocol eras.
- Tests never resolve to the checkout's own `.fnignis/`: a test that resolves the checkout as its root is refused before storage opens and fails at teardown.
- A live Claude Code session opened in the repository, with an extra working directory and without `IGNIS_CALLER_ROOT`, reads a real mission.
