---

description: "Dependency-ordered implementation and release tasks for public distribution and v0.6.0"
---

# Tasks: Public Distribution and v0.6.0 Release

**Input**: Design documents from `/specs/009-public-distribution-v0-6-0/`

**Prerequisites**: `plan.md`, `spec.md`, `research.md`, `data-model.md`, `contracts/`, `quickstart.md`

**Tests**: Required. Every repository behavior change follows RED → GREEN, and every public-state
claim requires a negative control or an unauthenticated behavioral probe.

**Ownership**: Claude Code executes Engineering tasks T001–T040 on the feature branch and stops
before external writes. Codex executes release-owner tasks T041–T050 after independent review.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel because it touches different files and has no dependency on another
  incomplete task in the same phase.
- **[Story]**: Maps the task to a user story in `spec.md`.
- Every task names the file that carries its durable result or evidence.

## Phase 1: Setup and RED Contracts

**Purpose**: Capture the live baseline and make every known distribution drift fail before changing
product or release surfaces.

- [X] T001 Create `.handoff/009-public-distribution-v0.6.0.handoff.md` with the base commit, clean/dirty status, `v0.5.0` live release facts, unit baseline, current GHCR anonymous `unauthorized` result, and the package-API `read:packages` limitation
- [X] T002 [P] Add RED current-state tests for 47-tool claims, migration endpoint `023`, no PyPI availability claim, and synchronized release versions in `tests/unit/test_public_distribution_contract.py`
- [X] T003 [P] Add RED verdict-state tests for `VERIFIED`, `MISSING`, `FAILED`, `UNREADABLE`, `DEFERRED`, and combined verdict precedence in `tests/unit/test_diagram_and_release_claims.py`
- [X] T004 [P] Add RED contracts for the Docker default MCP role, both Compose scheduler overrides, OCI `server.json`, all external workflow action pins, stable-SemVer release tags, source/ownership labels, and provenance attestation in `tests/unit/test_public_distribution_contract.py`
- [X] T005 Run the Phase 1 tests, confirm each new assertion fails for its intended current defect rather than import/setup noise, and record the exact RED results in `.handoff/009-public-distribution-v0.6.0.handoff.md`

**Checkpoint**: Each known false or stale release claim has an independently observed RED contract.

---

## Phase 2: Foundational Release Observation and MCP Smoke

**Purpose**: Build one fail-closed observation model and one MCP conversation reusable by source,
wheel, and container acceptance.

**CRITICAL**: No public-path story begins until this phase passes.

- [X] T006 Implement the typed surface record, required/deferred surface inventory, state validation, and pure verdict function in `scripts/public_release_acceptance.py`
- [X] T007 Add unit tests for duplicate/missing/unknown surface keys, full-SHA validation, secret redaction, and verdict serialization in `tests/unit/test_public_distribution_contract.py`
- [X] T008 Implement bounded command results that distinguish known absence from auth/network/tool failure and redact credential-bearing output in `scripts/public_release_acceptance.py`
- [X] T009 Generalize `scripts/wheel_mcp_smoke.py` to accept an optional caller-supplied server command while preserving the existing wheel default and exact 47-tool plus `get_runtime_config` checks
- [X] T010 Add RED→GREEN subprocess tests for local-Python and caller-supplied MCP smoke commands, timeout, malformed JSON, wrong tool count, and failed tool call in `tests/unit/test_public_distribution_contract.py`
- [X] T011 Implement unique temporary-root ownership, cleanup-on-success/failure, and JSON evidence output without environment or credential leakage in `scripts/public_release_acceptance.py`
- [X] T012 Run the foundational unit tests and existing wheel smoke tests, then record GREEN counts and any ruling in `.handoff/009-public-distribution-v0.6.0.handoff.md`

**Checkpoint**: A shared protocol smoke and release-state model can fail closed before touching a
live public surface.

---

## Phase 3: User Story 1 - Install From the Public Source Release (Priority: P1) MVP

**Goal**: Prove an exact public tag bootstraps and serves the 47-tool MCP contract without local
developer state.

**Independent Test**: Clone a fixture public tag into a disposable root, bootstrap under an isolated
home, verify schema through `023`, initialize MCP, discover 47 tools, and call
`get_runtime_config`.

### Tests for User Story 1

- [X] T013 [US1] Add RED source-observer tests for exact-tag clone, resolved commit, isolated home, no inherited `.venv`/`.env`/MCP config, and public URL credential rejection in `tests/unit/test_public_distribution_contract.py`
- [X] T014 [P] [US1] Extend `tests/integration/test_clean_user_journey.py` to prove migration `023` tables and packaged qualification modules are present after bootstrap, without contacting credentialed connectors

### Implementation for User Story 1

- [X] T015 [US1] Implement `source` mode with exact-tag clone, isolated bootstrap, schema/seed readback, and MCP smoke in `scripts/public_release_acceptance.py`
- [X] T016 [US1] Make source acceptance compare the cloned tag SHA with the expected verified `main` commit and classify missing tag, wrong commit, bootstrap failure, and unreadable network separately in `scripts/public_release_acceptance.py`
- [X] T017 [P] [US1] Update source-bootstrap, 47-tool catalog, and migration-`023` install/upgrade guidance in `README.md` and `docs/USER_GUIDE.md`
- [X] T018 [P] [US1] Apply the same source-bootstrap and migration guidance in target-market Vietnamese in `README.vi.md` and `docs/USER_GUIDE.vi.md`
- [X] T019 [US1] Run the source observer unit suite and tracked-tree clean-user journey, confirm GREEN and no credential/quota use, and record results in `.handoff/009-public-distribution-v0.6.0.handoff.md`

**Checkpoint**: The source path is implementation-complete and testable before a public `v0.6.0`
tag exists; the live tag scenario remains a release-owner task.

---

## Phase 4: User Story 2 - Pull and Run the Public Container Anonymously (Priority: P1)

**Goal**: Make GHCR a truthful OCI MCP distribution while preserving the explicit Compose worker.

**Independent Test**: Pull a fixture image with isolated Docker credentials, record its digest,
complete the default MCP smoke, and verify both Compose files still select the scheduler.

### Tests for User Story 2

- [X] T020 [US2] Add RED container-observer tests for empty Docker config, stripped GitHub credentials, selected-platform manifest/config/layer pull, digest capture, default MCP smoke with clean stdout/EOF exit, three-tag parity, and anonymous `unauthorized` classification in `tests/unit/test_public_distribution_contract.py`
- [X] T021 [P] [US2] Add RED static contracts for both `server.json` version fields, OCI identity/transport, optional SQLite-default metadata, Dockerfile MCP default, both Compose scheduler commands, source/ownership labels, stable-SemVer tags, all external action pins, and attestation permissions/subject in `tests/unit/test_public_distribution_contract.py`

### Implementation for User Story 2

- [X] T022 [US2] Change the Dockerfile default from scheduler to `ignis.interfaces.mcp.server`, add `LABEL io.modelcontextprotocol.server.name="io.github.fioenix/fn-ignis"`, and retain the explicit scheduler commands in `docker-compose.yml` and `docker-compose.prod.yml`
- [X] T023 [US2] Replace the deferred/nonexistent PyPI package in `server.json` with the version-matched `ghcr.io/fioenix/fn-ignis` OCI stdio package, retain its package-version field, mark the runtime-defaulted `DATABASE_URL` optional, and document ephemeral SQLite versus persistent configuration
- [X] T024 [US2] Pin every external `uses:` action in `.github/workflows/docker-publish.yml` to a reviewed full commit SHA with release comments, add repository source and exact MCP server-name metadata, fail before push on non-SemVer tags, and use metadata-action semver plus automatic stable-only `latest` for `0.6.0`/`0.6`/`latest`
- [X] T025 [US2] Add the minimum `attestations: write` and `id-token: write` permissions plus digest-bound OCI provenance in `.github/workflows/docker-publish.yml`
- [X] T026 [US2] Implement `container` mode with isolated Docker state, selected-platform anonymous pull, digest/three-tag/source/ownership-label readback, and caller-supplied MCP smoke in `scripts/public_release_acceptance.py`; keep authenticated provenance outside this anonymous observer
- [X] T027 [US2] Run the container contract tests, build the local image, inspect both labels, smoke its digest-pinned default MCP role, actually start the production Compose worker and prove the scheduler process without persistent data, then record GREEN results in `.handoff/009-public-distribution-v0.6.0.handoff.md`

**Checkpoint**: The locally built image and public manifest contract agree; live GHCR visibility and
anonymous pull remain release-owner actions.

---

## Phase 5: User Story 3 - Receive One Truthful Public Release Contract (Priority: P1)

**Goal**: Eliminate current operational drift while preserving dated historical evidence.

**Independent Test**: Run the governed-surface scan and prove current claims resolve to 47 tools,
migration 023, OCI distribution, and one version, while legitimate historical 39/45/022 references
remain accepted.

### Tests for User Story 3

- [X] T028 [US3] Add negative controls that independently mutate a current tool count, migration endpoint, PyPI/OCI claim, each Compose override, Docker role, each ownership label, every release tag digest, and each manifest/release version field, and prove `tests/unit/test_public_distribution_contract.py` turns red for each
- [X] T029 [US3] Add allowlisted historical-reference tests so dated backlog measurements, migration `022` upgrade tests, and filenames remain valid while unlabeled current claims fail in `tests/unit/test_public_distribution_contract.py`

### Implementation for User Story 3

- [X] T030 [P] [US3] Update current tool-count claims in `AGENTS.md`, `.github/workflows/ci.yml`, and generated/fallback Antigravity instructions in `src/ignis/interfaces/cli/setup_bundle.py` to 47; make discovery failure fail closed rather than emit a false success count
- [X] T031 [P] [US3] Update current tool-count claims in `docs/PROJECT_REVIEW_CONTEXT.md` and the `BACKLOG.md` banner/current accomplishments; use the repository's diagram workflow to update both architecture/pipeline HTML and SVG sources, regenerate both PNG derivatives, and visually verify 47 while leaving dated evidence intact
- [X] T032 [US3] Update current install and upgrade claims in `README.md`, `README.vi.md`, `docs/USER_GUIDE.md`, and `docs/USER_GUIDE.vi.md` so fresh-init verification and existing-database guidance reach migration `023`
- [X] T033 [US3] Run the public distribution, repository convention, manifest-drift, release-claim, and documentation contract suites; record exact GREEN counts and retained historical references in `.handoff/009-public-distribution-v0.6.0.handoff.md`

**Checkpoint**: Current release truth is governed by tests; history is not rewritten to make a text
search look clean.

---

## Phase 6: User Story 4 - Prepare a Verifiable v0.6.0 Candidate (Priority: P2)

**Goal**: Produce one reviewed, fully verified release candidate without performing any external
release action.

**Independent Test**: Run the full local release gate, inspect the built distributions, verify
version parity, and produce a clean committed branch plus bounded handoff.

### Candidate Gate and Versioning

- [X] T034 [US4] Run unit, provisioned dual-backend integration with no PostgreSQL skip, fresh Compose with an explicit no-skip assertion, clean-user, exact-one-wheel smoke from a cleaned `dist/`, local container/Compose smoke, Ruff, freshly erased-and-measured SC-004 coverage, committed-range diff checks, `uv lock --check`, and `uv build`; record all counts, skips, warnings, and environment limits in `.handoff/009-public-distribution-v0.6.0.handoff.md`
- [X] T035 [US4] Add a RED version-parity case for all six release-controlled files, both `server.json` version fields plus OCI identifier tag, `CITATION.cff` date, and `uv.lock` in `tests/unit/test_public_distribution_contract.py`
- [ ] T036 [US4] Update `pyproject.toml`, `openclaw.json`, both `server.json` version fields plus OCI identifier tag, `CITATION.cff`, `.openclaw/config.yaml`, and the unreleased `BACKLOG.md` v0.6.0 banner in one release-preparation commit, then regenerate `uv.lock` with `uv lock`
- [ ] T037 [US4] Inspect the wheel and sdist inventories for migration `023`, qualification modules, templates, manifests, and version `0.6.0`, and record byte-level evidence in `.handoff/009-public-distribution-v0.6.0.handoff.md`
- [X] T038 [US4] Draft `.handoff/009-public-distribution-v0.6.0-release-notes.md` covering migration `023`, two MCP tools, decision-grade evidence, source/GHCR policy, the direct-image default change and explicit worker command, ephemeral SQLite guidance, upgrade steps, PyPI deferral, no persistent migration, and architecture limits
- [ ] T039 [US4] Rerun the complete candidate gate after the version commit and require zero failures, no PostgreSQL skip, documented intentional skips only, Ruff clean, lock clean, build clean, and no secret finding; append final evidence to `.handoff/009-public-distribution-v0.6.0.handoff.md`
- [ ] T040 [US4] Commit every Engineering change atomically, verify a clean tracked tree and English imperative commit messages, and finish `.handoff/009-public-distribution-v0.6.0.handoff.md` with full commit SHAs, diff scope, commands, results, limitations, and the explicit statement that no push/merge/tag/package-visibility/Release/persistent migration occurred

**Checkpoint**: Engineering complete and explicitly parked on the feature branch. Claude Code stops
here and hands control to Codex.

---

## Phase 7: Release-Owner Integration and Public Shipping

**Purpose**: Codex independently accepts, integrates, publishes, and verifies the exact candidate.

- [ ] T041 [US4] Codex independently inspect the T001–T040 commit range, handoff claims, governed file set, negative controls, and built artifact inventories; record findings in `.handoff/009-public-distribution-v0.6.0-release-review.md`
- [ ] T042 [US4] Codex dispatch a fresh-context whole-branch review against `spec.md`, `plan.md`, `tasks.md`, and the Engineering diff; resolve Critical/Important findings through one RED→GREEN fix pass and record deferred minors in `.handoff/009-public-distribution-v0.6.0-release-review.md`
- [ ] T043 [US4] Codex rerun the complete release-candidate gate on the reviewed HEAD, push `codex/009-public-distribution-v0.6.0`, create a PR against `main`, and attach the PR URL to the current Codex task
- [ ] T044 [US4] Codex wait for CI, Compose Init, Performance, secret scan, and required review on the PR; record each owning GitHub check URL and conclusion in `.handoff/009-public-distribution-v0.6.0-release-evidence.md`
- [ ] T045 [US4] Codex merge only the green reviewed PR to `main`, check out the exact merge commit, rerun the release gate, wait for and read back CI/Compose Init/Performance/secret checks on that main commit, and record the full mainline SHA plus check URLs in `.handoff/009-public-distribution-v0.6.0-release-evidence.md`
- [ ] T046 [US4] Codex resolve the exact `fioenix/fn-ignis` GHCR package and repository linkage without changing visibility, create and push annotated tag `v0.6.0` on the verified `main` commit, and record the tag SHA in `.handoff/009-public-distribution-v0.6.0-release-evidence.md`
- [ ] T047 [US4] Codex wait for the tag-driven Docker Publish workflow while the package remains private, then use authenticated `gh attestation verify` against the immutable digest constrained to `fioenix/fn-ignis`, the release commit/ref, and expected signer workflow; record workflow URL, digest, and verification in `.handoff/009-public-distribution-v0.6.0-release-evidence.md`
- [ ] T048 [US4] Codex re-resolve the exact `fioenix/fn-ignis` package, accept the platform's one-way warning, change it to public without deleting or retagging historical versions, and record the target/readback without credentials in `.handoff/009-public-distribution-v0.6.0-release-evidence.md`
- [ ] T049 [US4] Codex run tagged-source and isolated anonymous-container acceptance from public bytes, verify `0.6.0`/`0.6`/`latest` digest parity and both 47-tool MCP sessions, record the reviewed `mcp-publisher` version/source and run public `mcp-publisher validate`, then save the redacted JSON bundle to `.handoff/009-public-distribution-v0.6.0-evidence.json`
- [ ] T050 [US4] Codex publish the approved GitHub Release, run both release-state checkers, require every mandatory surface `VERIFIED` with PyPI `DEFERRED`, update the post-release `BACKLOG.md` status through a reviewed follow-up commit/PR if needed, and report `RELEASED` only from the final live readback in `.handoff/009-public-distribution-v0.6.0-release-evidence.md`

**Checkpoint**: `v0.6.0` is either demonstrably released across both public paths or explicitly left
open with the exact missing, failed, or unreadable surface.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1**: Starts from `origin/main` at the recorded base commit.
- **Phase 2**: Depends on all Phase 1 RED contracts.
- **US1 / Phase 3**: Depends on Phase 2; can be implemented without US2.
- **US2 / Phase 4**: Depends on Phase 2; can proceed in parallel with US1 after the shared MCP smoke
  contract is green.
- **US3 / Phase 5**: Depends on the US1/US2 contract decisions so docs name real surfaces.
- **US4 candidate / Phase 6**: Depends on US1–US3 completion and green targeted suites.
- **Release-owner Phase 7**: Depends on a clean T040 handoff and never runs inside Claude Code's
  Engineering pass.

### User Story Dependencies

- **US1**: Independently proves source distribution.
- **US2**: Independently proves the OCI role and local anonymous-pull machinery; live public proof
  waits for release.
- **US3**: Consumes the chosen source/OCI contracts and makes them one public truth.
- **US4**: Requires US1–US3 because a version can be cut only after both paths and their documentation
  agree.

### Parallel Opportunities

- T002, T003, and T004 touch separate initial test concerns and may be prepared in parallel before
  the combined RED run T005.
- T014, T017, and T018 touch different source-test/document files after T013 defines the source
  observer contract.
- T030 and T031 touch different governed surfaces after the negative controls exist.
- US1 and US2 can progress independently after T012, but T028–T033 wait for both contracts.
- Release-owner tasks are deliberately serial because each changes or verifies the authority for
  the next irreversible step.

## Parallel Examples

### User Story 1

```text
Task: "Extend clean-user schema/module readback in tests/integration/test_clean_user_journey.py"
Task: "Update English source/migration guidance in README.md and docs/USER_GUIDE.md"
Task: "Update Vietnamese source/migration guidance in README.vi.md and docs/USER_GUIDE.vi.md"
```

### User Story 3

```text
Task: "Update AGENTS.md and .github/workflows/ci.yml current tool counts"
Task: "Update docs/PROJECT_REVIEW_CONTEXT.md and BACKLOG.md current tool counts"
```

## Implementation Strategy

### Engineering MVP

1. Complete Phase 1 and Phase 2.
2. Complete US1 and prove source bootstrap from an isolated tracked tree.
3. Stop and inspect the source evidence before adding container behavior.

This is an independently useful source-distribution increment, but it is not a `v0.6.0` release
because public GHCR and live release surfaces remain required.

### Full Candidate

1. Add US2 OCI behavior and local container acceptance.
2. Converge current public truth under US3.
3. Run Phase 6, bump atomically, verify final bytes, and hand off a clean branch.

### Ship

Codex performs T041–T050 serially. The first missing, failed, unreadable, or owner-blocked release
surface stops the release claim but does not erase already completed evidence.

## Notes

- Tests are written and observed RED before production/configuration changes.
- A workflow/config setting is not evidence of public behavior.
- Historical `39`, `45`, and `022` references are reviewed by context, not globally replaced.
- Version bump and `uv lock` regeneration are one atomic release-preparation commit.
- No Engineering task authorizes push, merge, tag, visibility change, Release publication, PyPI
  publication, credential rotation, or persistent database migration.
