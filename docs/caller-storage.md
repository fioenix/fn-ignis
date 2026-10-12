# Caller-owned storage and configuration

Mission tools require one authorized filesystem root. A client that explicitly advertises roots uses exactly one valid native MCP root. If the canonical typed client capabilities explicitly do not advertise roots, an operator may supply exactly one `IGNIS_CALLER_ROOT` in the server launch environment. Missing or unknown capabilities refuse; caller arguments, installation CWD and global database settings never grant root authority. Independent tactical operations retain their existing configuration. Actual native Codex configured-root activation is unverified; offline controls are not native-client integration proof.

## Operator startup scope

Set the scope before starting the existing server entry point, for example:

```sh
IGNIS_CALLER_ROOT=/absolute/path/to/authorized/repository fn-ignis
```

This is an operator launch example, not an installed registration or permission inferred from the model's `host_workspace` argument. Do not put this authority key in caller `.fnignis/.env`; that file retains its strict settings allowlist. The middleware snapshots the launch value once when the server is constructed, validates an absolute existing directory without traversal or symlink ancestors, and pins root/ancestor identities. Later environment edits cannot change an active server's grant. Startup validation creates no `.fnignis` files. Missing, malformed, replaced or symlinked configured roots refuse with sanitized `ROOT_REQUIRED` details.

Explicit non-advertisement selects the configured scope without an unsupported roots RPC. Advertising clients always use native roots: missing, malformed, ambiguous or failed native roots refuse, with no configured fallback. If a launch scope is also configured, it must be valid, unchanged and exactly match the selected native root. `host_workspace` and proposed paths remain assertions checked against that scope. A fresh launch may adopt another explicit operator scope; it does not migrate data, restore source grants or renew mission clocks/budgets. A same-account launch environment is operator authority, not independent proof of human identity.

Workspace confirmation protects `.fnignis/` with a bounded `/.fnignis/` entry in the caller repository's `.gitignore`, preserving existing bytes. An already tracked `.fnignis/.env` refuses setup without changing the index. Generated `.env` has mode 0600 and contains only a comment; existing user configuration is preserved. `.env.example` contains commented placeholders only.

| Location | Actual contents and allocation |
|---|---|
| `.fnignis/.env` | User-owned literal settings; created at confirmed setup, never populated with credentials automatically |
| `.fnignis/.env.example` | Supported setting placeholders; existing file preserved |
| `.fnignis/canonical.sqlite3` | Default canonical database, created when a repository operation needs storage |
| Configured database | Same canonical mission/accounting, permission manifests, raw source observations and processed qualification/Claim Ledger tables; existing mission/source/observation IDs remain authoritative. PostgreSQL stores these records remotely when explicitly selected. No duplicate raw/processed export directories are created. |
| `.fnignis/research/<workspace-slug>/` | Per-workspace manifests, mission references and run journals, allocated by existing workspace/run consumers |
| `.fnignis/reports/` | Requested artifacts, allocated by the existing artifact consumer |
| `.fnignis/logs/ignis.log` | Operational component/level metadata only; allocated on a scoped Ignis log event, maximum 256 KiB per file with two backups. Arbitrary messages and source bodies are excluded. |

## Explicit configuration

Supported keys are `DATABASE_URL`, `DB_MIN_POOL_SIZE`, `DB_MAX_POOL_SIZE`, `YOUTUBE_API_KEY`, `YOUTUBE_SEARCH_DAILY_LIMIT`, and `YOUTUBE_OTHER_DAILY_UNIT_LIMIT`. Caller settings precede typed local defaults: absent/empty `DATABASE_URL` uses local canonical SQLite; pools default to 1/3, YouTube caps to 100/10000 and its key to empty. Scoped consumers do not inherit the installation database or YouTube key. Configuration never grants source access or paid quota.

Parsing is literal dotenv syntax without shell execution or variable interpolation. Unknown keys, duplicate keys, invalid bounds, insecure file permissions and invalid connections refuse with sanitized errors. A changed configuration snapshot refuses cached consumers; restart the server to adopt explicit edits. Caller root and path identity checks remain active.

An explicit `sqlite:///` connection requires an absolute path inside the authorized caller root without traversal, query options or fragments. Outside-file SQLite needs separate path authority and is refused. Explicit `postgres://` or `postgresql://` uses the existing PostgreSQL adapter and supplied pool bounds. A failing configured backend refuses without creating a fallback SQLite database. Offline adapter failure controls do not establish connectivity or PostgreSQL server behavior.

Stopping, cancelling, revoking ingress, restarting or closing a viewer preserves data without restoring source grants, renewing clocks/budgets, or collecting automatically. No existing installation/live data is migrated. Future deletion requires an explicit owner decision. Source-specific YouTube 30-day policy/freshness status is documented in the owning contract; automatic refresh/deletion and runtime policy status are not introduced here. Dashboard startup is a separate dependent unit.

SQLite is the default for current operational transactions and canonical record reads. No analytical scan, volume or concurrency scalability claim follows from these controls. Filesystem checks constrain paths and observed identities; they do not claim perfect protection against hostile concurrent filesystem races.
