# Quickstart Validation: Spec 020

Automated checks below cover the accepted browser-only implementation. They do not prove live
account readiness. The owner decision in [plan.md](plan.md#owner-decision-27102026) overrides
older proposed API clauses in the contracts. Do not read credentials or existing env files,
change the G3 routine, activate Threads API access or claim a repaired channel.

Prepare accepts optional `source="threads"`; omission retains `source="tiktok"`. Submit and
cancel still accept only request/task/session IDs, and the public catalog remains 53 tools.
Threads internal Playwright collection is removed. Reels retains flag-free Playwright.

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
   cards cannot imply EMPTY_NO_DATA. A verified empty, well-formed captured search envelope can
   return EMPTY_NO_DATA for the executed keyword only. This independently proves SC-006.
5. Controlled complete periods: old/new, mixed within period, unknown, empty-with-path, equal path.
   Both axes refuse changed/mixed or proven-versus-unknown paths with reason; both unknown
   retains the legacy comparison rules; keep cadence, publication/ingestion placement,
   unrelated channels and once-per-topic dedup with query lineage.

Record sanitized IDs/versions/status/count/limitations/readback, never raw author URLs/identities,
tokens or credential material. Report each unverified live/transport/backend gate explicitly.

## 4. Distribution checkpoint and remaining gates

Build wheel and sdist offline into `.handoff/spec020-dist/` using the existing locked tooling.
Install only that wheel into `.handoff/spec020-wheel-venv/` with approved local dependencies.
Use a newly generated synthetic isolated SQLite configuration. Run the wheel interpreter with no
checkout PYTHONPATH from a separate working directory; prove the imported package belongs to the
wheel venv. Read SQL 036, both source extractors, Threads handoff and relay template from that
installed package. Run `scripts/wheel_mcp_smoke.py` with the same interpreter and configuration:
expect exact 53-tool discovery, optional prepare source default TikTok, unchanged ID-only
submit/cancel, a runtime configuration read, packaged guide read and clean shutdown. Record the
artifact hash, exact commands, output and limits in `.handoff/spec020-verification.md`.
No editable-source fallback, network install or shared-venv mutation is permitted.

T047 is coordinator PostgreSQL parity; skipped local cases do not complete it. T049 is independent
code/security review and T050 is coordinator final verification. T051 (host/G3) and T052 (Reels)
require separate explicit owner approval and actual live readback. Automated fixtures and wheel
smoke complete none of those live gates. The G3 routine remains unchanged.

Threads MCP/API submission, grant probing, App Review and API precedence remain deferred until
approval and a spec amendment. Do not call provider APIs to validate this browser-only increment.
