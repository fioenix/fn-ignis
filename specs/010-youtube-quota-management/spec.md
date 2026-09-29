# Feature Specification: YouTube Quota Management

**Feature Branch**: `codex/010-youtube-quota-management`

**Created**: 2026-09-29

**Status**: Draft

**Input**: User description: "Protect the fn-ignis-only YouTube API key from exhausting its daily quota while preserving scheduled radar ingestion and on-demand research."

## Clarifications

### Session 2026-09-29

- Q: Is the Google Cloud project/API key shared with any system outside fn-ignis? → A: No; only fn-ignis uses it. (owner confirmed)
- Q: How should daily search capacity be split between scheduled and requested work? → A: Cap scheduled Track 1 at 70 calls, reserve at least 30 for requested Track 2, and let Track 2 borrow any unused total capacity. (agent decided; basis: Track 1 is optional while Track 2 serves explicit user intent)
- Q: Which YouTube quota buckets should the feature manage? → A: Manage both `search.list` calls and the shared units used by other invoked endpoints, using current provider defaults with operator overrides. (agent decided; basis: key-level protection must cover every outbound YouTube call made by fn-ignis)
- Q: Should this feature also change the scheduler's default cadence? → A: No; preserve the existing cadence and enforce the hard daily boundary in the shared ledger. (agent decided; basis: changing operational frequency expands scope beyond quota safety)
- Q: Should this feature move or replace the published `v0.6.0` tag? → A: No; preserve the immutable `v0.6.0` release, integrate migration `024` through its own pull request, and leave the next release version to an explicit owner decision. (agent decided; basis: live GitHub readback shows `v0.6.0` was published on 2026-09-28, and the release ledger forbids moving that tag)
- Q: Which version should publish migration `024` and YouTube quota management? → A: `v0.7.0`. (owner confirmed; basis: this is the next MINOR after the published `v0.6.0`, and repository policy classifies a new migration and capability as MINOR)

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Prevent Concurrent Quota Overspend (Priority: P1)

As an operator running both the background worker and one or more agent clients, I need every YouTube request to draw from one shared daily allowance so concurrent processes cannot independently spend the same remaining quota.

**Why this priority**: Avoiding a provider-enforced outage is the core outcome. A process-local counter cannot protect one exclusive key used by separate worker and MCP processes.

**Independent Test**: Start concurrent scheduled and requested searches against the same remaining allowance. The combined number of admitted requests never exceeds the shared daily limit, including requests that later fail upstream.

**Acceptance Scenarios**:

1. **Given** multiple fn-ignis processes share the same key and daily bucket, **When** they reserve the final available calls concurrently, **Then** only requests within the remaining allowance are admitted.
2. **Given** a request has reserved quota, **When** the provider request fails or returns no results, **Then** the reservation remains consumed because the provider still charges attempted calls.
3. **Given** a result is served from the existing cache without a provider call, **When** the result is returned, **Then** no quota is reserved.
4. **Given** the provider reports that the daily quota is exhausted, **When** later requests arrive before reset, **Then** they fail closed without calling the provider again.

---

### User Story 2 - Protect On-Demand Research Capacity (Priority: P2)

As an operator using Track 2 for explicit research, I need unattended Track 1 searches capped below the total daily search allowance so scheduled sweeps cannot consume all capacity before I ask a question.

**Why this priority**: Track 1 is an optional baseline, while Track 2 serves active user intent. A deterministic reserve prevents background work from starving interactive research.

**Independent Test**: Consume the scheduled allowance, confirm another scheduled search is rejected, then confirm requested searches can still use the reserved capacity and any unused scheduled capacity up to the total limit.

**Acceptance Scenarios**:

1. **Given** scheduled searches have consumed 70 calls in the current quota day, **When** another scheduled search is attempted, **Then** it is rejected before contacting YouTube.
2. **Given** scheduled searches have consumed 70 calls and total usage is below 100, **When** a requested search is attempted, **Then** it is admitted until total usage reaches 100.
3. **Given** scheduled searches have consumed fewer than 70 calls, **When** requested searches need more than their 30-call reserve, **Then** they may use the remaining total capacity.

---

### User Story 3 - Understand Quota State and Reset (Priority: P3)

As an operator diagnosing a degraded YouTube connector, I need the system to report what bucket is limited, how much fn-ignis has recorded, and when it becomes available again without exposing the API key.

**Why this priority**: A fail-closed limiter without actionable state looks like a broken connector and encourages unsafe retries.

**Independent Test**: Exhaust each managed bucket in a controlled fixture and verify that connector diagnostics identify the exhausted bucket, recorded usage, and next Pacific-Time reset while all outputs remain secret-free.

**Acceptance Scenarios**:

1. **Given** a request is rejected locally, **When** health or error details are inspected, **Then** they identify the bucket, used amount, limit, and next reset time.
2. **Given** the Pacific-Time quota day rolls over, **When** the next reservation is attempted, **Then** a fresh daily bucket is used automatically.
3. **Given** diagnostics and logs are produced, **When** they are scanned for credentials, **Then** the YouTube API key is absent.

### Edge Cases

- Two processes attempt to reserve the final available call at the same instant.
- The local wall clock crosses midnight Pacific Time while a process remains running.
- Daylight-saving transitions change the UTC offset of Pacific Time.
- A provider call times out after the local reservation succeeds.
- The provider reports quota exhaustion before the local ledger reaches its configured limit because the provider-side allocation differs or was changed.
- A cached result expires while the daily bucket is already exhausted.
- Existing installations upgrade with no quota history.
- SQLite and PostgreSQL enforce the same admission behavior under their supported concurrency models.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST keep a persistent daily quota ledger shared by the worker and all MCP processes using the same fn-ignis database.
- **FR-002**: The system MUST manage the provider's separate daily `search.list` call bucket and the combined daily unit bucket used by other YouTube endpoints invoked by fn-ignis.
- **FR-003**: The system MUST atomically reserve the full known cost before each outbound YouTube request and MUST reject the request when the relevant reservation cannot be granted.
- **FR-004**: The system MUST retain a granted reservation as consumed regardless of the provider response, including invalid requests, timeouts, empty results, and other failures.
- **FR-005**: The system MUST NOT reserve quota when an existing cached response satisfies the request without contacting YouTube.
- **FR-006**: Scheduled Track 1 work MUST be limited to 70 `search.list` calls per Pacific-Time day.
- **FR-007**: Requested Track 2 work MUST have access to at least 30 `search.list` calls per Pacific-Time day and MAY consume any total capacity not already used by scheduled work.
- **FR-008**: Total `search.list` admissions MUST NOT exceed the configured daily provider allocation, which defaults to 100 calls.
- **FR-009**: Total admissions for other YouTube endpoints MUST NOT exceed their configured shared daily allocation, which defaults to 10,000 units.
- **FR-010**: The system MUST derive quota-day boundaries and the next reset instant from Pacific Time, including daylight-saving transitions.
- **FR-011**: When YouTube reports quota exhaustion, the system MUST mark the affected local daily bucket exhausted and reject later requests in that bucket until the next reset.
- **FR-012**: A locally rejected request MUST expose a typed rate-limit outcome that identifies the bucket, recorded usage, configured limit, and next reset instant.
- **FR-013**: Connector health and diagnostic output MUST distinguish local quota exhaustion from authentication failures, transient provider failures, and empty data.
- **FR-014**: The API key MUST NOT appear in quota records, errors, logs, diagnostics, or test artifacts.
- **FR-015**: Existing installations MUST acquire the quota ledger through the normal migration path without manual data repair.
- **FR-016**: SQLite and PostgreSQL MUST satisfy the same reservation, reset, exhaustion, and reporting contracts.
- **FR-017**: The feature MUST NOT add a second scheduler, replace the existing response cache, or attempt to synchronize usage by polling Google Cloud Console.

### Key Entities

- **Quota Day**: The Pacific-Time calendar date that owns a set of daily provider allowances and their reset boundary.
- **Quota Bucket**: A provider-defined allowance for one method group, with configured limit, recorded usage, exhaustion state, and next reset instant.
- **Quota Reservation**: An atomic admission decision that records the trigger, endpoint cost, and quota day before a provider request begins.
- **Ingress Trigger**: The existing distinction between scheduled background work and requested/on-demand work, used to enforce the Track 1 cap.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: In a concurrency test with more attempts than remaining allowance, 100% of runs admit no more requests than the shared remaining quota.
- **SC-002**: Scheduled work is rejected after 70 daily search admissions while at least 30 search admissions remain available to requested work.
- **SC-003**: Requested work can consume all unused daily search capacity, but combined scheduled and requested admissions never exceed 100 under default limits.
- **SC-004**: After an upstream quota-exhausted response, zero further provider calls for that bucket occur before the next Pacific-Time reset.
- **SC-005**: On the first reservation after a Pacific-Time day rollover, quota is available without process restart or operator intervention.
- **SC-006**: The full unit suite, backend parity tests, repository convention checks, and secret-scanning checks pass with no API key in captured output or committed files.
- **SC-007**: An operator can identify the limited bucket, recorded usage, limit, and reset time from one diagnostic result without consulting process-local state.

## Assumptions

- The Google Cloud project and API key are used exclusively by fn-ignis, as confirmed by the owner on 2026-09-29.
- All fn-ignis processes using the key point to the same configured database; cross-database coordination is outside this feature's scope.
- Default allocations follow Google's documented 2026 granular quota model: 100 daily `search.list` calls and 10,000 daily units combined for other endpoints; operators with a quota extension can override these limits through existing configuration conventions.
- Daily quotas reset at midnight Pacific Time.
- The ledger is an admission-control record for fn-ignis activity, not a billing-grade mirror of Google Cloud Console.
