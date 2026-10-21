# Quickstart: Validating No Author Identity at Rest

Run from the repository root with the project virtual environment. No real platform session or
token is used.

## 1. Conformance (SC-001, SC-007)

```bash
.venv/bin/pytest tests/integration/test_author_identity_conformance.py -q
```

Expected: the sentinel fixture mission passes with zero sentinel values in every table, research
file, report, MCP response and captured log; the leaking negative-control connector fails the
check; the coverage test confirms every registered connector has a fixture. The PostgreSQL variant
uses the existing dual-backend fixture, which skips without `IGNIS_TEST_POSTGRES_DSN`; the skip is
reported.

## 2. Markers and concentration (SC-002, SC-003)

```bash
.venv/bin/pytest tests/unit/test_author_marker.py -q
```

Expected: ten thousand fixture authors give an exact distinct count; the same authors in two
missions share no marker; a missing encryption key yields `UNAVAILABLE` and a visible limitation.

## 3. Declared accounts and mentions (SC-009, User Story 3)

```bash
.venv/bin/pytest tests/integration/test_declared_accounts.py -q
```

Expected: identity kept only for declared accounts, rendered by declared name; undeclared
business-labelled accounts keep none; withdrawal removes the name from reports and mentions.

## 4. Unverifiable sources (SC-010)

```bash
.venv/bin/pytest tests/unit/test_unverifiable_source.py -q
```

Expected: such observations are kept, counted and shown, and a claim resting only on them is
withheld on SQLite and refused by the PostgreSQL trigger when a DSN is available.

## 5. Parity of analysis (SC-008)

```bash
.venv/bin/pytest tests/integration/test_author_identity_parity.py -q
```

Expected: an existing mission fixture yields the same claims, permissions and Gap Report outcome
before and after the policy, apart from removed author fields.

## 6. Legacy inventory (SC-006)

```bash
.venv/bin/python scripts/inventory_author_identity.py --sqlite path/to/canonical.sqlite3
```

```bash
.venv/bin/python scripts/inventory_author_identity.py --database-url-env DATABASE_URL
```

Expected: JSON with counts per store, table and field; no identity value printed; zero writes
(verified by file modification time for SQLite and a read-only transaction for PostgreSQL).

## 7. Full regression

```bash
.venv/bin/pytest tests/
```
