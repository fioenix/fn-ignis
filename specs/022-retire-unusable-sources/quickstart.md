# Offline validation

Prerequisites: current branch `022-retire-unusable-sources`, existing main-checkout `.venv`.
Do not install dependencies, read credentials, open a real store, run Docker/PostgreSQL, or call
platform/browser/network services. All platform calls are fakes; SQLite files live under pytest
temporary directories. Use an allowlisted environment; do not print it.

Before **each** command run `uptime`; wait if its one-minute load is 12 or greater. Run serially,
at most two modules per command, using this form:

```sh
PYTHONPATH=src /Users/fioenix/Projects/fn-ignis/.venv/bin/python -m pytest -q -o addopts='' tests/unit/test_source_retirement.py
```

1. Catalog: expect exactly 41 tools, survivor schemas unchanged, no retired registrations or health
   entries, no saved session read for URL comments.
2. Admission: required and optional retired resources fail before any probe, quota or write.
3. Watchlists: mixed requests report retirement and create survivor-only runs; all-retired requests
   create nothing; stored definitions and historical manifests remain unchanged.
4. Historical reads: temporary rows from retired sources remain visible with their original units,
   platforms and outcomes. Run watchlist period/seen-axis and retained comment contracts.
5. Required final pairs: `tests/unit/test_public_distribution_contract.py` with
   `tests/unit/test_tool_manifests_drift.py`; then `tests/unit/test_public_doc_conventions.py` with
   `tests/unit/test_repo_conventions.py`. Use the command form above for each pair.

Actual commands, RED/GREEN counts and environment blockers belong in
`.handoff/022-verification.md`. PostgreSQL parity and live browser/platform checks are CI/later
operator work, not local acceptance claims. This task grants no release or publication authority.
