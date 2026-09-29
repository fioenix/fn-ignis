# Quickstart Validation: YouTube Quota Management

## Prerequisites

- Work from the feature branch with an initialized `.venv`.
- Do not use a live YouTube key for validation. Remove `YOUTUBE_API_KEY` from the test process.
- SQLite scenarios require no external service.
- PostgreSQL parity uses the repository's existing scratch-database fixture when available.

## 1. Focused quota contracts

```bash
env -u YOUTUBE_API_KEY .venv/bin/pytest tests/unit/test_youtube_quota.py -q
```

Expected: concurrent admission, 70/30 allocation, Pacific-Time rollover, provider exhaustion, and
diagnostic serialization all pass.

## 2. Connector integration

```bash
env -u YOUTUBE_API_KEY .venv/bin/pytest tests/unit/test_youtube_plugin.py tests/unit/test_registry.py tests/unit/test_scheduler.py -q
```

Expected: cached searches reserve nothing; each uncached search and metrics call reserves before
HTTP; scheduled/requested triggers reach the connector; local refusal makes no HTTP call.

## 3. Migration and conventions

```bash
env -u YOUTUBE_API_KEY .venv/bin/pytest tests/unit/test_sql_packaging.py tests/unit/test_repo_conventions.py tests/unit/test_secret_scanning.py -q
```

Expected: migration 024 is packaged, both backends declare the table, RLS/conventions pass, and no
credential appears in tracked content.

## 4. Full unit gate

```bash
env -u YOUTUBE_API_KEY .venv/bin/pytest tests/unit/ -q
```

Expected: all unit tests pass. Any pre-existing warning is reported separately; no failure is
silently excluded.

## 5. Manual diagnostic readback

With a disposable test database and mocked provider responses, call `verify_connectors_health` and
confirm the YouTube entry matches [contracts/quota-diagnostics.md](contracts/quota-diagnostics.md).
Do not call a live provider solely to prove local admission control.
