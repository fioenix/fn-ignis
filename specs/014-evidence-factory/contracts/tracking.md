# Tracking Contract (R2)

**Status**: Drafted with the R2 plan on 2026-10-19; not implemented. Supersedes the viewer parts of [relay-viewer.md](relay-viewer.md). Requirements: FR-005–FR-008, FR-014, FR-016, FR-024, FR-026, FR-030, FR-031.

## Snapshot read — existing, unchanged

`get_mission_relay_snapshot(mission_id, page_size, run_id?, after_revision?, after_ordinal?, evidence_offset?)` keeps its current signature, bounds and typed refusals, as documented in [relay-viewer.md](relay-viewer.md) "MCP read operations" and "T001 resource limits". It requires a resolved caller root ([caller-root.md](caller-root.md)). It never opens a browser, starts collection or writes mission state.

The display states an artifact may show come only from snapshot fields; the mapping is in [data-model.md](../data-model.md) "Tracking artifact".

## `ignis-track` delivery

One maintained source: `src/ignis/interfaces/mcp/guides/ignis_track.md`, shipped in the wheel.

| Surface | Identifier | Arguments | Returns |
|---|---|---|---|
| MCP prompt | `ignis_track` | optional `mission_id` | The guide, with the mission ID filled in when given |
| MCP resource | `fn-ignis://guide/ignis-track` | none | The guide verbatim |
| Repository skill | `.agents/skills/ignis-track/SKILL.md` | none | Frontmatter plus the guide body; a test asserts the body equals the packaged source |

Serving the guide starts no read, collection or write.

## Required guide content

1. **Read**: select one mission explicitly; call the snapshot with an explicit `page_size`; page events with the returned cursor pair and evidence with `evidence_offset`; treat any typed refusal as a failed read, never as empty data.
2. **When to generate**: on a user request, or at a milestone inside the agent's own active turn (collection settled, qualification recorded, claim or gap changed, research work ended). No polling, timers or scheduled refresh; nothing after the turn ends.
3. **What to show**: mission, run, `read_at`, frame or pending reason, collection state, channel outcomes, claim gate, work and finding revisions, totals with the page shown. Every artifact states that it is a point-in-time snapshot.
4. **Display rules**: the table in [spec.md](../spec.md) "Tracking artifact guidance (R2)", plus: show `reason_code` for withheld claims; never render a withheld or stale claim as permitted; never turn an unavailable channel into zero demand; never add metrics, confidence or activity absent from the snapshot; colour always carries a text label; all essential content readable without scripts, motion, fonts or network.
5. **After a failed read or a frame change**: the next artifact withdraws current permission from earlier claims and labels the last successful read as stale.
6. **Where it goes**: write a local file by default. Before publishing to any host or service off the user's machine, ask the user for that specific publication.

## Out of scope

Rendering templates, layout choices and host-specific artifact formats. The constitution's maintained-template rule applies to Ignis research reports, not to these artifacts, once the R2-4 amendment is executed.
