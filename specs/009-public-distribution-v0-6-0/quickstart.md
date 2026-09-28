# Quickstart: Validate Public Distribution and v0.6.0

This guide is the release acceptance path. Commands that mutate GitHub or GHCR are marked
**release-owner only**. Engineering runs the local sections and stops before external writes.

## 1. Local Candidate Preflight

```bash
test -z "$(git status --porcelain --untracked-files=all)"
BASE_COMMIT="$(git merge-base origin/main HEAD)"
git diff --check "$BASE_COMMIT"...HEAD
git log --check "$BASE_COMMIT"..HEAD
uv lock --check
uv run ruff check src/ tests/ scripts/
uv run pytest tests/unit/ -q
```

Expected: clean candidate tree (ignored handoff evidence is not inspected), no committed-range
whitespace error, lock current, Ruff clean, unit suite zero failures.

Provision an isolated PostgreSQL container before the measured suite; an empty inherited DSN is not
an acceptable substitute:

```bash
PG_TEST_NAME="ignis-release-pg-$$"
docker run -d --rm --name "$PG_TEST_NAME" -e POSTGRES_PASSWORD=ignis_test \
  -p 127.0.0.1::5432 timescale/timescaledb-ha:pg16
until docker exec "$PG_TEST_NAME" pg_isready -U postgres >/dev/null 2>&1; do sleep 1; done
PG_TEST_PORT="$(docker port "$PG_TEST_NAME" 5432/tcp | sed 's/.*://')"
export IGNIS_TEST_POSTGRES_DSN="postgresql://postgres:ignis_test@127.0.0.1:${PG_TEST_PORT}/postgres"
uv run coverage erase
uv run pytest tests/ -q --cov=ignis --cov-report=
uv run coverage report --rcfile=.coveragerc.sc004
docker rm -f "$PG_TEST_NAME"
```

Expected: no PostgreSQL test skipped; only documented opt-in skips; schema through `023`; SC-004 at
or above 85%. Record the JUnit/pytest skip inventory rather than accepting exit zero alone.

Run fresh Compose initialization with the same non-empty/no-skip assertion as the owning workflow:

```bash
mkdir -p .handoff/compose-init-results
IGNIS_TEST_COMPOSE_INIT=1 uv run pytest tests/integration/test_compose_init.py -q -rs \
  --junitxml=.handoff/compose-init-results/junit.xml
uv run python - .handoff/compose-init-results/junit.xml <<'PY'
import sys
import xml.etree.ElementTree as ET

root = ET.parse(sys.argv[1]).getroot()
suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
totals = {
    key: sum(int(suite.get(key, 0)) for suite in suites)
    for key in ("tests", "skipped", "failures", "errors")
}
print(totals)
if totals["tests"] < 1 or totals["skipped"] or totals["failures"] or totals["errors"]:
    raise SystemExit("fresh Compose init did not execute to a pass")
PY
```

Run the same wheel smoke path as CI from a disposable environment rather than the editable source
environment:

```bash
WHEEL_TEST_ROOT="$(mktemp -d /tmp/ignis-wheel-test.XXXXXX)"
BUILD_OUT="$(mktemp -d /tmp/ignis-build.XXXXXX)"
uv build --out-dir "$BUILD_OUT"
set -- "$BUILD_OUT"/fn_ignis-0.6.0-*.whl
test "$#" -eq 1
WHEEL="$1"
uv venv "$WHEEL_TEST_ROOT/.venv"
uv pip install --python "$WHEEL_TEST_ROOT/.venv/bin/python" "$WHEEL"
printf 'DATABASE_URL=sqlite:///%s/wheel_smoke.db\nDEFAULT_GEO=VN\n' "$WHEEL_TEST_ROOT" > "$WHEEL_TEST_ROOT/wheel.env"
IGNIS_ENV_FILE="$WHEEL_TEST_ROOT/wheel.env" \
  "$WHEEL_TEST_ROOT/.venv/bin/python" scripts/wheel_mcp_smoke.py
```

Expected: exactly one newly built `0.6.0` wheel is selected; the installed wheel completes an MCP
session and discovers 47 tools. Remove only the explicit temporary roots after recording results.

## 2. Contract and Negative-Control Gates

```bash
uv run pytest tests/unit/test_public_distribution_contract.py -q
uv run pytest tests/unit/test_tool_manifests_drift.py -q
uv run pytest tests/unit/test_diagram_and_release_claims.py -q
uv run pytest tests/integration/test_clean_user_journey.py -q
```

Before accepting the branch, run every negative control listed in
[contracts/release-verdict.md](contracts/release-verdict.md) against a temporary copy. Each named
claim must turn at least one test red independently, then the unmodified candidate must return green.

## 3. Inspect Built Artifacts

```bash
WHEEL_INVENTORY="$(mktemp /tmp/ignis-wheel-inventory.XXXXXX)"
SDIST_INVENTORY="$(mktemp /tmp/ignis-sdist-inventory.XXXXXX)"
unzip -Z1 "$BUILD_OUT"/fn_ignis-0.6.0-*.whl > "$WHEEL_INVENTORY"
tar -tf "$BUILD_OUT"/fn_ignis-0.6.0.tar.gz > "$SDIST_INVENTORY"
for required in 023_evidence_qualification.sql get_evidence_qualification_batch.py \
  submit_evidence_qualifications.py mission_report.html server.py; do
  rg -q "/${required}$" "$WHEEL_INVENTORY"
  rg -q "/${required}$" "$SDIST_INVENTORY"
done
```

Expected: each required entry exists in both inventories, and the candidate evidence records hashes
of the final wheel and sdist bytes. Artifact inspection is not PyPI publication.

## 4. Integration Gate — Release Owner Only

1. Independently inspect the Engineering commit range and handoff.
2. Run the complete gates on the candidate.
3. Push the feature branch and open the PR against `main`.
4. Wait for CI, Compose Init, Performance, secret scan, and review to pass.
5. Merge and check out the exact `main` merge commit.
6. Rerun release gates on that commit, then wait for and read back CI, Compose Init, Performance,
   and secret checks belonging to that exact `main` SHA.

Do not tag a feature-branch commit.

## 5. Resolve the GHCR Package — Release Owner Only

Resolve the exact `fioenix/fn-ignis` container package in GitHub Packages. Confirm its repository
link and owner, but keep it private until the `v0.6.0` tag workflow has published the new image.

Do not infer visibility from repository visibility or a successful authenticated pull. If package
metadata cannot be read because a token lacks `read:packages`, record `UNREADABLE` and continue to
the package settings surface rather than guessing.

## 6. Tag and Build the Image — Release Owner Only

```bash
test "$(git branch --show-current)" = main
MAIN_COMMIT="$(git rev-parse HEAD)"
test "$MAIN_COMMIT" = "$VERIFIED_MAIN_COMMIT"
git merge-base --is-ancestor "$MAIN_COMMIT" origin/main
git tag -a v0.6.0 -m "Release v0.6.0"
git push origin v0.6.0
```

Wait for the Docker Publish workflow and provenance attestation while the package remains private.
Using release-owner registry authentication, verify the immutable digest with `gh attestation
verify`, constrained to `fioenix/fn-ignis`, the verified source commit/ref, and the expected signer
workflow. A pushed tag alone is not a release.

## 7. Make the Exact GHCR Package Public — Release Owner Only

Re-resolve `fioenix/fn-ignis`, confirm the newly published `0.6.0` digest, read the platform warning,
and change that exact package to **Public**. The change cannot be reversed and also exposes existing
historical versions. Do not delete or retag them; only `0.6.0`, `0.6`, and `latest` carry the new
direct-MCP default contract.

## 8. Public Tagged-Source Acceptance

Run from outside every existing checkout with no GitHub credential in the clone URL:

```bash
uv run python scripts/public_release_acceptance.py source \
  --version 0.6.0 \
  --expected-commit "$VERIFIED_MAIN_COMMIT" \
  --repository https://github.com/fioenix/fn-ignis.git
```

Expected: exact-tag clone, correct main commit, isolated bootstrap, schema through `023`, 47 tools,
and successful `get_runtime_config`.

## 9. Anonymous Container Acceptance

```bash
uv run python scripts/public_release_acceptance.py container \
  --version 0.6.0 \
  --image ghcr.io/fioenix/fn-ignis
```

Expected: empty Docker credential state, complete anonymous pull, one recorded digest, default MCP
session with 47 tools, deterministic tool call, matching `0.6.0`/`0.6`/`latest` tags, and both
required image labels. Separately start the production Compose worker and prove the scheduler
process executes. Anonymous acceptance contains no provenance credential or claim.

Validate the now-public manifest and ownership binding:

```bash
mcp-publisher --version
mcp-publisher validate
```

Expected: the evidence names the reviewed publisher version and acquisition source; `server.json`,
its OCI artifact, exact server-name label, and transport validate. Do not use an unrecorded moving
`latest` binary as release evidence.

## 10. Publish the GitHub Release and Run the Combined Verdict

After both distribution paths pass, publish the approved GitHub Release from `v0.6.0`, then run:

```bash
uv run python scripts/check_release_state.py 0.6.0
uv run python scripts/public_release_acceptance.py all \
  --version 0.6.0 \
  --expected-commit "$VERIFIED_MAIN_COMMIT" \
  --repository https://github.com/fioenix/fn-ignis.git \
  --image ghcr.io/fioenix/fn-ignis \
  --json-output .handoff/009-public-distribution-v0.6.0-evidence.json
```

Expected: every required surface `VERIFIED`, PyPI `DEFERRED`, final verdict `RELEASED`. Any missing,
failed, or unreadable required surface keeps the version open and must be reported literally.

## 11. Cleanup Readback

The acceptance tool removes only temporary directories, containers, volumes, and images it created.
Read back that no scratch database/container remains and confirm that no credential or `.env` was
written into the checkout, distribution, Git history, log, or evidence JSON.
