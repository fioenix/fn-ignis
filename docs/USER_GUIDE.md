# Ignis User Guide — Spec 011 source branch

This guide describes the unreleased mission-bound source branch, not the published v0.7.0
image. The v0.7.0 Dual-Track worker and its diagrams are historical and do not describe this
branch. See [README](../README.md) for the product contract and release boundary.

## 1. Start and inspect

Use Python 3.11 or newer. From a source checkout, run `./scripts/bootstrap.sh`. It provisions
local SQLite and an MCP client configuration, then runs synthetic diagnostics. Inspect the
diagnostic result for each connector; a configured client or synthetic check is not proof of
live social access. Supply credentials or browser sessions only for the exact source and
research task you authorize. Never place a secret in a prompt, command transcript, or report.

The source migration chain ends at `sql/025_evidence_grounded_claim_ledger.sql`. Fresh local
SQLite initialization has been exercised. Applying `025` to PostgreSQL has not yet been
verified. For an existing database, run
`python scripts/inventory_legacy_baseline.py --dsn sqlite:///ignis.db` or pass an explicit
existing PostgreSQL DSN to
inspect legacy baseline content read-only. Do not delete or migrate it merely because the
new workflow does not use it. Review and approve any data transformation before applying the
numbered migrations in order. Earlier files include `sql/022_builtin_uuid_defaults.sql`,
`sql/023_evidence_qualification.sql`, and `sql/024_youtube_quota_ledger.sql`.

## 2. Choose the task

For a single source question, ask the agent for an atomic probe and specify a query, geography,
time window, and stop condition. The response should identify the source, request, collection
time, observed count, and channel state. It need not open a Market mission or produce a verdict.

For a market decision, state the decision you face, target audience, geography, time window,
hypothesis, plausible alternative, and what observation would change your mind. The agent
creates an Attention mission or confirms a Market Brief with you before collecting. Once the
scope is confirmed, `execute_mission_ingress` runs only that mission's plan. There is no daily
worker or unattended collection.

The [collection skill](../.agents/skills/ignis-collect/SKILL.md) is the method for gathering
an inspectable frame. The [analysis skill](../.agents/skills/ignis-analyze/SKILL.md) is a
separate method for testing the Market hypothesis. Ask for either or both.

## 3. Understand evidence and analysis

Ignis records a channel outcome for every requested source. `HEALTHY`, `EMPTY_NO_DATA`,
`AUTH_REQUIRED`, `RATE_LIMITED`, and `DEGRADED` are not interchangeable: an inaccessible
channel is a coverage gap, not proof that the market is empty. The agent reviews an evidence
qualification batch, records typed support, contradiction, or context judgments, and checks
that the current frame is terminal before making Market claims.

Each strategic statement belongs in the persisted Claim Ledger. `submit_mission_claims`
binds it to observations or eligible measured absence, and `get_mission_claims` shows whether
it may be rendered. `get_mission_analysis` must return only permitted current-frame claims.
If coverage, qualification, or claims are insufficient, it returns a Gap Report with safe
partial observations and the smallest useful next probe. A numeric score or raw signal is
not a substitute for that gate.

Uploaded files and purchased datasets can help phrase a question or identify a competitor.
Without mission-scoped provenance and qualification, they remain context rather than primary
Market evidence. The analysis should show disconfirming evidence and state when its conclusion
would change. Export HTML with `generate_mission_artifact` only when a saved report is wanted;
runtime output goes to gitignored `reports/`, while templates live in
`src/ignis/infrastructure/templates/html/`.

## 4. Tool and deployment boundaries

The local MCP server exposes **41 tools**. Discover the running server's descriptions for exact
signatures; removed daily-discovery and unguided-research tools are not part of this branch.
The published OCI manifest is still v0.7.0, so neither it nor a public-image smoke test
establishes that Spec 011 shipped. PyPI installation is not advertised. Run the branch's
`.venv/bin/pytest tests/unit/` and `uv lock --check` for local checks, then consult
[the task ledger](../specs/011-evidence-grounded-product-reset/tasks.md) for the outstanding
PostgreSQL, pilot, integration, and owner-controlled release gates.
