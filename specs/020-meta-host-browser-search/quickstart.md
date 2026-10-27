# Quickstart Validation: Spec 020

Future implementation guide; this planning run changes no runtime code or collection state.
Owner Gates in [plan.md](plan.md#owner-gates) precede dependent work. Payloads are in
[contracts/mcp-surface.md](contracts/mcp-surface.md) and [data-model.md](data-model.md).
No credential/env-file reads, installs, live database, browser or routine changes during planning.
New test files below are planned, not yet present.

## 1. Targeted source checks after implementation

Use checkout source rather than the shared non-editable wheel:

```bash
PYTHONPATH="$PWD/src" /Users/fioenix/Projects/fn-ignis/.venv/bin/pytest -q -p no:cacheprovider tests/unit/test_repo_conventions.py tests/unit/test_host_browser_search.py tests/unit/test_host_browser_relay.py tests/unit/test_threads_host_answer_validation.py tests/unit/test_browser_launch_flag_policy.py tests/unit/test_collection_path_comparability.py tests/unit/test_watchlist_period.py tests/unit/test_watchlist_seen_axis.py
PYTHONPATH="$PWD/src" /Users/fioenix/Projects/fn-ignis/.venv/bin/pytest -q -p no:cacheprovider tests/integration/test_threads_host_dom_contract.py tests/integration/test_host_browser_search_mcp.py tests/integration/test_host_browser_mission.py
rg -n -- 'AutomationControlled' src
```

Expect selected tests pass; rg finds no matches (exit 1). Inspect actual mocked args at every retained
launch, not text deletion alone. Run changed Threads/Meta/TikTok/registry cases in research R8;
prove Reels healthy result and unavailable blocked page. No full-suite run requested.

## 2. Backend and package parity

Use existing dual-backend fixtures with disposable PostgreSQL and approved injected
IGNIS_TEST_POSTGRES_DSN; never read/print value or source an env file:

```bash
PYTHONPATH="$PWD/src" /Users/fioenix/Projects/fn-ignis/.venv/bin/pytest -q -p no:cacheprovider tests/integration/test_meta_host_evidence_backend_parity.py tests/integration/test_watchlist_period_storage.py tests/integration/test_author_identity_parity.py
PYTHONPATH="$PWD/src" /Users/fioenix/Projects/fn-ignis/.venv/bin/pytest -q -p no:cacheprovider tests/unit/test_vocabulary_loader.py tests/unit/test_sql_packaging.py tests/unit/test_tool_manifests_drift.py tests/unit/test_public_mcp_contract.py
```

Both backends: 036 seed-only/idempotent, no schema/evidence rewrite; identity/alias; sanitized
observations/associations; exact clocks; counter precision; observation and zero-probe path JSON;
changed/mixed/unknown/equal-path comparisons on both axes; stale/caller/writer guards; complete
manifest outcomes and sibling-host single-run composition. Skipped PostgreSQL is pending, not parity.

Regenerate prescribed manifests during implementation; verify installed wheel contains JS/handoff/
SQL and exact 53 tools, prepare source default TikTok. Read scripts/wheel_mcp_smoke.py supported
help before invoking, not an invented command. No version bump, commit or publication here.

## 3. Browser acceptance (separate explicit live authority)

Obtain bounded Threads/Reels session and G3 run authority; leave routine unchanged (FR-009).
Confirm actual intended connected owner profile with supported host tools. No credentials exported,
fallback browser or account interaction. Stop at transport denial or missing authority.

1. Prepare tactical Threads, open relay's exact query control, run packaged script, stage via
   postMessage and existing submit. Where browser visibly has results, obtain cleaned body record,
   identity-free link, exact publication, raw rounded counts, query/capture and host path. No manual
   reconstruction or JSON repair.
2. Controlled fixtures/host tests: two queries, wrong query/origin/window, no vocabulary, expiry,
   replay/cancel, loading/shell/challenge, all-content-dropped. No failure becomes measured zero;
   preserve owner tabs/browser and stop new navigation at terminal states.
3. Run authorized G3 once through implemented Ignis-to-host flow with TikTok sibling tickets and
   remaining channels in one run. Read back canonical observations, outcomes, frame and periods;
   identity conformance finds zero leaking author values without displaying them. Manual G2 or a
   fixture does not prove FR-011/SC-001/SC-002. No routine change is part of the run.
4. Separately run live flag-free Reels: observation or unavailable with blocking reason; zero parsed
   cards cannot imply EMPTY_NO_DATA. This independently proves SC-006.
5. Controlled complete periods: old/new, mixed within period, unknown, empty-with-path, equal path.
   Both axes refuse changed/mixed/unknown with reason; keep cadence, publication/ingestion placement,
   unrelated channels and once-per-topic dedup with query lineage.

Record sanitized IDs/versions/status/count/limitations/readback, never raw author URLs/identities,
tokens or credential material. Report each unverified live/transport/backend gate explicitly.

## 4. Eventual Threads MCP

Today no approved grant exists: test missing-grant, SELF_ONLY and NOT_PERMITTED exclusion with
fixtures; do not call live API or submit App Review. After actual grant and explicit run authority,
prove external keyword execution and supported structured value transfer into existing relay form.
Validate actual provider contract, exact query/time/content/precision and sanitized readback. API
must take precedence; period shows host→API discontinuity. API failure does not fall back to browser.
If grant/transport/composition is unproved, keep API activation pending, do not invent a tool or
relax the relay. Browser readiness and eventual API readiness are separate acceptance gates.
