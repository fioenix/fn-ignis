# Contract: Public Distribution Surfaces

## Required Source Surface

**Identifier**: `https://github.com/fioenix/fn-ignis.git` at `v0.6.0`

**Consumer contract**:

1. Clone by exact tag without authentication.
2. Resolve the tag to the verified `main` release commit.
3. Run `./scripts/bootstrap.sh` under an isolated home.
4. Confirm the locked install, SQLite database, seeds, and migration endpoint `023`.
5. Complete MCP initialization, discover exactly 47 tools, and call `get_runtime_config`.

**Failure contract**:

- Authentication requested or checkout unavailable: `MISSING` when GitHub positively reports the
  tag/repository absent; otherwise `UNREADABLE`.
- Tag resolves to the wrong commit: `FAILED`.
- Bootstrap, schema, discovery, or tool call fails: `FAILED` with bounded stdout/stderr.

## Required Container Surface

**Identifier**: `ghcr.io/fioenix/fn-ignis:0.6.0`

**Consumer contract**:

1. Use an empty Docker configuration directory and no GitHub credentials.
2. Resolve the release tag and fully pull the selected/default-platform manifest, config, and every
   referenced layer.
3. Record the immutable repo digest.
4. Start the immutable digest through `docker run --rm -i`, complete the same MCP smoke
   conversation, reject non-MCP stdout, and require prompt exit when stdin closes.
5. Verify tags `0.6.0`, `0.6`, and `latest` resolve to the accepted digest.
6. Verify source-repository linkage and
   `io.modelcontextprotocol.server.name=io.github.fioenix/fn-ignis` on that digest.
7. After the image is public, run `mcp-publisher validate` against the committed `server.json`.

**Release-owner provenance contract**:

Provenance is deliberately not part of the anonymous consumer contract. With release-owner
registry authentication, run `gh attestation verify` against the immutable OCI digest and constrain
the verification to `fioenix/fn-ignis`, the release commit/ref, and the expected signer workflow.
Record this separately from anonymous pull/runtime evidence.

**Role contract**:

- Direct image default: MCP stdio server.
- `docker-compose.yml` worker command: scheduler.
- `docker-compose.prod.yml` worker command: scheduler.
- Direct users who still want the pre-`0.6.0` worker behavior must invoke
  `python -m ignis.interfaces.cli.scheduler` explicitly; release notes treat this as an upgrade
  behavior change.

**Failure contract**:

- `unauthorized` from an isolated pull: `MISSING` public access, even if authenticated pull works.
- Manifest succeeds but a layer fails: `FAILED`.
- Image runs a worker or another non-MCP process by default: `FAILED`.
- Package API returns 401/403 or network failure: metadata is `UNREADABLE`; continue to the
  anonymous behavior check.
- Attestation authentication or network failure: provenance is `UNREADABLE`; it does not weaken or
  replace the independently observed anonymous pull result.

## Deferred PyPI Surface

PyPI is not a `v0.6.0` distribution. Public docs and manifests must not offer `pip install`, `uvx`,
or a `registryType: "pypi"` package for `fn-ignis` until a later decision authorizes publication and
its own acceptance path.

The project may still build a wheel and sdist locally and attach or inspect them as release
artifacts. Building a Python distribution is packaging verification, not PyPI publication.

## Version and Tag Contract

- Product version: `0.6.0`.
- Git tag: annotated `v0.6.0` on the verified `main` commit.
- OCI tags: `0.6.0`, `0.6`, `latest`.
- No tag is created before required local and PR gates pass.
- No `RELEASED` claim is made before both public consumer contracts pass.

## Security Contract

- No persistent credential is required for either consumer path.
- The publisher uses GitHub's repository-scoped workflow token and OIDC attestation, not a new
  long-lived registry secret.
- Evidence redacts URL credentials, environment values, and subprocess output matching the
  repository's secret patterns.
- Temporary homes, Docker configurations, checkouts, databases, containers, and volumes are unique
  to the acceptance run and are removed only by their creator.
