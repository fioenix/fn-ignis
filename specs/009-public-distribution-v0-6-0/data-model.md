# Data Model: Public Distribution and v0.6.0 Release

Plan 009 adds no application database entity. Its data model describes the release evidence that
maintenance scripts produce and the state transitions the release owner evaluates.

## Release Candidate

| Field | Meaning | Validation |
|---|---|---|
| `version` | Proposed SemVer without the `v` prefix | Exactly `0.6.0` for this plan |
| `branch` | Reviewed feature/release branch | Not `main` during Engineering |
| `candidate_commit` | Full commit SHA after Engineering | Clean tree, reachable from branch |
| `main_commit` | Full merge commit selected for tagging | Required before tag; belongs to `main` |
| `version_files` | Release-controlled file/value map | Every controlled value, both manifest versions, and the OCI tag equal `0.6.0` |
| `lock_version` | Project version resolved in `uv.lock` | Equals `0.6.0`; produced by `uv lock` |
| `local_gates` | Named command, exit, counts, timestamp | Every required gate verified |
| `ci_gates` | Required GitHub check results | Every required check success on main commit |

### States

```text
DRAFT -> ENGINEERING_VERIFIED -> REVIEWED -> MERGED -> TAGGED -> PUBLISHED -> RELEASED
   |              |                 |          |          |          |
   +------------ FAILED <-----------+----------+----------+----------+
```

`RELEASED` is terminal for the version but not inferred from any preceding state. A candidate can
be merged or tagged and still remain a partial, unreleased distribution.

## Distribution Surface

| Field | Meaning | Validation |
|---|---|---|
| `name` | Stable surface key | One of the contract keys below |
| `required` | Whether the surface gates `RELEASED` | `true` except PyPI |
| `state` | Observation result | `VERIFIED`, `MISSING`, `FAILED`, `UNREADABLE`, or `DEFERRED` |
| `observed_at` | UTC observation timestamp | Set for every attempted check |
| `subject` | Tag, URL, digest, or commit observed | Redacted; no credential-bearing URL |
| `evidence` | Bounded factual summary | No secrets or full environment dump |
| `command_exit` | Exit status where a command ran | Integer or absent for API-only checks |
| `failure_class` | Why state is not verified | Missing, behavior mismatch, auth, network, tool unavailable |

### Required Surface Keys

- `repository_public`
- `tag_on_main`
- `github_release_published`
- `version_parity`
- `source_tag_checkout`
- `source_bootstrap`
- `source_mcp_runtime`
- `container_workflow`
- `container_anonymous_pull`
- `container_digest`
- `container_mcp_runtime`
- `container_provenance`
- `mcp_registry_validation`
- `compose_worker_override`

### Deferred Surface Key

- `pypi_distribution`

`DEFERRED` is valid only for a surface whose policy says `required = false`. It never satisfies a
required surface and never appears as a euphemism for `MISSING`.

## Source Distribution Evidence

| Field | Meaning |
|---|---|
| `clone_url` | Public HTTPS clone URL without credentials |
| `tag` | Exact requested tag |
| `resolved_commit` | Commit checked out from that tag |
| `isolated_home` | Whether no user home/config was inherited |
| `locked_install` | Whether bootstrap used the committed lock |
| `schema_endpoint` | Highest packaged/applied migration (`023`) |
| `tool_count` | MCP discovery result (47) |
| `tool_call` | Deterministic tool exercised and its bounded result |

## Container Distribution Evidence

| Field | Meaning |
|---|---|
| `image` | `ghcr.io/fioenix/fn-ignis:0.6.0` |
| `credential_isolation` | Empty Docker config and stripped ambient GitHub credentials |
| `pulled_digest` | Immutable repo digest returned by the pull |
| `release_tags` | `0.6.0`, `0.6`, and `latest` digest map |
| `source_label` | Repository linkage label from final image |
| `mcp_server_name_label` | Exact `io.modelcontextprotocol.server.name` ownership label |
| `default_role` | MCP stdio server |
| `tool_count` | MCP discovery result (47) |
| `compose_role` | Explicit scheduler worker command |
| `attestation_subject` | Digest covered by authenticated release-owner provenance verification |

## Release Evidence Bundle

| Field | Meaning | Rule |
|---|---|---|
| `schema_version` | Evidence record format | Fixed by the acceptance script |
| `release` | Release Candidate snapshot | Uses full SHAs and exact version |
| `surfaces` | Map of Distribution Surface records | Every required key appears once |
| `verdict` | `RELEASED`, `NOT_RELEASED`, or `INDETERMINATE` | Derived, never typed manually |
| `missing` | Required surfaces proven absent | Derived from `MISSING` |
| `failed` | Required surfaces fetched but behaviorally invalid | Derived from `FAILED` |
| `unreadable` | Required surfaces that could not be observed | Derived from `UNREADABLE` |
| `deferred` | Named non-required surfaces | Contains PyPI for Plan 009 |

### Verdict Derivation

- `RELEASED`: every required surface is `VERIFIED`.
- `NOT_RELEASED`: at least one required surface is `MISSING` or `FAILED`, and none is unreadable in
  a way that prevents classifying the overall state.
- `INDETERMINATE`: at least one required surface is `UNREADABLE`; list the unread fact and preserve
  any separately proven missing or failed facts.

## Ownership Boundaries

- **Claude Code / Engineering** writes repository bytes and local gate evidence only.
- **Codex / release owner** changes package visibility, pushes, merges, tags, publishes, and records
  live external evidence.
- **GitHub/GHCR** own tag, Release, workflow, visibility, digest, and attestation facts.
- **Anonymous clean-room clients** own the only acceptable proof of public source/container access.
