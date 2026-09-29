# Data Model: YouTube Quota Management

## Entity: YouTube Quota Bucket

One row represents one provider quota bucket during one Pacific-Time calendar day.

| Field | Meaning | Constraint |
|---|---|---|
| `quota_day` | Calendar date in `America/Los_Angeles` | Part of primary key |
| `bucket` | `search_list` or `default_units` | Part of primary key |
| `used` | Total locally admitted calls/units | Integer, non-negative |
| `scheduled_used` | Portion admitted for `IngressTrigger.SCHEDULED` | Integer, non-negative, not above `used` |
| `exhausted` | Provider reported the bucket exhausted | Boolean, defaults false |
| `created_at` | First reservation timestamp | UTC instant |
| `updated_at` | Most recent reservation/exhaustion timestamp | UTC instant |

Primary key: (`quota_day`, `bucket`). No API key or credential fingerprint is stored because the
owner confirmed one exclusive key and one shared database per installation.

## Value: Quota Policy

| Field | Default | Rule |
|---|---:|---|
| Search daily limit | 100 calls | Positive integer |
| Scheduled search daily limit | 70 calls | Between 0 and search daily limit |
| Other-endpoint daily limit | 10,000 units | Positive integer |

## Value: Quota Snapshot

Returned to the connector and diagnostics:

- quota day and bucket
- recorded total usage and scheduled usage
- configured total limit and applicable scheduled limit
- exhausted state
- next reset instant in UTC

## State Transitions

```text
ABSENT --first admitted reservation--> ACTIVE
ACTIVE --admitted reservation-------> ACTIVE (counters increase atomically)
ACTIVE --local limit reached--------> REFUSING (row unchanged; request rejected)
ACTIVE --provider quota exhausted---> EXHAUSTED
EXHAUSTED --any same-day request----> REFUSING
any state --next Pacific day--------> ABSENT for the new key, then ACTIVE on first reservation
```

Reservations are never rolled back after admission. Old rows are retained as small operational
history; the feature adds no cleanup job.
