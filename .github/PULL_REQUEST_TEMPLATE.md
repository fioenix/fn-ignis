## Description
Provide a concise explanation of what changes this PR introduces.

## Related Issue
Fixes #(issue)

## Type of Change
- [ ] Bug fix (non-breaking change which fixes an issue)
- [ ] New feature / Connector (non-breaking change which adds functionality)
- [ ] Breaking change (fix or feature that would cause existing functionality to not work as expected)
- [ ] Documentation / Community Health update

## Quality & Verification Checklist
- [ ] `uv run ruff check src/ tests/` passes with 0 errors.
- [ ] `uv run pytest -v` passes 100% (all unit and integration tests).
- [ ] Added regression tests covering the change.
- [ ] Verified Zero-Docker SQLite fallback still functions out of the box.
- [ ] Verified no PII leaks in generated artifacts.
