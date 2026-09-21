# Data Model: Dual-Surface Research Workspace

## Research Workspace

The logical boundary for one research inside the shared Ignis database, paired with a user-visible
child folder under the current host workspace.

| Field | Meaning | Rules |
|---|---|---|
| `workspace_id` | Stable identity | Immutable after creation |
| `slug` | Child-folder name | Validated, unique under the current host workspace |
| `root_path` | Absolute local workspace path | Must be under the confirmed host workspace |
| `format_version` | Workspace schema version | Required for reopen and compatibility checks |
| `status` | `READY` or `INCOMPATIBLE` | Non-empty folders without a matching manifest require explicit adoption |
| `created_at` | Creation time | Recorded once with an explicit UTC clock |

The manifest is the filesystem discovery entry point. The configured shared Ignis database is the
canonical record store. Every research-owned table is scoped by `workspace_id`; files outside
canonical tables are projections, journals, or artifacts.

## Mission

An analysis run inside a research workspace.

| Field | Meaning | Rules |
|---|---|---|
| `mission_id` | Stable mission identity | Immutable |
| `workspace_id` | Owning research workspace | Required foreign key and isolation boundary |
| `surface` | `ATTENTION` or `MARKET` | Immutable for the mission |
| `status` | `PENDING`, `RUNNING`, `COMPLETED`, `FAILED`, or `BLOCKED` | Transitions are recorded, not inferred from chat state |
| `title` | Human-readable mission label | Not an identity key |
| `geo` | Research geography | Required for both surfaces |
| `timeframe` | Research window | Required for both surfaces |
| `created_at` / `updated_at` | Mission clocks | UTC and provenance-preserving |
| `parent_attention_mission_id` | Optional Attention origin | Only set for a Market handoff |
| `parent_cluster_id` | Optional selected Attention cluster | Context lineage, never Market proof by itself |
| `brief_revision_id` | Required for a Market mission | Null for Attention missions |

The Agent chat/session identifier may be recorded as non-authoritative integration metadata. It
does not determine mission or workspace ownership.

The existing `research_missions` record is extended with the workspace and surface fields needed
above. There is no second mission table or alternate mission identity for the feature.

## Market Brief Revision

The immutable decision frame that authorizes a Market mission.

| Field | Meaning | Rules |
|---|---|---|
| `brief_revision_id` | Stable revision identity | Immutable |
| `workspace_id` | Owning workspace | Required foreign key |
| `mission_id` | Market mission authorized by the Brief | One confirmed revision per Market mission |
| `decision` | Decision the research must inform | Required, non-empty |
| `target_user` | User/customer under investigation | Required, non-empty |
| `problem` | Pain or job to investigate | Required, non-empty |
| `geo` | Geographic scope | Required |
| `timeframe` | Evidence window | Required |
| `hypothesis` | Falsifiable proposition | Required, non-empty |
| `falsifiers` | Conditions that would disconfirm it | Required, at least one useful condition |
| `confirmed_at` | Confirmation timestamp | Set once |
| `confirmed_by` | Requester identity or host-provided actor | Required for an accepted revision |
| `revision_number` | Monotonic revision within the research line | Never reused |

Draft answers and abandoned Q&A are not persisted as Brief entities.

## Observation and Mission Evidence

Reuse the existing canonical model:

- `source` identifies one external object.
- `observation` records one immutable sighting and its time/identity provenance.
- `mission_evidence` records the exact mission-to-observation association.

The feature adds workspace, surface, and lineage metadata around these existing records; it must
not introduce source identity in titles, URLs, or a second legacy signal table. SQLite and
PostgreSQL implementations must enforce the same workspace-scoping and provenance invariants.
Market citations resolve through `mission_evidence.observation_id`; a URL or title is display
payload only and cannot be used as the citation identity.

## Run Journal

The exclusive recovery record for one mission run.

| Field | Meaning | Rules |
|---|---|---|
| `run_id` | Stable run identity | Unique within the workspace |
| `mission_id` | Target mission | Required |
| `journal_path` | Exclusive journal file path | Created atomically; never overwritten by another run |
| `sequence` | Fixed-width collision sequence | Allocated only after the timestamp |
| `status` | Run lifecycle state | Updated transactionally where possible |
| `started_at` / `completed_at` | Run clocks | UTC; completion may be absent for interrupted runs |

## Artifact

A derived, human-readable output such as an HTML dashboard or JSON export.

Artifacts carry their owning `workspace_id`, `mission_id`, and source revision or analysis
version. They are not a second canonical evidence store and can be regenerated from the configured
shared database.

## State transitions

```text
Workspace proposal --confirm--> READY
        \\--cancel/reject--> no durable workspace

Attention mission: PENDING -> RUNNING -> COMPLETED | FAILED

Market draft --confirm complete Brief--> Market mission PENDING
Market mission: PENDING -> RUNNING -> COMPLETED | FAILED
                  \\--conflicting write--> new Brief revision or BLOCKED
```
