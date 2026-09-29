# Contract: YouTube Quota Diagnostics

The existing `verify_connectors_health` result adds a `quota` object to the YouTube connector entry.
No new MCP tool is introduced.

```json
{
  "connectors": {
    "YouTube Data API v3": {
      "status": "HEALTHY",
      "quota": {
        "quota_day": "2026-09-29",
        "next_reset_at": "2026-09-30T07:00:00+00:00",
        "buckets": {
          "search_list": {
            "used": 12,
            "scheduled_used": 8,
            "limit": 100,
            "scheduled_limit": 70,
            "exhausted": false
          },
          "default_units": {
            "used": 13,
            "scheduled_used": 0,
            "limit": 10000,
            "scheduled_limit": null,
            "exhausted": false
          }
        }
      }
    }
  }
}
```

Rules:

- Missing rows read as zero usage, not unknown usage.
- A local refusal raises `ConnectorQuotaExceededException` with bucket, usage, limit, and reset attributes.
- The API key and request URL never appear in this object or exception text.
- Authentication, transient failures, empty data, and quota exhaustion remain distinct connector states.
