# Data Model: No Author Identity at Rest

Additive to the schema on `main` (latest migration `026`); delivered as
`sql/031_author_identity_at_rest.sql` with SQLite parity in `_ensure_schema` (research R14).

## Changed: `observations`

| Field | Change | Rule |
|---|---|---|
| `metadata` | Content only | Contains no key from the author field list (R2); enforced by the repository guard. |
| `observed_title` | Text policy | `@mention` tokens replaced (R7); email/phone/secret redaction unchanged. |
| `source_url` | Identity-free | Canonical link from platform + content identifier, or `NULL` (R5). |
| `identity_source` | New value | `unverifiable_content` added to the CHECK (R6). |

Validation: an observation with `identity_source = 'unverifiable_content'` may only be bound to a
claim with purpose CONTEXT and relation `CONTEXT_ONLY`.

## Changed: `sources`

| Field | Rule |
|---|---|
| `external_id` | Content identifier, a handle-free normalised URL, or `content:<sha256>` for unverifiable content. Never derived from a profile or handle URL. |

## Changed: `mission_evidence`

| Field | Type | Rule |
|---|---|---|
| `author_state` | enum `KNOWN`, `UNKNOWN`, `UNAVAILABLE`, `DECLARED` | Required for rows written after the migration; `NULL` marks legacy rows. |
| `author_marker` | 16 hex chars, nullable | Present only when `KNOWN`. Stable within the mission, different across missions (FR-007). |
| `declared_account_id` | FK → `mission_declared_accounts.id`, `ON DELETE SET NULL` | Present only when `DECLARED`; same mission as the row. |

Transitions: `DECLARED` → (declaration withdrawn) → `declared_account_id` becomes `NULL` and the
row reads as `UNKNOWN` for analysis; no marker is created retroactively, because the identity was
never kept.

## New: `mission_author_keys`

| Field | Type | Rule |
|---|---|---|
| `mission_id` | PK, FK → mission | One key per mission. |
| `encrypted_key` | text | 32 random bytes, Fernet-encrypted with `IGNIS_ENCRYPTION_KEY`. Never returned by any tool, report or log (FR-008). |
| `created_at` | timestamp | |

Lifecycle: created on first collection; destroyed by `destroy_mission_author_key`, called from the
mission evidence deletion paths. Retention enforcement itself is outside this feature.

## New: `mission_declared_accounts`

| Field | Type | Rule |
|---|---|---|
| `id` | UUID PK | |
| `mission_id` | FK → mission | A declaration belongs to exactly one mission (FR-018). |
| `platform` | platform enum | |
| `account_key` | text | Normalised handle (lowercase, no `@`) or platform account identifier. Unique per (mission, platform). |
| `declared_name` | text | Name shown in reports (FR-019). |
| `declared_at` | timestamp | Declarations apply to content collected after this time. |

Withdrawal deletes the row.

## Domain values (no table)

- **AuthorIdentityPolicy**: input is a signal, the mission's declarations, the self-content
  identities and the mission key; output is an identity-free signal plus `author_state`,
  `author_marker`, `declared_account_id`.
- **AuthorConcentration**: per mission and channel — `distinct_authors`, `unknown`, `unavailable`,
  `top_share` (share of observations from the single most frequent marker).
- **LegacyIdentityInventory**: per store, table and field — count of rows holding author keys,
  handle-bearing URLs or handle-derived external ids. Counts only.
