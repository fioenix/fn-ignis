# Implementation Plan: Public Distribution and v0.6.0 Release

**Branch**: `codex/009-public-distribution-v0.6.0` | **Date**: 2026-09-28 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/009-public-distribution-v0-6-0/spec.md`

## Summary

Turn the already-public source repository and already-built GHCR artifact into two truthful,
tested distribution paths for `v0.6.0`. The source path remains the one-command bootstrap from an
immutable tag. The container path becomes a public OCI package whose default process is the 47-tool
MCP stdio server, while Compose continues to select the optional scheduler worker explicitly.

Before release, replace stale current-state claims (39/45 tools and migration endpoint 022), remove
the nonexistent PyPI package claim, add static negative controls for those drifts, harden the
tag-driven container workflow, and create a fail-closed clean-room verifier that exercises public
bytes rather than configuration. Engineering stops at a reviewed release candidate. Codex, as
release owner, performs merge, public-visibility change, tag, GitHub Release, CI monitoring, and
live readback.

## Technical Context

**Language/Version**: Python 3.11 through 3.14; Bash for bootstrap; GitHub Actions YAML; OCI image

**Primary Dependencies**: Existing FastMCP runtime, `uv`, Docker/Buildx, GitHub Actions, GitHub
Container Registry, existing GitHub CLI and standard-library subprocess/JSON support; no new
runtime dependency

**Storage**: No application schema change in Plan 009. Clean-room acceptance uses disposable
SQLite and scratch PostgreSQL/Compose state only. Migration `023` is packaged and tested but is not
applied to a persistent operator database.

**Testing**: pytest unit and integration contracts; real PostgreSQL parity; fresh Compose init;
clean-user bootstrap; wheel MCP smoke; container MCP smoke; isolated anonymous Docker pull;
release-state negative controls; Ruff, coverage, lock, build, secret and diff gates

**Target Platform**: Public GitHub source on macOS/Linux and a Linux OCI image on GHCR. `v0.6.0`
does not add a multi-architecture guarantee; the source bootstrap remains the portable path.

**Project Type**: Single Python package exposing an MCP stdio server and an optional background
worker, distributed as tagged source and one OCI image

**Performance Goals**: Keep the existing SC-001 P95 below 50 ms; complete each public clean-room
path within the existing 15-minute bootstrap timeout; add no steady-state runtime overhead

**Constraints**: No PyPI publish; no persistent database migration; no secret in logs or generated
configuration; public-state evidence must come from unauthenticated consumers; GHCR visibility is
one-way; tag only a verified `main` commit; version changes are atomic and lockfile-generated

**Scale/Scope**: One release, two required distribution paths, six release-controlled files plus
the lockfile and tag, 47 MCP tools, migrations `001` through `023`, one container package and three
supported release tags (`0.6.0`, `0.6`, `latest`); historical image versions are preserved

## Constitution Check

*GATE: Passed before Phase 0 and re-checked after Phase 1.*

- **I. Zero-Token Ingress**: PASS. Distribution and smoke checks make no model calls and consume no
  connector quota. The deterministic smoke tool reads local runtime configuration only.
- **II. Pluggable connectors**: PASS. No connector implementation or eligibility changes. Clean
  acceptance deliberately avoids connector credentials and live research ingress.
- **III. Storage-first evidence**: PASS. Migration `023` is packaged and exercised on scratch
  databases. No persistent corpus is touched and no second application data authority is added.
- **IV. Deterministic artifacts**: PASS. No report template changes are required. Built source,
  wheel, and container contents are checked against the committed migration and template inventory.
- **V. Simplicity and type safety**: PASS. The existing image and smoke client are adapted rather
  than adding another service or dependency. One typed release-surface model distinguishes
  verified, missing, failed, and unreadable states.
- **VI. Evidence-gated migration and release**: PASS. The release is withheld until local gates,
  mainline integration, live tag/Release state, public GHCR access, and clean-room runtime evidence
  are all positive. An unread surface never becomes a negative or positive fact by inference.

## Project Structure

### Documentation (this feature)

```text
specs/009-public-distribution-v0-6-0/
├── spec.md
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── public-distribution.md
│   └── release-verdict.md
├── checklists/
│   └── requirements.md
└── tasks.md
```

### Repository Changes

```text
Dockerfile
docker-compose.yml
docker-compose.prod.yml
server.json
openclaw.json
.openclaw/config.yaml
CITATION.cff
pyproject.toml
uv.lock
BACKLOG.md
AGENTS.md
README.md
README.vi.md
docs/
├── assets/
│   ├── architecture.html
│   ├── architecture.svg
│   └── architecture.png
├── diagrams/
│   ├── ignis-pipeline.html
│   ├── ignis-pipeline.svg
│   └── ignis-pipeline.png
├── PROJECT_REVIEW_CONTEXT.md
├── USER_GUIDE.md
└── USER_GUIDE.vi.md
.github/workflows/
└── docker-publish.yml
scripts/
├── check_release_state.py
├── public_release_acceptance.py
└── wheel_mcp_smoke.py
src/ignis/interfaces/cli/
└── setup_bundle.py
tests/
├── unit/
│   ├── test_public_distribution_contract.py
│   ├── test_diagram_and_release_claims.py
│   ├── test_repo_conventions.py
│   └── test_tool_manifests_drift.py
└── integration/
    ├── test_clean_user_journey.py
    └── test_compose_init.py
```

**Structure Decision**: Extend the existing single-package release surfaces. Keep release policy and
live-surface classification in maintenance scripts, user-facing installation truth in the existing
public guides, and behavioral contracts in the existing pytest hierarchy. Do not add a release
service, database table, or third distribution registry.

## Design

### 1. Make each distribution claim executable

The source contract starts from `git clone --branch v0.6.0 --depth 1` against the public URL, not a
copy produced by `git ls-files`. It runs bootstrap under an isolated home, validates migration
`023`, starts an MCP session, lists 47 tools, and calls `get_runtime_config`. The existing
tracked-tree clean-user test remains the pre-tag regression gate; the public-tag run is the release
gate that catches missing commits and tag mistakes.

The container contract uses an empty Docker configuration directory and removes GitHub credential
variables from the child environment. It fully pulls the selected/default-platform manifest,
config, and referenced layers, records the `RepoDigest`, and starts that immutable digest through
`docker run --rm -i`. The existing MCP smoke conversation is generalized to launch either local
Python or a caller-supplied command so the wheel and container exercise one protocol contract
instead of two copied clients. The smoke rejects non-MCP stdout and requires prompt exit on stdin
EOF.

### 2. Align the OCI image with the registry manifest

`server.json` changes from the deferred/nonexistent PyPI package to an OCI package at
`ghcr.io/fioenix/fn-ignis:0.6.0`, with stdio transport. Therefore the Dockerfile's default command
must start `ignis.interfaces.mcp.server`. Both Compose files already provide an explicit scheduler
command; tests will lock that separation before the Dockerfile changes. The manifest keeps both
its root version and package version synchronized with the version in the OCI identifier. Because
the runtime already defaults to SQLite, `DATABASE_URL` becomes optional in the manifest; public
guidance states that the default container filesystem is ephemeral and persistent operation needs
an explicit database or mounted volume.

The image must carry both the source-repository label and
`io.modelcontextprotocol.server.name=io.github.fioenix/fn-ignis` before its first `v0.6.0`
publication so GitHub links the package to the repository and the MCP Registry can establish
ownership. The tag workflow rejects non-SemVer tags before any push, uses metadata-action's semver
rules and automatic stable-only `latest`, adds an OCI provenance attestation, and uses reviewed
full commit SHAs for every external `uses:` action, including GitHub-owned actions. No Docker Hub
mirror is added.

The direct-image default changes behavior for operators who bypass Compose and currently rely on
the worker `CMD`. Release notes and public guides call this out explicitly and give the stable
worker command (`python -m ignis.interfaces.cli.scheduler`). Compose remains the supported
background-worker surface and its behavioral smoke is mandatory.

The implementation updates the HTML/SVG diagram sources and regenerates their PNG derivatives
through the repository's diagram workflow, then visually verifies the rendered count. A text-only
edit that leaves a stale PNG is not accepted.

### 3. Treat GHCR visibility as a release-owner state transition

GitHub creates container packages private by default. Repository visibility and workflow success do
not change that. The exact `fioenix/fn-ignis` package must be resolved, then the release owner makes
it public through the package settings surface after the `v0.6.0` image has been published and the
one-way warning has been reviewed. This step is irreversible under the current platform contract,
exposes the package's historical versions as well, and is not delegated to Engineering. Historical
images are neither deleted nor silently retagged; their older default behavior remains versioned.

The active `gh` token currently lacks `read:packages`; a 403 from the package API is classified as
`UNREADABLE`, not private. The acceptance authority is the anonymous consumer: isolated pull plus
runtime smoke. Package metadata may be recorded when readable but cannot replace that behavior.

### 4. Replace remembered counts with governed contracts

Add one static contract that enumerates current operational surfaces and proves:

- current MCP catalog claims equal runtime/manifests at 47;
- fresh-init and upgrade guidance reaches `023`;
- `server.json` names an OCI package that matches the release version and public image;
- the image ownership label exactly matches `server.json.name` and public `mcp-publisher validate`
  succeeds;
- the Docker default and Compose worker overrides remain deliberately different; and
- the public-install text does not claim PyPI availability.

The gate must target explicit current-state sections rather than banning every historical `39`,
`45`, or `022`. Historical measurements in `BACKLOG.md`, migrations, tests, and dated evidence stay
unchanged when they describe what was true then. Negative controls independently mutate each claim
class and prove the gate can turn red.

### 5. Extend the release verdict without collapsing unknown into absent

Keep `scripts/check_release_state.py` as the quick Git/GitHub surface reader and extend its pure
surface/verdict model only where backward compatibility stays clear. Add
`scripts/public_release_acceptance.py` for the expensive distribution checks. It emits a structured
record using the state model in [contracts/release-verdict.md](contracts/release-verdict.md): each
required surface is `VERIFIED`, `MISSING`, `FAILED`, or `UNREADABLE`; PyPI is `DEFERRED`.

The combined verdict is `RELEASED` only when every required surface is `VERIFIED`. A missing fact
is evidence of absence; a command/auth/network failure is `UNREADABLE`; a fetched artifact that
does not satisfy its contract is `FAILED`. This preserves the three-state lesson already encoded in
the existing release checker while adding behavioral distribution evidence.

The script redacts URLs and subprocess output before persistence, creates temporary homes and
Docker configs under a unique temporary root, and removes only resources it created. Its JSON
output may be stored under `.handoff/` for review; no evidence file is committed as product code.
Anonymous pull/runtime acceptance does not verify provenance. The release owner separately runs
authenticated `gh attestation verify` against the immutable OCI digest, constrained to
`fioenix/fn-ignis`, the release commit/ref, and the expected signer workflow, and records that as a
different surface.

### 6. Cut one atomic MINOR release candidate

After behavior and docs are green, update `0.5.0` to `0.6.0` in the six controlled files, both
`server.json` version fields and its OCI identifier tag, the `CITATION.cff` date, and the
`BACKLOG.md` banner in one commit. Run `uv lock`; never hand-edit the lock. A static version-parity
test and `uv lock --check` are the release-candidate gate.

The release notes name the shipped Plan 008 outcomes: migration `023`, two evidence-qualification
MCP tools, decision-grade fail-closed analysis, and the truthful public distribution policy. They
also state the limits: PyPI deferred, no persistent database migrated by the release, browser
connectors remain on-demand, and no new multi-architecture container guarantee.

### 7. Separate Engineering from release ownership

Claude Code owns the RED→GREEN repository work, atomic commits, local verification, and a bounded
handoff on the feature branch. It must not push, merge, tag, change package visibility, publish a
Release, or migrate persistent data.

Codex owns acceptance and release decisions: independently verify the branch and commits, request
fresh review, push/create the PR, monitor required checks, merge into `main`, change the exact GHCR
package to public, tag the verified merge commit, publish the GitHub Release, monitor the container
workflow, and run both public clean-room paths. A merge is not reported as a release.

## Release Sequence

1. Claude Code implements repository tasks and leaves a clean, committed feature branch plus
   `.handoff/009-public-distribution-v0.6.0.handoff.md`.
2. Codex independently verifies diffs, commits, targeted tests, full gates, package contents, and
   negative controls; Critical/Important review findings return for one fix pass.
3. Codex pushes the feature branch, opens the PR, waits for CI/Compose/Performance/secret gates, and
   merges only a green reviewed candidate to `main`.
4. Codex reruns the release gates on the exact `main` merge commit and records its full SHA.
5. Codex resolves the exact `fioenix/fn-ignis` package and repository linkage without changing its
   visibility, then creates and pushes annotated tag `v0.6.0` on the verified `main` commit.
6. Codex waits for the tag-driven Docker workflow and provenance attestation to publish the correct
   image while it is still private, then verifies the attestation against the immutable digest with
   authenticated release-owner credentials and exact repository/ref/workflow constraints.
7. Codex accepts the one-way public visibility change for that exact package, then runs public
   tagged-source bootstrap, isolated anonymous container pull/runtime smoke against the recorded
   image digest, and public `mcp-publisher validate` against `server.json`.
8. After those distribution paths pass, Codex publishes the GitHub Release, runs the combined live
   verdict, updates post-release state, and only then calls `v0.6.0` released. Any partial state is
   reported literally and remains open.

## Complexity Tracking

No constitution violation is accepted. The one new acceptance script exists because current local
tests cannot prove public-tag or anonymous-container behavior; extending a product runtime module
or adding a service would be a larger and less truthful solution.
