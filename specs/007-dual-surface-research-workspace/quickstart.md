# Quickstart Validation: Dual-Surface Research Workspace

This guide validates the accepted user contract after implementation. It is intentionally
implementation-light; schema and command details belong in the plan and task artifacts.

## Prerequisites

- A clean checkout with the project environment installed.
- A writable temporary host workspace.
- Core tests use SQLite-local. PostgreSQL parity tests use `IGNIS_TEST_POSTGRES_DSN` when
  configured; no production database or connector credential is required.

## 1. Confirmed workspace creation

1. Ask the Agent to propose a research named `AI customer service` in the current host workspace.
2. Verify that the proposal shows `.ignis/research/ai-customer-service/`.
3. Before confirmation, verify that the child directory, manifest, database, and journal do not
   exist.
4. Confirm creation and verify the manifest exists while the research records are created in the
   configured shared Ignis database under the new `workspace_id`; no per-research database is
   created.
5. Open the workspace through a second supported Agent host connected to the same Ignis database
   and verify the same workspace identity and scoped records.

Expected result: the workspace is addressable across Agent hosts using one shared database, and no
durable workspace write occurs before confirmation.

## 2. Attention-only journey

1. Create an `ATTENTION` mission with geo and timeframe.
2. Run the mission and inspect the ranked topics or clusters.
3. Verify citations, freshness, momentum, and channel status are present.
4. Verify no Market Brief is required and no Opportunity Index is returned.

Expected result: discovery works without a hypothesis and does not make a market claim.

## 3. Direct Market journey

1. Start a `MARKET` request without an Attention parent.
2. Complete the adaptive Q&A, one question at a time.
3. Attempt execution before all seven Brief fields are complete.
4. Verify execution is blocked and missing fields are named.
5. Complete and edit the draft, then explicitly confirm it.
6. Run the Market mission and inspect the evidence, falsifiers, Opportunity Index, and next
   validation plan.

Expected result: only a confirmed Brief authorizes Market probes, and only Market emits an
Opportunity Index.

## 4. Attention-to-Market handoff and revision

1. Select one Attention topic for investigation.
2. Verify a separate Market draft records the Attention mission and cluster as context lineage.
3. Confirm the Brief and run Market probes.
4. Change the hypothesis or another required Brief field.
5. Verify a new immutable Brief revision and Market mission are created.
6. Verify the old mission and its evidence links are unchanged and are not silently counted as
   support for the new hypothesis.

Expected result: the handoff preserves context while the Market mission remains independently
evidenced.

## 5. Concurrency and recovery

1. Start two different missions in the same workspace concurrently.
2. Verify both retain their own state and evidence.
3. Start two runs for the same mission and verify one creates a new revision or fails clearly.
4. Freeze the run clock so two runs start in the same second.
5. Verify distinct fixed-width journal identities and unchanged earlier journal bytes.

Expected result: no mission state or run journal is lost through a collision or whole-file
overwrite.

## Automated checks

The implementation should provide targeted tests for the scenarios above, then run:

```bash
.venv/bin/pytest tests/unit/
.venv/bin/pytest tests/integration/
.venv/bin/ruff check src tests
git diff --check
```

Any PostgreSQL-dependent test that cannot run without `IGNIS_TEST_POSTGRES_DSN` must be reported
as skipped rather than described as full-green coverage.
