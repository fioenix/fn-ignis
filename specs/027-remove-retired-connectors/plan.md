# Implementation Plan: Remove Retired Connector Code

**Branch**: `027-remove-retired-connectors` | **Date**: 2026-11-13 | **Spec**: `spec.md` | **Research**: `research.md`

## Summary

Delete the retired Reels, Google Trends RSS and Creative Center connectors, cut `TikTokPlugin` down to the comment
path, remove what that orphans, and narrow the SC-004 coverage gate. No tool, schema, migration or stored-row read
changes.

## Path

`tasks.md` (Spec Kit depth gate, agent decided 2026-11-13): the change spans many modules, tests and CI config, and
the order matters (code before its tests, coverage config with its gate test). Implementation is delegated to
Antigravity; the coordinator accepts with fresh targeted tests and two posted reviews.

## Constitution check

- VI (persisted evidence): no migration and no edit to `sql/`; old rows keep their readers.
- Section 6 of AGENTS.md: 41 tools stay independently callable with unchanged signatures.
- Section 8: the connector-tier decision (Reels OAuth, Instagram settings) is the owner's, recorded in `spec.md`.

## Verification

Per touched module, at most two modules per command, with the one-minute load below 15:
`PYTHONPATH=src .venv/bin/pytest <module(s)>`. Always include `tests/unit/test_repo_conventions.py`,
`tests/unit/test_public_mcp_contract.py`, `tests/unit/test_tiktok_comments.py`,
`tests/unit/test_t022_coverage_gate.py`, `tests/unit/test_source_retirement.py` and
`tests/unit/test_identity_free_mcp_responses.py`. `ruff check src/ tests/`.
