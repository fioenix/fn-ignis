# fn-ignis Agent Bundle

This bundle configures an MCP client for the source checkout. Run `./bundle/install.sh` from
the repository root, or use `uv run python -m ignis.interfaces.cli.setup_bundle`.

The unreleased Spec 011 source branch provides 41 tools for explicit social-source probes
and mission-bound Market analysis. It does not start a worker, daily discovery, or recurring
baseline. Use the live MCP tool descriptions for exact signatures, the
[collection skill](../.agents/skills/ignis-collect/SKILL.md) for bounded evidence collection,
and the [analysis skill](../.agents/skills/ignis-analyze/SKILL.md) for qualified claims and
Gap Reports. A saved HTML report is optional and comes from `generate_mission_artifact`.

The public v0.7.0 bundle and image predate this reset. Installing a client configuration
does not prove live connector access or imply that Spec 011 has been published. See the
[source user guide](../docs/USER_GUIDE.md) and [task ledger](../specs/011-evidence-grounded-product-reset/tasks.md).
