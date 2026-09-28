# Research: Public Distribution and v0.6.0 Release

## Decision 1: Require source bootstrap and public GHCR; defer PyPI

**Decision**: `v0.6.0` ships through an immutable public source tag and
`ghcr.io/fioenix/fn-ignis`. PyPI remains explicitly deferred.

**Rationale**: Source bootstrap is already the product's zero-configuration install contract, and
the GHCR workflow already builds an image on tags. These are the smallest surfaces that can be made
truthful and exercised now. Publishing to PyPI would add namespace ownership, trusted-publisher
configuration, a third install path, and another long-lived release credential/policy without being
required for current users.

**Alternatives considered**:

- Publish source only: rejected because an existing production Compose file already promises GHCR.
- Publish PyPI in this release: deferred because it expands release authority and acceptance beyond
  the owner-approved policy.
- Add Docker Hub: rejected as a second container authority with no current consumer requirement.

## Decision 2: Make the OCI image's default process the MCP server

**Decision**: Direct OCI execution starts the MCP stdio server. Compose explicitly continues to run
the scheduler worker.

**Rationale**: The MCP Registry supports `registryType: "oci"` with stdio transport. Because this
manifest declares no command override, the project's executable contract requires the image
default to speak MCP. Today `server.json` claims a PyPI package and the Dockerfile defaults to the
worker. Both Compose files already override the command to the scheduler, so changing the image
default separates direct MCP consumption from the worker role without changing deployed Compose
behavior. Direct `docker run` users who relied on the old worker default do pay a behavior-change
cost and receive an explicit command and release-note migration.

**Alternatives considered**:

- Keep the worker default and point `server.json` at OCI: rejected because the manifest would lie
  about the transport.
- Keep the PyPI declaration without publishing: rejected because a registry manifest must name an
  obtainable artifact.
- Build separate MCP and worker images: rejected as unnecessary duplication; the byte contents are
  the same and command selection already distinguishes the roles.

**Primary reference**: [MCP Registry `server.json` format](https://github.com/modelcontextprotocol/registry/blob/main/docs/reference/server-json/generic-server-json.md)

## Decision 3: Prove GHCR access with an isolated real pull

**Decision**: Public-container acceptance uses an empty Docker configuration, removes ambient
GitHub credentials, performs a complete pull, records the digest, and runs an MCP conversation.

**Rationale**: GitHub documents that public Container Registry packages permit anonymous access,
but new packages default to private. The live baseline proves the gap: the v0.5.0 publish workflow
succeeded, while an isolated anonymous manifest request returned `unauthorized`. Reading workflow
YAML, repository visibility, or an authenticated cache would repeat the exact false-positive class
this plan exists to close.

**Alternatives considered**:

- Read package visibility through the current `gh` token: rejected as the authority because the
  token currently returns 403 without `read:packages`.
- Inspect only the manifest: rejected because layer authorization can still fail.
- Trust a successful workflow: rejected because publishing bytes and making them public are
  independent states.

**Primary references**:

- [Configuring package visibility](https://docs.github.com/en/packages/learn-github-packages/configuring-a-packages-access-control-and-visibility)
- [Working with the Container registry](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry)

## Decision 4: Keep the public-package visibility change release-owner only

**Decision**: Engineering prepares and proves the package identity; Codex performs the exact
`fioenix/fn-ignis` visibility change after the `v0.6.0` image is published during release.

**Rationale**: GitHub warns that a public package cannot be made private again. The owner explicitly
approved public GHCR in the Plan 009 direction, but the target still must be resolved from live
state before the irreversible action. Package visibility applies to existing historical versions
as well, so they are preserved and not silently retagged or deleted. Delegating the change inside a
coding pass would mix repository work with a one-way external state change.

**Alternatives considered**:

- Flip visibility before the v0.6.0 tag workflow: rejected because the v0.5.0 image still defaults
  to the worker and the manifest remains false.
- Automate visibility in the workflow: rejected because no reviewed, necessary API contract was
  found and repeated workflow runs must not reapply an irreversible administrative action.

## Decision 5: Pin the publication workflow and attest the image

**Decision**: Pin every external `uses:` action in `docker-publish.yml` to a reviewed full commit
SHA, keep its release comment, reject non-SemVer tag events before push, use metadata-action's
stable-SemVer `latest` behavior, and add an OCI provenance attestation for the pushed digest.

**Rationale**: The distribution workflow is part of the released supply chain. GitHub recommends
commit-SHA pinning for actions, and its current container-publishing example grants
`attestations: write` plus `id-token: write` and attests the exact build digest. The repository's CI
workflows already use this review pattern; the Docker workflow is the stale exception.

**Alternatives considered**:

- Keep mutable major tags: rejected because a later upstream retag could change release behavior
  without a repository diff.
- Add signing keys: rejected because GitHub's OIDC-backed attestation covers provenance without a
  new long-lived secret.

**Primary reference**: [Publishing Docker images](https://docs.github.com/en/actions/tutorials/publish-packages/publish-docker-images)

## Decision 6: Bind OCI ownership to the MCP Registry identity

**Decision**: The image carries
`io.modelcontextprotocol.server.name=io.github.fioenix/fn-ignis`, exactly matching
`server.json.name`, and the public image is checked with `mcp-publisher validate`.

**Rationale**: MCP Registry OCI publication uses this label as the ownership binding. A fetchable
image with a valid JSON shape is still unpublishable when the label is absent or different. Static
Dockerfile/image-inspect tests catch local drift; publisher validation proves the public bytes.

**Primary reference**: [MCP Registry Docker/OCI package requirements](https://github.com/modelcontextprotocol/registry/blob/main/docs/modelcontextprotocol-io/package-types.mdx#dockeroci-images)

## Decision 7: Govern current claims without rewriting history

**Decision**: Static gates inspect explicit current-state surfaces and allow dated historical
measurements to keep their original 39/45/022 values.

**Rationale**: Live operational claims must say 47 tools and migration endpoint 023. However,
historical backlog entries, migration names, tests for upgrading from 021 to 022, and dated evidence
are not drift. A global text replacement would erase provenance and corrupt valid contracts.

**Observed current drift on 2026-09-28**:

- `AGENTS.md`: 39-tool independence claim.
- `.github/workflows/ci.yml`: 39-tool clean-user comment.
- `docs/PROJECT_REVIEW_CONTEXT.md`: 39-tool current product description.
- `BACKLOG.md`: 45-tool version banner and current-accomplishments catalog.
- `src/ignis/interfaces/cli/setup_bundle.py`: generated Antigravity instruction and fallback count.
- Current architecture/pipeline SVG and HTML exports: 39-tool product labels.
- `README.md`, `docs/USER_GUIDE.md`, and Vietnamese equivalents: fresh-init verification and
  upgrade guidance stop at migration 022.
- `server.json`: PyPI package claim for an intentionally deferred/unpublished surface.
- `Dockerfile`: scheduler default inconsistent with an OCI stdio manifest.

**Alternatives considered**:

- Ban the old tokens everywhere: rejected because it would break historical evidence and migration
  tests.
- Fix prose only: rejected because the same drift would recur without executable negative controls.

## Decision 8: Use a fail-closed four-state release observation

**Decision**: Required surfaces use `VERIFIED`, `MISSING`, `FAILED`, or `UNREADABLE`; intentionally
excluded surfaces use `DEFERRED`. Only all-required `VERIFIED` yields `RELEASED`.

**Rationale**: The existing release checker already preserves the crucial difference between
GitHub saying no release exists and GitHub failing to answer. Public distribution adds the same
distinction for clone, pull, digest, workflow, and runtime checks. Boolean collapse would turn an
auth or network failure into a false release decision.

**Alternatives considered**:

- Boolean pass/fail: rejected because it cannot distinguish absence, bad bytes, and unread state.
- Treat a previous green run as current state: rejected because public visibility and tags are
  mutable external facts.

## Decision 9: Separate anonymous distribution from authenticated provenance

**Decision**: Anonymous container acceptance proves fetchability and runtime behavior. Release-owner
attestation verification is a distinct authenticated observation against the immutable digest,
constrained to the repository, source commit/ref, and signer workflow.

**Rationale**: `gh attestation verify oci://...` requires registry authentication and an owner or
repository constraint. Combining it with a credential-free consumer run would either make a false
anonymous claim or silently weaken provenance verification.

**Primary reference**: [GitHub CLI attestation verification](https://cli.github.com/manual/gh_attestation_verify)

## Decision 10: Cut `0.6.0` as one MINOR increment

**Decision**: Bump `0.5.0` to `0.6.0` after all behavior changes are green.

**Rationale**: Plan 008 adds migration 023, two public MCP tools, and a new backward-compatible
analytical model. The repository's SemVer rules classify each as MINOR and prohibit number
skipping. The direct-image default also changes for authenticated/private-image users, but it is a
distribution entrypoint correction during the `0.x` beta rather than an architectural overhaul;
the image has not yet been publicly pullable, Compose retains its worker contract, and direct users
receive an explicit migration command. The release commit updates all six controlled files and
regenerates `uv.lock` atomically.

**Alternatives considered**:

- `0.5.1`: rejected because the public API and schema additions are features, not a patch.
- `1.0.0`: rejected because enterprise multi-tenancy and production-stability milestones remain
  outside the beta release.

## Verified Baseline

Measured in an isolated worktree at `63c25bef40610c8688bd54061ebc066d6c5940f6` on 2026-09-28:

- `tests/unit`: 1,226 passed, 3 skipped, 0 failed; two pre-existing coroutine warnings.
- Mainline CI, Compose Init, and Performance runs for that commit: success.
- GitHub Release `v0.5.0`: published.
- Docker Publish run for `v0.5.0`: success.
- Anonymous isolated manifest request for `ghcr.io/fioenix/fn-ignis:0.5.0`: `unauthorized`.
- `gh` package metadata read: `UNREADABLE` because the token lacks `read:packages`.
- Current runtime/manifests: 47 tools; newest migration: `023_evidence_qualification.sql`.
