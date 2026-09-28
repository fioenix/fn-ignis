# Contract: Release Observation and Verdict

## Surface Record

```json
{
  "name": "container_anonymous_pull",
  "required": true,
  "state": "VERIFIED",
  "observed_at": "2026-09-28T00:00:00Z",
  "subject": "ghcr.io/fioenix/fn-ignis@sha256:<digest>",
  "evidence": "isolated pull completed and every layer was available",
  "command_exit": 0,
  "failure_class": null
}
```

## States

| State | Meaning | Example |
|---|---|---|
| `VERIFIED` | Owning surface positively satisfies the contract | Anonymous pull and MCP smoke exit 0 |
| `MISSING` | Owning surface positively says the required object/access is absent | GitHub says release not found; GHCR returns unauthorized to anonymous consumer |
| `FAILED` | Artifact was obtained but violated its behavioral contract | Image starts worker instead of MCP |
| `UNREADABLE` | The fact could not be observed | Network failure, missing local tool, insufficient API scope |
| `DEFERRED` | Policy explicitly excludes a non-required surface | PyPI in Plan 009 |

An empty stdout, non-zero exit, or missing JSON field is not automatically `MISSING`. The caller
must classify stderr/status against a known absence response; otherwise the state is `UNREADABLE`.

## Bundle Shape

```json
{
  "schema_version": 1,
  "version": "0.6.0",
  "main_commit": "<40-hex-sha>",
  "surfaces": {},
  "verdict": "RELEASED",
  "missing": [],
  "failed": [],
  "unreadable": [],
  "deferred": ["pypi_distribution"]
}
```

Every required surface named in `data-model.md` must appear exactly once. Unknown extra surface
names fail validation so a typo cannot silently create an unchecked replacement.

## Verdict Function

```text
if any required state == UNREADABLE:
    INDETERMINATE
else if any required state in {MISSING, FAILED}:
    NOT_RELEASED
else if every required state == VERIFIED:
    RELEASED
else:
    INDETERMINATE
```

The output lists all observed problems even when one unreadable surface makes the overall verdict
indeterminate. This prevents a network failure from hiding a separately proven missing Release or
failed runtime.

## Negative Controls

Each claim must have an independent mutation that turns its gate red:

- Remove the Git tag while leaving the GitHub Release fixture present.
- Mark the repository public while removing the Release.
- Return API 403 with empty stdout; expect `UNREADABLE`, not `MISSING`.
- Make an authenticated container pull succeed and the isolated pull return `unauthorized`.
- Point any one of `0.6.0`, `0.6`, or `latest` at a different digest.
- Start the container as the scheduler while the manifest says stdio.
- Remove either Compose scheduler override and prove runtime worker acceptance turns red.
- Remove or alter the `io.modelcontextprotocol.server.name` label while keeping the source label.
- Remove migration `023` from the wheel/container while keeping the source file.
- Change one current 47-tool claim to 39 or 45 while runtime/manifests remain 47.
- Change one current installation endpoint from `023` to `022`.
- Reintroduce a PyPI availability claim while PyPI remains deferred.
- Change only the root `server.json` version, package version, or OCI identifier tag.
- Leave `uv.lock` at `0.5.0` after changing `pyproject.toml`.

## Human-Readable Output

The CLI prints one line per surface, then the verdict and grouped missing/failed/unreadable/deferred
lists. It never prints a token, Docker config, environment file, database DSN, or complete child
process environment.
