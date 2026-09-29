# Research: YouTube Quota Management

## Decision 1: Model Google's granular daily buckets

**Decision**: Track `search.list` as a daily call bucket with a default limit of 100 and track all
other endpoints invoked by fn-ignis as a shared daily unit bucket with a default limit of 10,000.
Treat each current `videos.list` call as one unit.

**Rationale**: Google's June 2026 quota model separates `search.list` from the former shared unit
pool. The current code and tests still describe the earlier 100-units-per-search model, so leaving
those constants in place would enforce the wrong capacity. Google's current overview and quota
calculator are the authoritative sources:

- https://developers.google.com/youtube/v3/getting-started
- https://developers.google.com/youtube/v3/determine_quota_cost
- https://developers.google.com/youtube/v3/revision_history

**Alternatives considered**:

- Track only search calls: rejected because health, feed, and metric requests still spend the same key's other bucket.
- Query Google Cloud Console on every admission: rejected because no stable data-plane API is part of the existing product contract and local admission must remain available offline from the console.

## Decision 2: Reserve before HTTP and never refund

**Decision**: Atomically reserve the known endpoint cost before opening the HTTP request. Cache hits
skip reservation. A reservation remains consumed on timeout, invalid request, empty response, or
other failure.

**Rationale**: Google charges attempted requests, including invalid requests. Reserving after the
response creates a race in which multiple processes can all observe the same remaining capacity.
Refunding on local error would undercount provider usage.

**Alternatives considered**:

- Increment after success: rejected because it is neither conservative nor concurrency-safe.
- Lease then commit/refund: rejected because provider charging is not transactional with the local database.

## Decision 3: One row per quota day and bucket

**Decision**: Persist one aggregate row per Pacific-Time day and quota bucket. The row holds total
usage, scheduled usage, an exhausted flag, and timestamps. PostgreSQL admits with a single atomic
upsert; SQLite uses `BEGIN IMMEDIATE` around read/check/write so separate processes serialize on the
database file.

**Rationale**: The product needs admission control and diagnostics, not a billing ledger. Aggregate
rows are sufficient, minimize write volume, and avoid retention policy or cleanup complexity.

**Alternatives considered**:

- Append one immutable row per request: rejected as unnecessary volume and schema complexity for the stated outcome.
- In-memory semaphore/counter: rejected because worker and MCP are separate processes.
- File lock separate from the database: rejected because PostgreSQL deployments and multi-host workers would not share it.

## Decision 4: Pacific-Time day identity, UTC reset output

**Decision**: Compute the quota-day key with `America/Los_Angeles` and expose the next local midnight
converted to UTC.

**Rationale**: Google resets daily quota at midnight Pacific Time. A fixed UTC offset fails across
daylight-saving transitions; Python's IANA timezone database handles both offsets.

**Alternatives considered**:

- UTC calendar days: rejected because they do not match provider resets.
- Fixed UTC-8: rejected because Pacific daylight time is UTC-7 for part of the year.

## Decision 5: Existing diagnostic surface, no new MCP tool

**Decision**: Add quota state to `verify_connectors_health` and typed quota exceptions. Do not add a
new public tool.

**Rationale**: Operators already use the connector diagnostic to distinguish authentication,
connectivity, and rate-limit failures. A separate tool would expand the public catalog for one
connector and duplicate the same troubleshooting surface.

**Alternatives considered**:

- New `get_youtube_quota_status` MCP tool: rejected as unnecessary public-surface growth.
- Logs only: rejected because logs are process-local and not an actionable shared snapshot.

## Decision 6: Preserve scheduler cadence

**Decision**: Correct stale quota comments and interval calculations, but do not change the current
configured or default scheduler cadence. The shared ledger is the hard enforcement boundary.

**Rationale**: A cadence change affects product freshness and deployment operations; the requested
scope is preventing exhaustion and reserving capacity. Existing deployments may already override
the interval.

**Alternatives considered**:

- Change the default to fit a theoretical maximum daily pass count: rejected because autonomous discovery, cache hits, and variable keyword counts make that estimate deployment-specific.
