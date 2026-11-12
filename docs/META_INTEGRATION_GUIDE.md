# Meta collection: Threads and historical Instagram evidence

On the Spec 022 branch, Threads collection runs only through the user's explicitly authorized
host browser. Reels collection and the platform-specific login tools have been retired.
Stored observations, channel outcomes and sessions remain readable; this change deletes no data.
The branch exposes 41 tools and has not been released as a new version.

## Collect Threads

Use the [collection guide](../.agents/skills/ignis-collect/SKILL.md) for a bounded request.
`prepare_host_browser_search` with `source="threads"` prepares the authorized scope;
`submit_host_browser_search` validates the captured public evidence, and
`cancel_host_browser_search` cancels that scope. Preparation is not permission to access a browser.
The host uses its own browser capability and preserves the user's tabs.

The `threads-search-top-v2` path collects a bounded visible Top sample. Loading, a login wall,
a challenge or an unparseable page is unavailable, never proof of an empty market. Stored Graph
credentials do not enable this flow. Ignis does not probe an API grant or fall back to Graph API
or an internal Playwright collector. See the [user guide](USER_GUIDE.md#explicit-host-browser-search-tiktok-threads-instagram)
for scope, counter precision, identity handling and period comparability.

## Existing sessions and evidence

`get_platform_auth_status` still reads generic credential metadata. Only an explicitly requested
`clear_platform_auth` removes a saved credential locally.
To revoke provider-side access, use the platform's own security settings.
Retirement itself never clears sessions. Self-content exclusion may still read stored account
identity; that does not open a collection session or establish readiness.

A new mission or rerun naming `reels` returns `BLOCKED / SURFACE_RETIRED` before collection.
A watchlist run drops retired requested surfaces with that typed reason, or blocks when none
remain. Old Reels observations and outcomes remain visible under their original platform labels.

## Credential security

Existing credential storage uses Fernet (AES-128-CBC + HMAC-SHA256) with `IGNIS_ENCRYPTION_KEY`.
`key_version` is an envelope label. There is no dual-key decryption or automatic re-encryption;
replacing the key makes records encrypted with the old key unreadable. Never paste credentials
into chat. Output sanitization covers project-controlled paths, not external tools or transcripts.
Pattern-based PII filtering reduces exposure but cannot certify removal of every personal name.

The [source-connection decision](decisions/2026-11-10-source-connection-boundary.md) governs future
connections: an official platform-owner MCP is used by the host; otherwise a working built-in
connection remains eligible. Community MCPs do not qualify as official.
