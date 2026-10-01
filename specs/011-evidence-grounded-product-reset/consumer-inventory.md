# Consumer Inventory: Evidence-Grounded Product Reset

**Captured**: 2026-09-30
**Base commit**: `483308ca9106710e3b4bbc3792396626cf313a0b`
**Purpose**: Freeze the live public and runtime consumers before the breaking cutover. Historical
specs and backlog entries remain historical records; they are not rewritten as current guidance.

## Public MCP baseline

`mcp.list_tools()` returns **47** operations on the base commit. The following eight operations are
the approved removal candidates, pending the separate owner signature gate:

| Operation | Required parameters | All parameters |
|---|---|---|
| `run_autonomous_research_mission` | `topic`, `keywords` | `topic`, `keywords`, `geo`, `timeframe`, `min_signals` |
| `create_research_mission` | `topic`, `keywords` | `topic`, `keywords`, `platforms`, `geo`, `timeframe` |
| `get_trending_topics` | none | `geo`, `timeframe`, `limit` |
| `get_topic_detail` | `topic_id` | `topic_id`, `limit` |
| `generate_trend_artifact` | none | `topic_id`, `geo`, `format` |
| `trigger_ingress_refresh` | none | `geo`, `scope`, `timeframe` |
| `trigger_autonomous_discovery` | none | `geo` |
| `get_latest_daily_discovery` | none | `geo` |

The cutover also plans two additions: `submit_mission_claims` and `get_mission_claims`. If no other
tool changes occur, the resulting inventory is **41** operations.

## Machine-readable public consumers

- FastMCP registrations and handlers: `src/ignis/interfaces/mcp/server.py`
- Hermes catalogs: `hermes_manifest.json`, `.hermes/tools.json`
- OpenClaw summary and count: `openclaw.json`
- Built-wheel inventory check: `scripts/wheel_mcp_smoke.py`
- Manifest parity tests: `tests/unit/test_tool_manifests_drift.py`
- Direct handler consumers: `tests/unit/test_mcp_server.py`, `tests/unit/test_mission_flow.py`,
  `tests/unit/test_graph_artifact.py`, `tests/unit/test_autonomous_discovery.py`

## Worker, scheduler, and recurring-runtime consumers

- Package entrypoints: `pyproject.toml` (`fn-ignis-worker`, `ignis-worker`)
- Runtime module: `src/ignis/interfaces/cli/scheduler.py`
- Compose services: `docker-compose.yml`, `docker-compose.prod.yml`
- Image description: `Dockerfile`
- Runtime settings: `src/ignis/config.py`, `env.example`
- Trigger semantics: `src/ignis/domain/value_objects.py`
- Registry and quota accounting: `src/ignis/infrastructure/connectors/registry.py`,
  `src/ignis/infrastructure/persistence/sqlite_repository.py`,
  `src/ignis/infrastructure/persistence/postgres_repository.py`
- Public-release verification: `scripts/public_release_acceptance.py`
- Tests: `tests/unit/test_scheduler.py`, `tests/unit/test_worker_connector_selection.py`,
  `tests/unit/test_env_example_matches_settings.py`, `tests/unit/test_public_distribution_contract.py`,
  `tests/unit/test_regional_script_gate.py`, `tests/unit/test_registry.py`,
  `tests/unit/test_youtube_quota.py`, `tests/unit/test_youtube_plugin.py`,
  `tests/unit/test_postgres_repository.py`, `tests/integration/test_postgres_migration_contract.py`

## Autonomous discovery and daily artifact consumers

- Use case: `src/ignis/application/use_cases/autonomous_discovery.py`
- MCP handlers: `src/ignis/interfaces/mcp/server.py`
- Direct tests: `tests/unit/test_autonomous_discovery.py`, `tests/unit/test_vocabulary_loader.py`
- Daily output naming: `daily_discovery_<geo>_<date>.html` inside the autonomous-discovery use case

## Trend template consumers

All three legacy trend templates are currently reachable and therefore cannot be deleted merely by
name:

- `trend_dashboard.html` → `HTMLArtifactBuilder.build_trend_dashboard()`
- `trend_graph.html` → `HTMLArtifactBuilder.build_trend_graph()`
- `trend_card.html` → `HTMLArtifactBuilder.build_topic_card()`

The direct callers live in `src/ignis/infrastructure/templates/html_builder.py`,
`src/ignis/interfaces/mcp/server.py`, `tests/unit/test_html_builder.py`,
`tests/unit/test_graph_artifact.py`, and current documentation. Deletion is allowed only after the
eight-operation cutover makes a builder path unreachable and tests prove no retained mission visual
uses it.

## Active documentation and agent-instruction consumers

- `README.md`, `README.vi.md`
- `docs/USER_GUIDE.md`, `docs/USER_GUIDE.vi.md`
- `AGENTS.md`, `CLAUDE.md`, `.codexrules`
- `.agents/skills/fn-ignis-harness/SKILL.md`
- `bundle/README.md`, `server.json`, `openclaw.json`
- `scripts/bootstrap.sh`, `src/ignis/interfaces/cli/setup_bundle.py`
- `BACKLOG.md` for final shipped/not-shipped synchronization

## Historical consumers retained as history

The following documents describe earlier accepted work and remain unchanged except for an explicit
superseded pointer where needed: Specs 004, 005, 009 (public distribution), and 010 (YouTube quota),
plus historical `BACKLOG.md` entries. Rewriting their completed acceptance text would destroy the
reason the old runtime existed.

## Reconciliation findings

1. The initial plan was numbered Spec 009 and migration `024`, but the refreshed live base already
   owns those identities. The feature is now Spec 011 and the planned migration is `025`.
2. The initial task list omitted active consumers in `docker-compose.prod.yml`, `Dockerfile`,
   `scripts/public_release_acceptance.py`, `.codexrules`, and
   `.agents/skills/fn-ignis-harness/SKILL.md`. Their owning tasks now include them.
3. `IngressTrigger.SCHEDULED` also participates in YouTube quota accounting and migration-contract
   fixtures. Removing the worker does not justify deleting audit columns or historical scheduled
   values. Runtime scheduling paths are removed; persisted historical trigger values remain
   readable unless a separately approved evidence migration says otherwise.
4. The legacy trend templates are not currently unreachable. T076 is conditional on the consumer
   audit after MCP removal and must retain any template still used by a mission artifact.
5. The local checkout that started planning was behind the public-release base. All implementation
   decisions and tests use `483308ca9106710e3b4bbc3792396626cf313a0b` as the refreshed base.
