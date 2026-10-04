# fn-ignis

Ignis is a self-hosted, mission-bound social market research harness. It helps people collect
inspectable evidence from accessible social sources, then challenge a market hypothesis before
acting on it. Its two capabilities are independent: source collection can end with an evidence
frame, while Market analysis can end with a Gap Report rather than a forced verdict.

**Release boundary:** This branch implements the unreleased Spec 011 product reset. The published
v0.7.0 source and image are historical Dual-Track artifacts; they do not expose the 44-tool
mission-bound surface described here. Do not use a published image to validate this branch.

## Product contract

Ignis starts only for an explicit source probe or confirmed research mission. It does not run a
worker, daily discovery, or unattended baseline. A mission records the question, scope, sources,
stopping rule, and collection outcomes. Analysis follows Outcome, Design, and Critical thinking:
define the decision, inspect the user's context, seek disconfirming evidence, and report gaps.

Market verdicts require a current qualified evidence frame and persisted Claim Ledger. Every
rendered claim must identify its observations, contrary evidence, limitations, and conditions
that would change it. Missing or unavailable channels are not zero demand. Uploaded or purchased
datasets are context unless they acquire mission-scoped provenance and qualification. See
[Spec 011](specs/011-evidence-grounded-product-reset/spec.md) and its
[public contract](specs/011-evidence-grounded-product-reset/contracts/mission-bound-public-surface.md).

## Local source setup

Requirements: Python 3.11 or newer. Run `./scripts/bootstrap.sh` from a source checkout. It
creates a local virtual environment and SQLite database, seeds the local vocabulary, configures
supported MCP clients, and runs synthetic diagnostics. Connector credentials and real social
sessions are optional and require the operator's own authorization. Never interpret synthetic
readiness as live source access.

For a Codex-only installation with separate UAT storage, run
`./scripts/bootstrap.sh --client codex --env-file /absolute/path/to/uat/.env`.
Other client configurations remain unchanged; omitting these options retains the all-client setup.

The current source tree contains migrations through
`sql/026_partial_degraded_probe_outcomes.sql`. Migration 026 changes only the outcome-count
constraint: partial DEGRADED results remain incomplete measurements. A fresh SQLite bootstrap is exercised locally;
PostgreSQL migration rehearsal on a disposable database does not verify an operator's existing
database. For an existing database, inventory
legacy baseline rows with `python scripts/inventory_legacy_baseline.py --dsn sqlite:///ignis.db`
or an explicit existing PostgreSQL DSN before planning any migration or
archive. Apply only pending numbered migrations in order after reviewing the migration's data impact and
the operator's approval. The previous files include `sql/022_builtin_uuid_defaults.sql`,
`sql/023_evidence_qualification.sql`, `sql/024_youtube_quota_ledger.sql`, and
`sql/025_evidence_grounded_claim_ledger.sql`.
Do not rerun historical 025 after partial DEGRADED rows exist: it reinstalls the stricter count
CHECK before 026 can run. Replay verification for 026 is not whole-history replay verification.

The published OCI image and manifest still refer to v0.7.0. Build and run this source branch
locally for Spec 011 validation; do not assume the public image includes `025` or the new tools.
PyPI publication is not advertised. Runtime HTML output belongs in gitignored `reports/`; the
committed report templates live only in `src/ignis/infrastructure/templates/html/`.

## Agent capabilities

The current MCP server exposes **44 tools**. Use the server's live tool descriptions as the
signature authority. Representative operations:

- `create_attention_mission` and `confirm_market_brief` establish a bounded question and
  confirmed scope; `execute_mission_ingress` collects the requested frame.
- Atomic source tools such as `get_tiktok_search_suggestions` and
  `get_tiktok_video_comments` can answer source-specific questions without a Market verdict.
- Opt-in `prepare_host_browser_search`, `submit_host_browser_search` and
  `cancel_host_browser_search` collect bounded public TikTok grids through an authorized host
  browser. See [host-browser scope and limits](docs/USER_GUIDE.md#explicit-host-browser-tiktok-search-development-branch).
- `get_mission_evidence_qualification_batch` and
  `submit_mission_evidence_qualifications` record evidence judgments.
- `submit_mission_claims`, `get_mission_claims`, and `get_mission_analysis` control
  current-frame claims and the Gap Report. `generate_mission_artifact` exports an HTML report
  when requested.

Agent instructions are in [AGENTS.md](AGENTS.md). The separate
[collection](.agents/skills/ignis-collect/SKILL.md) and
[analysis](.agents/skills/ignis-analyze/SKILL.md) skills define the human-facing methods.
The [user guide](docs/USER_GUIDE.md) covers the current source workflow. Historical v0.7.0
diagrams and the published release remain available through the v0.7.0 Git tag; they are not
diagrams of this branch.

## Verification and release status

Run `.venv/bin/pytest tests/unit/` for the local unit gate and `uv lock --check` for lock
consistency. A passing local gate does not mean this branch is merged, packaged, published, or
deployed. The pilot and release gates are tracked in
[Spec 011 tasks](specs/011-evidence-grounded-product-reset/tasks.md). No release version is
bumped by this development branch.

## License

See [LICENSE](LICENSE).
