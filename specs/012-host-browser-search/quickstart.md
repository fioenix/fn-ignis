# Validation Guide: Host Browser Search

Operations are implemented locally under the approved plan; this guide is not proof of shipping or
current runtime activation. Run live checks only with approved account/surface/query scope.

## Preconditions

- Host supports safe navigation and deterministic DOM evaluation through authorized browser tools;
  otherwise report unsupported and stop.
- Reload actual Ignis MCP connection and inspect live tool discovery. Editable-source changes do not
  prove a running server updated.
- Automated tests use inert environment, synthetic keys and isolated SQLite. Never source real `.env`,
  print credentials or capture secret-bearing exception locals.
- Tactical live gate needs no DB write. Mission gate uses a fresh explicitly scoped local workspace.

## Automated Gates

From modern worktree with sanitized environment:

```bash
.venv/bin/pytest tests/unit/test_repo_conventions.py
.venv/bin/pytest tests/unit/ tests/integration/
.venv/bin/ruff check src tests
git diff --check
```

Cover spec acceptance plus expiry/replay/concurrency, oversize, partial failure, stale revision, writer
conflict, cancellation race and restart. Installed-wheel MCP smoke verifies actual tool schemas and
extractor resource packaging; do not load resources accidentally from checkout. Tasks will name focused tests.

## Tactical Live Round-Trip

1. Prepare through actual Ignis for `túi đi làm` with finite limit/expiry; retain IDs.
2. Use approved Chrome session and task-created tab; navigate exact returned URL and execute packaged
   extractor via supported host APIs, not manual model transcription.
3. Stage the extractor's retained typed JSON through the returned same-origin relay form, then call
   submit with request/task/session references only; read attributable URLs, exact query, capture time,
   host path/version and missingness.
4. Repeat with two approved queries in one batch; verify same session and separate query IDs.
5. Test failure/cancel; unrelated tabs remain intact. Stop and close task-created resources only.

Expect attributable observations when browser shows videos, no Market verdict or invented metrics.
Manual Chrome success without prepare/submit does not pass. Store sanitized proof in `.handoff/`.

## Mission Round-Trip

Fresh isolated mission, confirmed Brief/manifest including falsifiers/full budgets. Do not restart
historical retail mission. Prepare/collect/submit and verify normal run journal, current frame,
source/observation associations and qualification boundaries. Every surface has outcome; unknown
window cannot prove absence.

Change manifest/Brief or run a competing pass before submit: stale result refuses before persistence.
Replay accepted answer: observation counts unchanged. Restart server: old request refuses. Uncertain
write requires journal/frame readback before replacement; no automatic retry.

## Delivery

Record code revision, installed artifact, live inventory and sanitized scope/output. Review code and
security, integrate through approved workflow; release requires separate authorization. Local tests
alone do not mean the bridge shipped or activated.
