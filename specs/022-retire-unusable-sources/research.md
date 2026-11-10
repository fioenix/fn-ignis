# Research: source retirement

## R1 — Separate collection admission from retained evidence
Decision: explicit retired-surface policy for `google`, `tiktok_creative_center`,
`tiktok_video_grid`, `reels`; validate creation and execution, not `MissionManifest.__post_init__`.
Rationale: stored manifests must still deserialize, and period reads derive channels from stored
rows. Alternatives rejected: deleting platform enums or filtering repository reads hides evidence;
removing only registry entries returns generic unavailable/empty behavior and misses optional paths.

## R2 — Watchlists and legacy routine prompts
Decision: sanitize only a new run's requested resource list; preserve order, return typed retirement
entries, and reject a request with no surviving resources. Stored watchlists contain immutable topic
versions and run references; `allowed_resources` actually belongs to run manifests and host prompts.
Rationale: no persisted watchlist rewrite is needed. Rejecting a mixed request violates US2; storing
new zero observations or mutating old outcomes would turn retirement into fabricated evidence.

## R3 — Comments, sessions and identity
Decision: preserve `TikTokPlugin.canonical_comment_video_url` and `fetch_video_comments` with its
navigation guard, redaction, ephemeral commenter keys and error shape; compose it without stored
authentication. Generic auth tools remain direct repository operations. Keep self-identity loading
and encrypted credential repository APIs. Do not delete any session row.
Rationale: comments were proven public without login; old session refresh alerts must not imply an
active collector. Exclusive authentication MCP handlers can disappear without changing storage.

## R4 — Vocabulary and historical measurement metadata
Decision: remove unused probe/suggest registration dependencies while retaining seed SQL and template
domain exclusions. Keep historical channel ordering, sampled-unit metadata, supply qualification
platforms and template sections used to render older observations. Mark their purpose in code.
Rationale: those are readers, not source discovery. Deleting historical labels or seeds is neither
necessary nor safe evidence preservation. No migration is introduced.

## R5 — Composition beyond MCP
Decision: retire setup's RSS readiness probe and sample generator registrations as well as MCP
composition. Search tools, health, auth and vocabulary consumers are enumerated in plan.md.
Rationale: only changing MCP initialization leaves other entry points advertising dead collection.

## R6 — Surviving keyword pain-point tool
Decision: preserve the name and parameters, but refuse with `BLOCKED / SURFACE_RETIRED`
before components or quota. FR-001 permits unchanged signatures with a typed refusal required by
FR-003. No new search or URL-selection feature is inferred from the retirement request.

## R7 — Distribution and verification
Decision: runtime tools are authoritative; freeze surviving schemas before edits, regenerate Hermes
catalogs using the existing script, and update every governed count and smoke fixture to 42.
Rationale: hand-editing generated schemas can hide drift. Use only fake platforms and temporary
SQLite. PostgreSQL checks stay in CI; no live probe repeats the owner's already-settled decisions.

## R8 — Removal boundary and retained modules
Remove the eleven exclusive MCP wrappers/handlers, their OAuth/status helpers, the keyword
pain-point acquisition body, four composition registrations, setup RSS probe, sample registrations,
and vocabulary wiring. Keep dormant `google_trends/rss_plugin.py`, `tiktok/creative_center_plugin.py`
and `reels/reels_plugin.py` for offline legacy parser/conformance fixtures; no shipped composition
constructs them. Their acquisition methods have no production caller. Whole-file deletion is not
required by FR-002 and would also remove those parser fixtures. `TikTokPlugin` remains shared by
URL comments and legacy parser tests; its keyword helpers have no production caller after the
pain-point refusal. Shared browser/navigation, credential storage and identity helpers stay.

The source-map HTML/SVG/PNG is a dated 29/09/2026 historical diagram, already excluded from current
README embeds by `test_public_doc_conventions`. No replacement diagram is added. Report templates
retain old platform colors, Macro Radar and suggestion sections for historical rendering; no
template issues collection calls. `server.json` has no tool list/count and needs no byte change.
