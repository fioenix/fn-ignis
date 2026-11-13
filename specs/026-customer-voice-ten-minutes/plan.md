# Implementation Plan: Customer Voice in Ten Minutes

**Branch**: `026-customer-voice-ten-minutes` | **Date**: 2026-11-13 | **Spec**: `spec.md`

## Summary

Ship one packaged guide that chains the existing host-browser search (TikTok, Threads) and
`get_tiktok_video_comments` into a bounded ten-minute run ending in a local Markdown synthesis with quotations.
No tool, schema, migration or connector changes.

## Path

Direct implementation, no `speckit-tasks` (Spec Kit depth gate, agent decided 2026-11-13). Basis:
- one seam: a guide file, its prompt and resource in `server.py`, a repository skill pointer, the OpenClaw
  manifest's prompt and resource lists, the user guides and tests;
- known consumers: `voice_of_customer_audit` is called by `tests/unit/test_public_mcp_contract.py` and listed in
  `openclaw.json`; the new resource joins the guide lists in `tests/unit/test_host_browser_guides.py`;
- no migration, dependency or irreversible boundary. The prompt's text changes (a small contained contract
  change, all consumers updated here) and it guides an agent over untrusted collected text, so the security
  review covers it before merge.

## Changes

| File | Change |
|---|---|
| `src/ignis/interfaces/mcp/guides/ignis_customer_voice.md` | New guide: FR-001–FR-010 |
| `src/ignis/interfaces/mcp/server.py` | Resource `fn-ignis://guide/ignis-customer-voice`; `voice_of_customer_audit(keywords=None)` returns the guide, keyword first when given (FR-011) |
| `.agents/skills/ignis-customer-voice/SKILL.md` | Pointer skill, as for the source skills |
| `openclaw.json` | Add the resource |
| `tests/unit/test_customer_voice_guide.py` | Packaged, served, prompt with and without keyword, rules present |
| `docs/USER_GUIDE.md`, `docs/USER_GUIDE.vi.md` | Short section; README unchanged unless it lists guides |
| `BACKLOG.md` | PRD-1 status; the two LOW wording fixes from PR 163 review |

## Performance budget

From Spec 025 medians: TikTok 58 s, Threads 79 s prepare to accepted. Five comment calls of 20 comments each are
the unknown; SC-001 measures them. Writing the file is the remainder of the ten minutes.

## Constitution check

- I (explicit bounded work): the run starts only on the person's keyword and request; no schedule.
- VII (no author identity at rest): comments are not stored; the synthesis adds no author; `@mentions` arrive
  masked.
- Attention context stays context: no verdict, index or labels (FR-007, FR-008).
