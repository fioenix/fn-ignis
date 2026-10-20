# Contract: MCP Surface Changes

## Owner gate: new tool `set_mission_declared_accounts`

Status: **approved by the owner on 2026-10-20 (OG-1, AGENTS.md Section 8)**. Adding
one tool (47 → 48 once PR #51 merges; `main` has 44 today) changes every governed tool-count surface checked by
`tests/unit/test_public_distribution_contract.py`.

Input:

```json
{
  "mission_id": "uuid",
  "accounts": [
    {"platform": "tiktok", "account": "@brandx", "declared_name": "Brand X"}
  ]
}
```

- Replaces the mission's whole declaration set; an empty list withdraws all.
- `account` is normalised (lowercase, leading `@` removed). Duplicate (platform, account) is
  `INVALID_REQUEST`.
- Unknown mission or a mission outside the caller's workspace is refused with the existing
  mission-scope refusal.

Output:

```json
{
  "mission_id": "uuid",
  "accounts": [
    {"id": "uuid", "platform": "tiktok", "account": "brandx", "declared_name": "Brand X",
     "declared_at": "2026-10-20T08:00:00Z"}
  ],
  "withdrawn": 0,
  "applies_from": "Content collected after declared_at; earlier observations are not re-attributed."
}
```

## Response-shape changes (no signature change)

| Tool | Removed | Added or changed | Consumers to update |
|---|---|---|---|
| `get_mission_analysis` | `stats.top_creators`, `top_signals[].metadata.channel`, handle-bearing `url` | `author_concentration` per channel; identity-free `url` | report builder, `ignis-analyze` skill text, tests |
| `discover_market_opportunities` | citation `author_or_channel` for undeclared authors | `author_or_channel` only for declared accounts | report builder, tests |
| `get_tiktok_video_comments` | `author`, `author_id` | per-response `author_concentration` (ephemeral key) | tests, docs |
| `extract_customer_pain_points` | `inquiries[].author`, handle-bearing `video_url` | identity-free `video_url` or content id; `author_concentration` | report template (`inq.author`), tests |
| `get_mission_evidence_qualification_batch` | handle-bearing `source_url` | identity-free `source_url`; `source_verifiable: false` for unverifiable content | qualification skill text, tests |

Every text field in these responses carries `@[user]` in place of undeclared mentions.

## Report template

`src/ignis/infrastructure/templates/html/mission_report.html` renders an author only for a
declared account (lines 389, 595-597, 701-702 on `main`), and a link only when an identity-free
link exists; otherwise the content identifier with "link unavailable".
