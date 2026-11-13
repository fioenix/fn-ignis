# Pull-request CI uses SQLite only

Status: Accepted (owner, chat 2026-11-13)

## Decision

The owner decided in chat on 2026-11-12 that the store is one SQLite file and there is no
production yet. Pull requests wait only on `Secret scan` and `Test & Lint (Python 3.12)`.
The latter keeps lint, the suite without a PostgreSQL DSN, packaging and wheel MCP smoke.

PostgreSQL services, durability tuning, the full suite including `migration_chain`, and the
SC-004 coverage floor move to `PostgreSQL parity (Python 3.12)`, excluded from pull requests.
Parity, fresh Compose initialization and the SC-001 benchmark run on main/release/hotfix
pushes, release tags, weekly schedules and manual dispatch. Existing additional CI push
branches remain covered. The coordinator updates branch protection separately.

## Trade-off

Pull requests spend less time and runner capacity on an unused backend. These are now caught after
merge, on main or by the weekly run, rather than before merge: a PostgreSQL regression (including a
`sql/` change that breaks the migration chain, which the old scope step forced before merge), a drop
below the SC-004 coverage floor, a broken fresh Compose init, and an SC-001 latency regression. A
`workflow_dispatch` run on a pull request's branch still runs all of them before merge when a change
touches PostgreSQL code or `sql/`. Both-backend
storage contracts remain exercised; their timing changes, not their assertions.
