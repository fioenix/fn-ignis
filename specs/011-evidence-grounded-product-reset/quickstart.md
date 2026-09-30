# Quickstart: Validate the Evidence-Grounded Product Reset

This is a verification guide for the future implementation. Commands name the intended test
surfaces; they are not proof until the implementation phase creates and passes them.

## Prerequisites and setup

- Run from the repository root on the implementation branch for Spec 011.
- Use a bootstrap-created `.venv` with development dependencies installed.
- Keep connector credentials absent for deterministic contract tests; use only synthetic fixtures.
- Configure the repository's PostgreSQL test fixture only for the explicit parity scenario.

```bash
./scripts/bootstrap.sh
.venv/bin/python -m pytest --version
```

Do not use a real TikTok, Threads, or Instagram session during this quickstart. The five real pilot
missions have a separate explicit-authorization gate.

## 1. Prove idle means zero work

```bash
.venv/bin/pytest tests/integration/test_mission_bound_idle.py -q
```

Expected: no connector call, writer claim, journal entry, alert, digest, scheduled task, or report is
created without an explicit request.

## 2. Prove tactical collection remains independent

```bash
.venv/bin/pytest tests/integration/test_tactical_collection_contract.py -q
```

Expected: an atomic source-specific probe returns observations and a channel state without creating
a Market Brief, strategic verdict, or follow-up run.

## 3. Prove a sufficient Market mission preserves contradiction

```bash
.venv/bin/pytest tests/integration/test_evidence_grounded_market_mission.py -q -k sufficient
```

Expected: the mission persists alternatives, null hypothesis, falsifiers, kill criteria,
contradictory evidence, a ready sufficiency decision, and claims bound to the current frame.

## 4. Prove fail-closed gap states

```bash
.venv/bin/pytest tests/integration/test_evidence_grounded_market_mission.py -q \
  -k 'auth_blocked or low_relevance or missing_metric'
```

Expected in all three cases: a Gap Report identifies the failed gate and smallest next probe;
Opportunity Index, whitespace, saturation, demand-gap, and commercial verdicts are absent.

## 5. Prove channel-state semantics

```bash
.venv/bin/pytest tests/unit/test_mission_probe_outcomes.py -q
```

Expected: only an exact-frame `EMPTY_NO_DATA` can represent measured absence. Authentication,
rate-limit, degraded, failed, and not-requested states never become zero.

## 6. Prove the breaking public surface

```bash
.venv/bin/pytest tests/unit/test_public_mcp_contract.py -q
```

Expected: all eight removed operations are absent; no alias or redirect exists; retained atomic and
workspace mission tools remain enumerable; the two Claim Ledger operations are present.

## 7. Prove both persistence modes

```bash
.venv/bin/pytest tests/unit/ -q
.venv/bin/pytest tests/integration/test_evidence_grounded_persistence.py -q
```

Run the integration contract once against SQLite and once against the repository's PostgreSQL test
fixture. Expected: identical required fields, uniqueness, foreign keys, check constraints, cascade
semantics, frame invalidation, and claim statuses.

## 8. Prove baseline disposition is dry-run first

```bash
.venv/bin/pytest tests/integration/test_legacy_baseline_inventory.py -q
```

Expected: the inventory classifies explicit records as archive candidates or deletion candidates,
produces a recoverable target manifest, changes no data, and never promotes a baseline record into
mission evidence.

Actual deletion is a separate owner-authorized operation with target readback and post-action
verification. It is not part of this plan or its default test run.

## 9. Run repository gates before claiming implementation complete

```bash
.venv/bin/pytest tests/unit/test_repo_conventions.py -q
.venv/bin/pytest tests/unit/ -q
uv lock --check
python -m build
git diff --check
```

The implementation is still not shipped until the breaking change is merged, released under an
owner-approved version, installed from the public surface, and verified there.
