# Implementation Plan: Retire Unusable Source Connectors

**Branch**: `022-retire-unusable-sources` | **Date**: 2026-11-10 | **Spec**: [spec.md](spec.md)
**Baseline**: `56f1fd3`; owner decisions: spec Clarifications and accepted source-connection ADR.

## Summary

Expose exactly 41 tools and stop offering or collecting through four retired surfaces. Refuse
new missions and old mission reruns before collection; reduce watchlist run requests without
rewriting their historical evidence. Preserve YouTube, host TikTok/Threads and URL-based TikTok
comments. No migration, real-store access, network, release, branch change or PR is authorized.

## Workflow and depth gate

Source: installed `finolabs-vibecode:fnl-coding-router`, repository Spec Kit skills.
Path: `speckit-plan → speckit-tasks → speckit-implement → speckit-converge`.
Depth: **DEEP**, trigger **consumers**; authentication composition and manifest authority also
require security review. Direct implementation fails the depth gate: catalog/composition,
admission/history, and shipped guidance need ordered seams with distinct acceptance evidence.
The owner explicitly requested tasks and test-first implementation. Jev/live cookbook and
external reviewers are unavailable under the no-network instruction; use deterministic source
inspection, preserve independent-review obligations, and do not claim semantic evaluation ran.
Implementation remains serial: no external delegate/network access, one test command at a time.

## Technical Context

- Python 3.11+, FastMCP, dataclasses, existing pytest/pytest-asyncio; no dependency changes.
- SQLite and PostgreSQL adapters are unchanged; local proof uses temporary SQLite only.
- MCP server and host-browser service; macOS development checkout, portable Python runtime.
- Performance goal: reject retired resources before connector, quota, writer or journal activity.
- Scope: twelve removed tools, four retired collection surfaces, all traced consumers below.
- Tool signatures of the other 41 tools stay byte-equivalent; descriptions may explain refusal.

## Constitution Check

Pre-research and post-design: PASS for I–VII. Explicit bounded ingress remains mandatory (I),
availability stays typed (II), historical evidence and missingness survive (III), report builders
and legacy render fields remain (IV), no new framework/dependency/taxonomy (V), no migration or
release (VI), comments keep author stripping and the self-content guard stays (VII).
Removing MCP tools is explicitly owner-approved. No data transformation or schema change.

## Project Structure and consumer map

| Seam | Exact areas and disposition |
|---|---|
| Catalog/composition | `src/ignis/interfaces/mcp/server.py`: remove twelve decorators, wrappers and exclusive handlers; unregister Google RSS, Creative Center, TikTok grid and Reels. Keep Threads host-required compatibility port and conditional YouTube registration. Instantiate TikTok comments without a stored session. |
| Other composition | `src/ignis/interfaces/cli/setup_bundle.py::run_synthetic_diagnostics`, `scripts/generate_sample_case_studies.py`: remove RSS probe and retired registrations. Never run these live. |
| Health/auth | `diagnose_system_health`, `verify_connectors_health`: active registry only, no retired login remediation or expiry alerts from dormant sessions. Generic auth status/clear keep direct repository behavior and signatures; no automatic deletion. |
| Self-content | `config/vocabulary_loader.py`, `auth/self_identity.py`: retain credential repository and self-identity loading; do not instantiate removed login managers. |
| Vocabulary/ingest | Remove Google probe and TikTok suggest registrations from `VocabularySynchronizer`; retain historical seed rows and exclusion prefixes so `ingest_trends.py::load_seed_keywords` never probes template text. Preserve common language/quality machinery. |
| Admission | `domain/research_workspace.py`, create Attention/Market use cases, `execute_mission.py`, `host_browser_mission.py`, registry execution requirements: one deterministic retired-resource check, invoked before writes/probes; never in manifest deserialization. |
| Watchlist runs | `application/use_cases/watchlists.py`: reduce the caller's resource list; report each removed entry with `SURFACE_RETIRED`; refuse all-retired requests without creating a mission. The stored watchlist model contains topics/brands, not allowed resources: host routines supply authority each run. |
| Historical reads | `domain/watchlist_period.py`: keep `CHANNEL_ORDER` and `SAMPLED_CHANNELS` as historical measurement metadata, not an active connector catalog. `SUPPLY_SURFACE_PLATFORMS` stays for existing evidence qualification. Preserve platform enums, repository reads, channel outcomes and report/template fields. |
| Dead code | Remove exclusive MCP acquisition bodies and registrations. Retain unregistered leaf modules for legacy parser/conformance fixtures and TikTok URL comments; see research R8 for exact retention reasons. Keep shared browser/HTTP, auth storage, identity and cache helpers. |
| Guidance | `.agents/skills/ignis-*`, `src/ignis/interfaces/mcp/guides/`, `docs/agents/`, active README/user guides and templates (the dated source map remains historical): no instruction to invoke retired sources. Historic rendering labels remain. |
| Counts | `AGENTS.md`, `CLAUDE.md`, `openclaw.json`, `server.json`, Hermes catalogs, `scripts/wheel_mcp_smoke.py`, public-distribution fixtures, README pair, user-guide pair, current `BACKLOG.md`; inspect governed tests and CI/setup-generated counts. Generate both Hermes catalogs with `scripts/sync_tool_manifests.py --write`. |

## Execution and validation

1. Freeze survivor schemas; write and observe catalog/composition/diagnostic RED; implement seam.
2. Write admission/reduction RED for required and optional retired resources; implement one policy.
3. Prove old snapshots/manifests/observations/outcomes/sessions survive using temporary fixtures;
   retain historical period fixtures and comments/YouTube/host-browser contracts.
4. Update and regenerate guidance/catalogs; run required public-distribution, manifest-drift,
   public-doc and repository convention modules. Review final diff and converge against tasks.

Every test command starts with `uptime` and runs only with one-minute load <12. At most two
modules per command, serial; use the requested main-checkout Python with `PYTHONPATH=src` and
`-m pytest -q -o addopts=''`. Record exact RED/GREEN commands and outputs in
`.handoff/022-verification.md`. Stop after two failed corrections to one invariant.
Use a clean allowlisted process environment and temporary HOME; never read credential files.
PostgreSQL parity, real browser/platform behavior and external review stay unverified locally.
Commit each complete seam with explicit paths and the requested Co-Authored-By trailer.

## Implementation decisions

- Owner follow-up (2026-11-10): remove `extract_customer_pain_points`, its handler and exclusive
  keyword-to-comments helper; the source-connection ADR forbids blocked placeholders. Preserve
  `get_tiktok_video_comments` and the parameter schemas of all 41 surviving tools. The follow-up
  is one serial NORMAL/contract seam on the existing task path; the broader spec retains its
  DEEP review obligations. No replacement search workflow is added.

## Open

- Independent code/security reviews cannot be represented as completed without a permitted
  reviewer run. They are a later merge gate; no PR or merge is requested here.

## Complexity Tracking

No constitution exception. No migration, new dependency, scheduler, new source or new public tool.
