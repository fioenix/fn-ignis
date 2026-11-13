# Implementation Plan: Tool-Selection Eval

**Branch**: `028-tool-selection-eval` | **Date**: 2026-11-13 | **Spec**: [spec.md](spec.md)

## Summary

A maintainer-run eval that puts a real host agent (Claude Code headless) in front of the live Ignis
tool catalog with simulated handlers, feeds it 46 user intents over three journeys, and scores the
tool calls it makes. It adds no MCP tool, no product behaviour and no dependency. The deliverable is
the eval, its model-free unit tests, and a recorded baseline for AGX-2, AGX-3 and AGX-7.

## Technical Context

**Language/Version**: Python 3.12 (repository standard).

**Primary Dependencies**: the existing `mcp` package (low-level `Server` over stdio) and the
installed `claude` CLI. No new package.

**Storage**: none. Intents are a JSON fixture; transcripts and reports are local files under
`reports/` (gitignored); the baseline summary is committed under this spec folder.

**Testing**: pytest unit tests for intent validation, catalog fidelity and scoring. No test calls a
model.

**Project Type**: maintainer script under `scripts/`, the pattern of `t021_read_path_benchmark.py`.

**Constraints**: no real source, store, browser, session, token or network endpoint from the
simulated server (FR-005); the host agent runs isolated from the maintainer's own configuration
(FR-006); not in CI (FR-011).

**Scale/Scope**: 46 intents × 3 on two models repeats, at most 8 tool calls per intent.

## Design

### Files

| Path | Role |
| --- | --- |
| `tests/fixtures/tool_selection_intents.json` | The versioned intent set (FR-001–FR-003). |
| `scripts/tool_selection_eval/catalog.py` | Reads tools, prompts and server instructions from the live `ignis.interfaces.mcp.server.mcp` registration without running its lifespan; computes the catalog fingerprint. |
| `scripts/tool_selection_eval/sim_server.py` | Low-level MCP stdio server that republishes that catalog unchanged and answers every call from the intent's scripted responses; appends each call to a JSONL log; enforces the call cap. |
| `scripts/tool_selection_eval/scoring.py` | Pure functions: score one transcript against its intent, aggregate a run, compute the spread over repeats. |
| `scripts/tool_selection_eval/run.py` | CLI: validates intents against the live catalog, runs the host agent per intent, scores, writes the report. |
| `tests/unit/test_tool_selection_eval.py` | Model-free tests for the three modules above. |

### Catalog fidelity (FR-004)

`catalog.py` calls the real server object's `list_tools()`, `list_prompts()` and reads its
`instructions`; the simulated server returns those `Tool` and `Prompt` objects as they are. A unit
test asserts the simulated server's published tool list equals the real one field for field. The
fingerprint is the SHA-256 of the canonical JSON of names, descriptions and input schemas.

### Simulated handlers (FR-005, edge cases)

- Each intent scripts responses by tool name; a tool may have a list of responses consumed in
  order. An unscripted call returns a neutral empty success (`{"status": "SUCCESS", "items": []}`)
  and is scored wrong. No response names the eval, so the agent cannot tell it is being scored.
- Arguments are validated against the tool's input schema with the validation the real server
  publishes; a rejected call is logged as made and returns the error.
- From call 9 on, every call returns a rate-limit error; the scorer reports the cap.
- The simulated server imports the product module only to read registrations; it opens no store
  and runs no lifespan. A unit test runs it with networking and the store factory patched to
  raise, to prove no handler path reaches them.

### Host agent isolation (FR-006)

Each intent runs in a fresh temporary directory:

```
claude -p <intent text> --model <model> --tools "" --strict-mcp-config --mcp-config <sim.json>
  --disable-slash-commands --setting-sources project --no-session-persistence
  --system-prompt <neutral host prompt> --output-format json
```

A probe on 13/11/2026 with these flags (empty MCP config) showed no built-in tools and no
CLAUDE.md content in the agent's context. `--system-prompt` replaces the Claude Code coding
prompt with a short, neutral assistant prompt, closer to a general host such as Claude Desktop;
Ignis's own server instructions still arrive through MCP. The default model is `sonnet`; `--model`
overrides it and the report records it.

### Scoring (FR-007, FR-008)

Per intent: the decisive first call is the first call that is not a neutral read, unless the
intent lists that read as acceptable first. `first_call_ok` (decisive first call in the acceptable
set, or none when "no tool" is acceptable), `first_call_trap`, `any_trap_call` (a trap tool
anywhere in the run), `neutral_calls`, `wrong_calls` (calls outside the acceptable path and the
neutral set), `reached_terminal` and `calls_to_terminal`. Per run: first-call accuracy overall,
per journey and on traps; trap-call rate; mean wrong and neutral calls; terminal-reach rate; median
calls to terminal. Over repeats: min, max and spread in percentage points for the four rate
metrics (first call, trap first call, trap-call rate, terminal reach); unstable when any spread
exceeds 10.

### Intent set (FR-001–FR-003)

46 intents: 17 tactical, 13 watchlist and 16 mission, 16 of them traps (among them "find market
opportunities" and "show my Threads"). Mostly Vietnamese with diacritics, five in English and three
untoned Vietnamese. The set also declares nine neutral orientation tools with shared default
responses; an intent's own response for a tool overrides the default. Each intent names `acceptable_first`, `acceptable_path`,
`trap_tools`, `terminal` (a tool call or `reply`) and `responses`. A unit test refuses an intent
that names a tool missing from the live catalog.

## Constitution Check

- **I. Mission-bound autonomy**: the eval collects nothing and starts only when the maintainer runs
  it. Pass.
- **II. Connectors**: untouched. Pass.
- **III. Evidence-first**: no Market claim; the baseline is a measurement with its limits stated.
  Pass.
- **IV. Deterministic report builders**: untouched. Pass.
- **V. Simplicity**: three small modules, no new dependency, no abstraction beyond one use. Pass.
- **VI. Migration and release**: no migration, no version change. Pass.
- **VII. No author identity at rest**: intents are synthetic; transcripts hold no author identity.
  Pass.
- **Data-driven vocabulary**: the intent fixture is test data, not engine vocabulary in `src/`.
  Pass.
- **41 tools independently callable**: unchanged; the eval only reads the catalog. Pass.

## Depth gate (Spec Kit)

Direct path, no `tasks.md`: one coherent seam (a maintainer script, its fixture and its tests),
known consumers (none in `src/`), no task ordering or parallel split, no migration, dependency or
irreversible boundary, no public contract change. Security trigger: it starts a subprocess that
uses the maintainer's Claude subscription and imports the product module; the security review
covers that path before merge.

## Delivery

1. Intent fixture, catalog reader, scoring and unit tests (model-free; red first).
2. Simulated server and runner; one smoke intent through the real host agent.
3. Full baseline: three repeats, report, baseline summary in `baseline.md`, BACKLOG AGX-1 updated.
4. Pull request with code and security reviews.
