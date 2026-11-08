# Release Gates

Read this before a version bump, tag, or release, and when checking a change against the checklists. Enforcer: agent judgment (advisory), except where a named test or CI job is given.

## Release Versioning Principles & SemVer Guardrails

All agents use the **`MAJOR.MINOR.PATCH`** release format. During the current `0.x` beta,
the owner-approved criterion is user-visible product impact, not implementation size:

```
v MAJOR . MINOR . PATCH
    ↑       ↑       ↑
Major   User-visible   Internal / Fix
```

### Version Bump Criteria

| Increment Level | When to Bump | Example Transition | Reset Rule |
|---|---|---|---|
| **`PATCH`** (`+0.0.1`, tier 3) | Fixes, optimization, refactoring, tests, documentation, and other changes without a material user-visible product change. | `0.7.0` $\rightarrow$ `0.7.1` | None |
| **`MINOR`** (`+0.1.0`, tier 2) | A clear change to user-facing capabilities or how users operate Ignis. A new migration, dependency, or large refactor alone is not sufficient. | `0.7.0` $\rightarrow$ `0.8.0` | `PATCH` resets to `0` |
| **`MAJOR`** (`+1.0.0`) | An explicitly owner-approved major/stable product boundary; incompatible public-contract changes after `1.0.0` retain the MAJOR rule. | `0.x.y` $\rightarrow$ `1.0.0` | `MINOR` & `PATCH` reset to `0` |

Owner approved this beta criterion on 2026-10-02. It supersedes the former automatic
MAJOR-for-breaking rule during `0.x`, not the obligation to disclose removed tools, incompatible
contracts, or required migration steps.

### ⛔ Strict Agent Guardrails

1. **NO Speculative or Arbitrary Bumps**: Do NOT bump version numbers for routine single-file bug fixes or daily development tasks. Versions are bumped **ONLY during formal release preparation** on `release/*` or `main`.
2. **NO Number Skipping**: Never jump versions arbitrarily (e.g. from `0.1.0` directly to `0.5.0` or `1.0.0`). Always increment by strictly `+1` at the appropriate level.
3. **Atomic Version Synchronization**: Six files carry the version string, not three. When a version bump is performed, the Agent **MUST update every one of them in a single atomic commit**, then tag:
   - [`pyproject.toml`](pyproject.toml) $\rightarrow$ `version = "X.Y.Z"`
   - [`openclaw.json`](openclaw.json) $\rightarrow$ `"version": "X.Y.Z"`
   - [`server.json`](server.json) $\rightarrow$ twice: the manifest version and the package version
   - [`CITATION.cff`](CITATION.cff) $\rightarrow$ `version: X.Y.Z` and `date-released`
   - [`.openclaw/config.yaml`](.openclaw/config.yaml) $\rightarrow$ `version: X.Y.Z`
   - [`BACKLOG.md`](BACKLOG.md) $\rightarrow$ the version banner
   - Git Tag on `main` $\rightarrow$ `vX.Y.Z`

   The identical list is enforced in Checklist C below. Do not reintroduce the obsolete three-file wording.
4. **Beta Phase Principle (`0.X.Y`)**: While in initial beta stages (`0.X.Y`), prioritize `PATCH` and `MINOR` increments. Do NOT rush to `1.0.0` until enterprise multi-tenancy and production stability milestones are reached.

## Checklist A: Open-Source Codebase & Documentation Standards
- [ ] **Global Codebase Convention**: All source code (`src/`), test suites (`tests/`), variable/function names, docstrings, inline comments, assert messages, log lines, and strings emitted by the code follow standard English (see the Language Boundary Protocol table in Section 3).
- [ ] **No Hardcoded Vocabulary**: No new domain terms, synonyms, intent keywords, noise phrases, or category keywords added as Python constants in `src/` (see the Data-Driven Vocabulary Protocol in Section 3).
- [ ] **Convention Gate**: `.venv/bin/pytest tests/unit/test_repo_conventions.py` passes.
- [ ] **Developer Meta-Guidance**: Core developer instructions (`AGENTS.md`, `CLAUDE.md`, skills) are maintained in English.
- [ ] **Git Commits & Branching**: 100% English imperative commit messages (e.g., `Add`, `Fix`, `Refactor`, `Update`).
- [ ] **Regional Documentation**: Dedicated localized documentation (such as `README.vi.md`) and market dossiers in `reports/` are accurately maintained for regional audiences.

## Checklist B: Harness Autonomy & Non-Prescriptive Decoupling
- [ ] **Non-Prescriptive Instructions**: Verify FastMCP server instructions and tool docstrings do NOT coerce agents into forced pipelines (no "MUST STRICTLY FOLLOW").
- [ ] **Atomic Independence**: See `AGENTS.md` section 6.
- [ ] **Framework Separation**: The strategic research recipe is a reference, never a forced pipeline for tactical collection.
- [ ] **Contextual Deliverables**: Deliverables match user intent (concise text, cards, tables, or full HTML dashboards) without forcing boilerplate templates for trivial queries.

## Checklist C: Formal Release & Version Bump Gate
- [ ] **Automated Test Gate**: Run `uv run pytest tests/`, as CI does, with a 100% pass rate before committing release changes. `tests/unit/` alone misses the integration tests.
- [ ] **Docs & Specs Sync**: Verify `docs/` (e.g., `USER_GUIDE.md`, architecture specs) and tool catalogs (`README.md`, `README.vi.md`) are fully updated with newly introduced tools, parameters, or schemas.
- [ ] **Clean Working Tree**: Verify no uncommitted scratchpads, no leaked credentials/`.env`, and no temporary audit notes placed in `docs/` (strictly `.handoff/`).
- [ ] **Branch Merge to Main**: Ensure the feature or maintenance branch is fully merged into `main` before tagging.
- [ ] **Packaging Verification**: Run distribution build check (`python -m build` or `uv build`) to verify clean package artifacts without missing assets.
- [ ] **Atomic Version Synchronization**: Six files carry the version string, not three. Update every one of them in a single atomic commit, then tag:
  - `pyproject.toml` (`version = "X.Y.Z"`)
  - `openclaw.json` (`"version": "X.Y.Z"`)
  - `server.json` (twice: the manifest version and the package version)
  - `CITATION.cff` (`version: X.Y.Z` and `date-released`)
  - `.openclaw/config.yaml` (`version: X.Y.Z`)
  - `BACKLOG.md` (the version banner)
  - Git Tag (`vX.Y.Z`) on `main`
  - Verify with `grep -rn "<previous version>" --include="*.toml" --include="*.json" --include="*.yaml" --include="*.cff" --include="*.md" .` returning nothing
- [ ] **Regenerate `uv.lock` in that same commit.** The lock records the project's own version,
  so bumping `pyproject.toml` without running `uv lock` makes `uv sync --locked` fail on a clean
  checkout and takes CI down with it. Run `uv lock`; never hand-edit the file. Confirm with
  `uv lock --check`.
- [ ] **GitHub Release Tagging**: Tag and push release commit (`git tag -a vX.Y.Z -m "Release vX.Y.Z" && git push origin vX.Y.Z`) and publish the GitHub Release note.
- [ ] **SemVer Guardrail**: Increment strictly by `+1` (`PATCH`, `MINOR`, `MAJOR`) according to the bump criteria above. Never jump versions arbitrarily.




---
