# Quickstart: Validate Decision-Grade Evidence Qualification

This guide proves the feature contract after implementation. It uses deterministic fixtures for
semantic outcomes; no live connector, AI provider, or production database is required.

## Prerequisites

- project dependencies installed with `uv sync --locked --all-extras`;
- a clean temporary workspace for generated research folders;
- Docker only when a local PostgreSQL contract database is needed; and
- `IGNIS_TEST_POSTGRES_DSN` pointing to a server where the test harness may create and drop scratch
  databases for dual-backend parity.

Never use a production DSN. The test harness must mint a uniquely named scratch database and verify
its removal afterward.

## 1. Prove cold-start parity

Run the cold-start contract:

```bash
.venv/bin/pytest tests/integration/test_decision_grade_evidence.py \
  -k "cold_start" -q
```

Expected:

- the first mission after process construction synchronizes persisted probe templates and noise
  vocabulary before any connector call;
- the warm control invokes the same connector surfaces with the same registered vocabulary; and
- a synchronization failure calls no connector and returns a structured failure.

## 2. Prove unsupported Market evidence fails closed

Run the semantic negative controls:

```bash
.venv/bin/pytest tests/integration/test_decision_grade_evidence.py \
  -k "keyword_noise or insufficient_market" -q
```

The fixture includes film, sports, lottery, and unrelated news titles that repeat a Market probe
keyword. Submit them as excluded or context-only through the real MCP handlers.

Expected:

- qualification counts preserve every raw observation;
- no excluded/context/unassessed observation reaches a Market conclusion citation;
- `analysis_status` is `INSUFFICIENT_RELEVANT_EVIDENCE` after assessment;
- `opportunity_index_applies` is false; and
- no saturation, whitespace, or demand-gap verdict is emitted.

## 3. Prove the positive Market control still works

```bash
.venv/bin/pytest tests/integration/test_decision_grade_evidence.py \
  -k "qualified_market_control" -q
```

The control supplies one qualified demand observation and two qualified supply observations from
two canonical sources.

Expected:

- only the qualified topic receives an Opportunity Index;
- all conclusion citations point to qualified evidence for the same Brief revision;
- repeated sightings of one canonical source count once for source independence; and
- context-only and excluded observations remain inspectable but do not change the verdict.

Run the measured-zero control separately. It must use two persisted healthy-empty supply surfaces;
one empty plus one failed/rate-limited/auth-required surface is insufficient.

## 4. Prove Attention refuses a fallback candidate

```bash
.venv/bin/pytest tests/integration/test_decision_grade_evidence.py \
  -k "attention_handoff" -q
```

Expected:

- a noise-only/adjacent fixture returns `NO_QUALIFIED_CANDIDATE`;
- a positive fixture exposes only a directly relevant cluster backed by two source ids; and
- Attention never emits an Opportunity Index in either case.

## 5. Prove qualification history and revision isolation

```bash
.venv/bin/pytest tests/integration/test_decision_grade_evidence.py \
  -k "reopen or revision or evidence_replacement" -q
```

Expected:

- reopening a completed mission reads the same persisted judgments without an evaluator call;
- a new Brief revision starts with zero qualifications and cannot reuse the prior mission's rows;
- pruning mission evidence removes only its associated qualification;
- newly collected evidence returns the mission to `QUALIFICATION_REQUIRED`; and
- batch validation is atomic when one observation or frame fingerprint is invalid.

## 6. Prove artifact parity

```bash
.venv/bin/pytest tests/unit/test_data_provenance.py \
  tests/unit/test_html_builder.py -q
```

Expected:

- MCP payload and HTML show the same question-relevance score and qualification counts;
- a withheld Market verdict renders no Opportunity Index card or chart; and
- Attention renders the no-qualified-candidate state without presenting it as a market failure.

## 7. Prove both storage backends

Without `IGNIS_TEST_POSTGRES_DSN`, only SQLite evidence is valid and PostgreSQL cases must report as
skipped rather than green.

With a scratch-capable DSN:

```bash
IGNIS_TEST_POSTGRES_DSN='<redacted>' \
  .venv/bin/pytest tests/integration/test_decision_grade_evidence.py -q
```

Expected: every contract runs once on SQLite and once on PostgreSQL, with no PostgreSQL skip.

Then run the full parity suite:

```bash
IGNIS_TEST_POSTGRES_DSN='<redacted>' .venv/bin/pytest tests/integration/ -q
```

Report exact pass/skip/fail/error counts and confirm that every remaining skip belongs to a
deliberately backend-specific case.

## 8. Rehearse migration and package contents

Run the migration contracts against a throwaway PostgreSQL server and fresh Compose database:

```bash
IGNIS_TEST_POSTGRES_DSN='<redacted>' \
  .venv/bin/pytest tests/integration/test_postgres_migration_contract.py -q

IGNIS_TEST_COMPOSE_INIT=1 \
  .venv/bin/pytest tests/integration/test_compose_init.py -q
```

Expected:

- migration `023` creates both tables with RLS, constraints, foreign keys, and owner-only access;
- applying `023` twice is idempotent;
- no existing source, observation, mission evidence, mission, Brief, or journal row changes;
- Compose applies every SQL file through `023` in filename order; and
- cleanup leaves no scratch database, role, container, volume, network, or credential file.

Verify package contents and local gates:

```bash
.venv/bin/pytest tests/unit/ -q
.venv/bin/ruff check src/ tests/ scripts/
git diff --check
uv lock --check
uv build
```

The wheel and source distribution must contain migration `023`. Do not bump a version, tag, push,
merge, or migrate a persistent database as part of feature implementation.
