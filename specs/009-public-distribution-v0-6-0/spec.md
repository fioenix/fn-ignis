# Feature Specification: Public Distribution and v0.6.0 Release

**Feature Branch**: `codex/009-public-distribution-v0.6.0`

**Created**: 2026-09-28

**Status**: Accepted for planning

**Input**: Product-owner direction to make source bootstrap and public GHCR the required
distribution surfaces, defer PyPI, prove both paths from clean public inputs, and release the
decision-grade evidence work as `v0.6.0` after correcting stale tool and migration claims.

## Clarifications

### Session 2026-09-28

- Q: Which public distribution surfaces are required for `v0.6.0`? → A: A tagged public source
  checkout with the one-command bootstrap and a public GHCR image are required. PyPI is explicitly
  deferred and is not a release blocker (owner decided in the Plan 009 direction).
- Q: What does the GHCR image run when used directly? → A: The image's default behavior serves
  the MCP stdio surface advertised by the public registry manifest. The existing Compose files
  continue to select the optional scheduler worker explicitly (agent decided from the dual-track
  contract; cost if wrong: direct image consumers would receive a worker instead of the advertised
  MCP server, or Compose users would lose the worker role).
- Q: What evidence proves public availability? → A: A successful build or authenticated pull is
  insufficient. Acceptance requires an actual source checkout from the public tag and an actual
  container pull with isolated, empty client credentials, followed by runtime checks against the
  pulled bytes (owner direction plus current GitHub Container Registry access semantics).
- Q: Why is this `0.6.0` rather than `0.5.1`? → A: Plan 008 added migration `023`, two public MCP
  tools, and a new decision-grade analytical model, all backward-compatible additions. The release
  therefore increments MINOR exactly once under the repository's SemVer policy.

## User Scenarios & Testing

### User Story 1 - Install From the Public Source Release (Priority: P1)

As a new self-hosting operator, I want to obtain an immutable public source release and bootstrap
it without repository credentials or local developer state so that I can start Ignis through the
documented zero-configuration path.

**Why this priority**: Source bootstrap is the universal distribution path and the fallback when a
container runtime is unavailable. A release that only works from the maintainer's checkout has not
been distributed.

**Independent Test**: In a disposable environment with an empty home directory and no existing
checkout, clone only tag `v0.6.0` through the public URL, run the documented bootstrap command, open
an MCP session, discover exactly 47 tools, and execute one deterministic tool without connector
credentials.

**Acceptance Scenarios**:

1. **Given** no GitHub credentials and no local repository copy, **When** an operator clones tag
   `v0.6.0`, **Then** the checkout succeeds and resolves to the release commit on `main`.
2. **Given** an isolated home and the tagged checkout, **When** the operator runs the documented
   bootstrap command, **Then** it installs the locked dependencies, creates the SQLite default,
   applies the complete packaged schema through migration `023`, and registers the supported MCP
   clients without copying credentials into their configuration.
3. **Given** the bootstrapped tagged checkout, **When** an MCP client initializes and lists tools,
   **Then** it receives exactly 47 independently callable tools and can execute a deterministic
   no-credential operation.
4. **Given** a source archive or checkout missing migration `023`, either new qualification use-case
   module, a maintained template, or a declared manifest, **When** clean-room acceptance runs,
   **Then** acceptance fails before the release is called usable.

---

### User Story 2 - Pull and Run the Public Container Anonymously (Priority: P1)

As a container operator or MCP client, I want to pull a versioned Ignis image without signing in
and run the MCP server it advertises so that GHCR is a real public distribution path rather than a
private build artifact.

**Why this priority**: The current `0.5.0` image was built successfully but an anonymous manifest
request returns `unauthorized`. Public repository visibility and a green publish workflow do not
make the package public.

**Independent Test**: With an empty container-client configuration and no GitHub environment
credentials, pull `ghcr.io/fioenix/fn-ignis:0.6.0`, initialize its default stdio process, list 47
tools, inspect its immutable digest, source label, and MCP Registry ownership label, and separately
start the existing production Compose worker path.

**Acceptance Scenarios**:

1. **Given** a machine with no GHCR login or cached credential, **When** it pulls the `0.6.0` image,
   **Then** the selected/default-platform manifest, config, and every referenced layer download
   without authentication.
2. **Given** the pulled versioned image, **When** it starts with its default command, **Then** it
   serves the MCP stdio protocol and exposes exactly 47 tools.
3. **Given** the same image, **When** the production Compose configuration starts its worker
   service, **Then** Compose's explicit command still starts the optional scheduler worker.
4. **Given** the release tag, **When** container metadata is inspected, **Then** `0.6.0`, `0.6`, and
   `latest` resolve to the released image as defined by policy, the image links to the public source
   repository, and the recorded digest is the one exercised by clean-room acceptance.
5. **Given** an authenticated maintainer machine can pull the image but an isolated client cannot,
   **When** release evidence is evaluated, **Then** the GHCR distribution gate remains failed.
6. **Given** the package is public, **When** the release owner validates `server.json` with the MCP
   Registry publisher, **Then** the manifest, OCI package, exact ownership label, and transport pass
   validation against the public image.

---

### User Story 3 - Receive One Truthful Public Release Contract (Priority: P1)

As an operator, MCP registry consumer, or reviewer, I want every current release surface to agree
on the available tools, migration endpoint, distribution method, and version so that I do not act
on a stale or nonexistent package.

**Why this priority**: Current tracked surfaces disagree: they report 39, 45, or 47 tools; parts of
the install documentation stop at migration `022`; and `server.json` advertises a PyPI package that
the distribution policy defers.

**Independent Test**: Scan every current operational document, manifest, workflow assertion, and
release-controlled version file; then validate the registry manifest against the actual public
artifact and MCP runtime.

**Acceptance Scenarios**:

1. **Given** the current `v0.6.0` documentation and manifests, **When** a consumer reads the tool
   catalog or performs discovery, **Then** every current-state claim and the runtime agree on 47
   tools; historical measurements remain clearly historical rather than being rewritten.
2. **Given** a fresh or upgraded installation, **When** a consumer follows the migration guidance,
   **Then** the documented and packaged chain reaches migration `023` and explains that existing
   databases apply every missing migration in order.
3. **Given** PyPI remains deferred, **When** a client reads `server.json`, **Then** it does not claim
   that a PyPI package exists and it identifies only a distribution that can be fetched publicly
   and run with the declared transport.
4. **Given** the release commit, **When** version parity is checked, **Then** all six
   release-controlled files, the root version, package version, and OCI identifier tag in
   `server.json`, the lockfile's project version, the release tag, and the release notes agree on
   `0.6.0`.
5. **Given** a stale `0.5.0` version or a current-state `39`/`45`-tool or migration-`022` endpoint
   claim remains in a governed surface, **When** the release gate runs, **Then** it fails with the
   exact file and claim instead of relying on a manual search result.

---

### User Story 4 - Verify Shipping From External Surfaces (Priority: P2)

As the release owner, I want one evidence bundle that distinguishes code merged to `main` from a
release that users can actually obtain so that a partial publish is reported as not released.

**Why this priority**: A tag, GitHub Release, public repository, GHCR image, and clean-room runtime
are separate facts. Previous checks correctly covered the first three but not anonymous container
distribution or tagged-source usability.

**Independent Test**: Starting from the final release commit, run the complete local gates, merge
the reviewed release branch, create the tag and GitHub Release, wait for the tag-driven image build,
then query and exercise every external surface without reusing the release operator's checkout or
container credentials.

**Acceptance Scenarios**:

1. **Given** any required local or CI gate is red, skipped outside its documented exception, or
   unreadable, **When** release readiness is evaluated, **Then** no release tag is created.
2. **Given** the release changes are not merged to `main`, **When** tagging is attempted, **Then**
   the release process refuses to tag a side branch.
3. **Given** a tag exists but the GitHub Release is missing, the container workflow failed, the
   package is private, or either clean-room path fails, **When** live state is checked, **Then** the
   verdict is `NOT RELEASED` or `INDETERMINATE`, never `RELEASED`.
4. **Given** all required live surfaces and clean-room paths pass, **When** the release verdict is
   recorded, **Then** it names the tag commit, GitHub Release URL, container digest, anonymous-pull
   result, source-checkout result, and any intentionally deferred surface.

### Edge Cases

- The GHCR workflow succeeds while the package retains its default private visibility.
- A cached Docker login makes a private image look public; acceptance must isolate client state.
- An anonymous manifest lookup succeeds but one or more image layers cannot be downloaded.
- The package visibility API cannot be read because the active token lacks `read:packages`; this is
  an unread fact, not evidence that the package is either public or private.
- Making the GHCR package public is irreversible under the current platform contract; the exact
  `fioenix/fn-ignis` target and package ownership must be resolved before the visibility change.
- Making the package public also exposes its existing historical image versions. Plan 009 must not
  delete or silently retag those versions; only `0.6.0`, `0.6`, and `latest` carry the new direct-MCP
  default contract.
- A tag-driven image build publishes from a commit other than the tag or omits the exact version
  tag while updating `latest`.
- The direct image command starts the background worker although the registry manifest declares an
  MCP stdio server.
- An operator starts the image directly expecting the pre-`0.6.0` worker default and silently gets
  the MCP server because the direct-image behavior change was not documented.
- Compose loses its explicit worker command after the image default changes.
- A local tracked-file copy passes while the public Git tag omits a newly added file.
- Current operational guidance is stale, while a historical backlog measurement legitimately
  records an older tool or migration count.
- A version bump updates the six visible files but leaves `uv.lock` at `0.5.0`.
- A GitHub or GHCR outage makes a required fact unreadable after tagging.

## Requirements

### Functional Requirements

- **FR-001**: The release MUST define tagged public source bootstrap and public GHCR as the two
  required distribution surfaces for `v0.6.0`.
- **FR-002**: PyPI publication MUST remain outside the `v0.6.0` release scope and MUST NOT be
  represented as an available package in any public manifest or installation instruction.
- **FR-003**: Every current operational claim about the MCP catalog MUST agree with runtime
  discovery at exactly 47 tools; historical evidence MAY retain its original measured count when
  labelled with its date and context.
- **FR-004**: Every current installation and upgrade instruction MUST identify migration `023` as
  the current chain endpoint and MUST preserve the rule that existing databases apply every missing
  migration in filename order as the table owner.
- **FR-005**: The public source release MUST be retrievable by exact tag without authentication and
  MUST bootstrap successfully from an isolated home with no developer artifacts.
- **FR-006**: Source clean-room acceptance MUST prove the locked install, SQLite default, complete
  schema and seed load, supported client registration, 47-tool discovery, and one real
  no-credential MCP tool call.
- **FR-007**: The container package MUST be publicly visible and fully pullable without a token or
  prior registry login.
- **FR-008**: The versioned container MUST default to the MCP stdio server described by the public
  registry manifest because that manifest declares no command override, MUST emit only
  newline-delimited MCP JSON-RPC on stdout, MUST exit promptly when stdin closes, and MUST expose
  the same 47-tool contract as source bootstrap.
- **FR-009**: The local and production Compose definitions MUST continue to start the optional
  scheduler worker explicitly after the image default changes.
- **FR-010**: The container publication MUST produce the immutable `0.6.0` tag and the moving tags
  `0.6` and `latest` from the same validated stable-SemVer release event, with repository linkage
  and a recorded digest; malformed or prerelease tags MUST NOT move `latest`.
- **FR-011**: The container publication workflow MUST use reviewed full commit SHAs for every
  external `uses:` action, including GitHub-owned actions, and MUST publish build provenance for
  the released image.
- **FR-012**: The MCP registry manifest MUST describe a real public artifact and transport; it MUST
  not point at a nonexistent or deferred package. The image MUST carry
  `io.modelcontextprotocol.server.name=io.github.fioenix/fn-ignis`, exactly matching the manifest
  name, and the public image plus manifest MUST pass `mcp-publisher validate`.
- **FR-013**: The release preparation MUST increment `0.5.0` to `0.6.0` exactly once in
  `pyproject.toml`, `openclaw.json`, both `server.json` version fields and its OCI identifier tag,
  `CITATION.cff` including the release date, `.openclaw/config.yaml`, and the `BACKLOG.md` version
  banner.
- **FR-014**: The same atomic release commit MUST regenerate `uv.lock` through the package manager,
  and the lock check MUST pass without hand editing.
- **FR-015**: Before integration, the release candidate MUST pass the repository's unit,
  integration, PostgreSQL, fresh Compose, clean-user, wheel, lint, coverage, packaging, manifest,
  secret-scanning, and diff checks with every skip or environmental limitation named.
- **FR-016**: The release branch MUST be reviewed and merged into `main` before `v0.6.0` is tagged.
- **FR-017**: The annotated `v0.6.0` tag MUST point to the verified `main` release commit and the
  published GitHub Release MUST describe the two new MCP tools, migration `023`, the decision-grade
  evidence boundary, required distribution paths, upgrade guidance, and known limitations.
- **FR-018**: Post-release verification MUST read the public Git tag, repository visibility,
  published GitHub Release, tag-triggered container workflow, anonymous container pull, container
  digest, authenticated digest-bound provenance, tagged-source bootstrap, MCP discovery, and MCP
  Registry validation from their owning live surfaces. Anonymous distribution proof and
  authenticated release-owner provenance proof MUST remain separate observations.
- **FR-019**: A missing, failed, contradictory, or unreadable required surface MUST prevent a
  `RELEASED` verdict; unreadable state MUST remain distinct from proven absence.
- **FR-020**: The release MUST NOT migrate any persistent operator database, publish to PyPI,
  rotate credentials, or delete an existing package or release as a side effect.
- **FR-021**: Public guidance and release notes MUST identify the direct-image default change and
  give existing worker users the explicit scheduler command; runtime acceptance MUST start the
  production Compose worker and prove it executes the scheduler rather than only checking YAML.
- **FR-022**: `server.json` MUST represent `DATABASE_URL` as optional because the runtime defaults
  to SQLite, while container guidance MUST distinguish that ephemeral smoke default from a
  persistent database or mounted volume suitable for continuing operation.

### Key Entities

- **Release Candidate**: The reviewed commit proposed for `v0.6.0`, including its branch, mainline
  identity, gate results, and synchronized version set.
- **Source Distribution**: The public tag/archive plus bootstrap path, locked dependencies,
  packaged migrations and templates, and its clean-room acceptance result.
- **Container Distribution**: The GHCR package, version tags, immutable digest, source linkage,
  default runtime role, visibility, provenance, and anonymous-pull result.
- **Release Evidence Bundle**: The attributable facts collected from local gates, CI, Git, GitHub
  Releases, GHCR, tagged-source bootstrap, and runtime discovery.
- **Deferred Surface**: A named distribution channel intentionally excluded from this release;
  PyPI is the only deferred surface for Plan 009.

## Success Criteria

### Measurable Outcomes

- **SC-001**: A disposable environment with no repository credentials completes tagged-source
  bootstrap, discovers 47 tools, and performs one real deterministic MCP call with zero failures.
- **SC-002**: A container client with an empty credential directory downloads every `0.6.0` image
  layer, starts the default MCP process, and discovers 47 tools with zero authenticated requests.
- **SC-003**: The `0.6.0`, `0.6`, and `latest` container references resolve to the accepted release
  digest immediately after publication, and that digest is recorded in release evidence.
- **SC-004**: Automated drift gates report zero stale current-state tool counts, migration endpoints,
  PyPI availability claims, or release versions across governed surfaces.
- **SC-005**: All six release-controlled files, both `server.json` version fields and its OCI
  identifier tag, `uv.lock`, the annotated tag, and the GitHub Release agree on `0.6.0`.
- **SC-006**: Every required repository gate passes on the release commit; no PostgreSQL test is
  skipped, and each remaining skip is documented as intentional.
- **SC-007**: The live release checker reports `RELEASED` only after the public repository, tag,
  GitHub Release, public container, anonymous pull, and tagged-source acceptance are all positively
  observed; zero required fact is inferred from prose or configuration.

## Assumptions

- `v0.5.0` is the current published release and `v0.6.0` is the next available MINOR version.
- Plan 008 is already merged to `main`; Plan 009 packages and distributes that accepted work rather
  than changing the decision-grade evidence model.
- The repository stays public under `fioenix/fn-ignis`, and the required container stays under
  `ghcr.io/fioenix/fn-ignis`.
- The existing GHCR package belongs to the same personal account and can be made public by the
  release owner after verifying the exact target. The platform's one-way visibility warning is
  accepted as part of the explicit public-distribution decision.
- The production Compose files remain the supported background-worker entry point and already
  carry an explicit scheduler command.
- Release acceptance may use disposable local containers, temporary homes, and scratch databases;
  it does not require or authorize access to a persistent production database.

## Scope Boundaries

### In Scope

- Current tool-count, migration-endpoint, package-availability, and version drift.
- Truthful OCI distribution through public GHCR and a registry manifest that runs it as MCP stdio.
- Clean-room source and container acceptance.
- Formal `v0.6.0` preparation, integration, tagging, GitHub Release publication, and live readback.

### Out of Scope

- Publishing or reserving a PyPI package.
- Adding a hosted MCP endpoint or SaaS control plane.
- Changing the two new qualification tools or the Plan 008 analytical policy.
- Applying migration `023` to any persistent operator database.
- Adding Docker Hub or another container registry.
- Deleting, rewriting, or retagging historical GHCR image versions.
