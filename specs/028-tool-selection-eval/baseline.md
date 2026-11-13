# Tool-Selection Eval Baseline

**Date**: 2026-11-13 | **Intent set**: `2026-11-13.3` (46 intents, 16 traps) | **Catalog
fingerprint**: `8cd56e0987deb11aba5dec944af0589b7a1cc7ab50da2434eac26f0a8298ec5a` (41 tools, main
`8229e4b`) | **Repeats**: 3 per model | **Cost**: $2.20 Sonnet, $0.15 Haiku (list price, on the
owner's subscription)

The run below was made by `python -m scripts.tool_selection_eval.run --repeats 3 --model <m>`. Raw
transcripts stay in gitignored `reports/`.

## Headline metrics

| Model | Run | First call % | Trap first call % | Trap wrong first | Trap call % | Terminal reach % |
| --- | --- | --- | --- | --- | --- | --- |
| Sonnet | 1 | 93.5 | 87.5 | 2 | 8.7 | 89.1 |
| Sonnet | 2 | 87.0 | 75.0 | 4 | 13.0 | 87.0 |
| Sonnet | 3 | 82.6 | 62.5 | 6 | 10.9 | 82.6 |
| Haiku | 1 | 84.8 | 75.0 | 4 | 8.7 | 87.0 |
| Haiku | 2 | 89.1 | 81.2 | 3 | 8.7 | 87.0 |
| Haiku | 3 | 89.1 | 75.0 | 4 | 10.9 | 84.8 |

Pooled over three runs, both models make 121/138 acceptable first calls and 11–12/48 wrong first
calls on trap intents; 15/138 (Sonnet) and 13/138 (Haiku) intent runs call a trap tool at some point.

## Stability against the 10-point bar

| Metric | Sonnet spread | Haiku spread |
| --- | --- | --- |
| First call | 10.9 | 4.3 |
| Trap first call | **25.0** | 6.2 |
| Trap-call rate | 4.3 | 2.2 |
| Terminal reach | 6.5 | 2.2 |

Haiku passes on every metric. Sonnet fails on first call and trap first call: four trap intents
(M14, T14, W10, W13) changed outcome between runs. The trap-call rate passes on both models.

## What the agents got wrong

Consistent across both models and nearly every run:

- **Stale descriptions pull agents into retired behaviour.** Asked for an Opportunity Index, white
  spaces or a recommendation from an Attention mission (M14, M15, M16), both models called
  `get_mission_analysis` ("Scorecard, 10 White Spaces, ...") and, for white spaces,
  `discover_market_opportunities` ("Identify high-demand, low-supply market white spaces"). These are
  two of the four tools AGX-2 names.
- **`verify_connectors_health` is called when a read-only check would do** (T06 on both models in every
  run; T14, T10 and W13 on Sonnet): its description does not say that it probes live sources.
- **The customer-voice intent never starts collecting** (T08, 3/3 on both models): agents ask a
  clarifying question instead of starting a bounded TikTok search.
- **A watchlist run stops before ingress on Sonnet** (W02, 3/3): it calls `start_watchlist_run` and
  stops without `execute_mission_ingress`.

The plain "find market opportunities" traps (M01, M02) did not catch either model: both asked for
scope or proposed a workspace.

## Limits

- One catalog, two models, three repeats each; the intent set is synthetic and written by the agent
  that built the eval.
- Scripted responses stand in for the host-browser step a headless agent cannot run, and say so in
  a neutral note; they may make the host-browser path easier than it is in a real host.
- The host runs with a short neutral system prompt, not Claude Desktop's or another host's.
- The simulator republishes tools, prompts and instructions but not the server's resources, and
  validates arguments with JSON Schema rather than the server's own validation and middleware.
- First baseline (same day, 38 intents, 8 traps, no neutral reads) is superseded: one trap flip
  moved its trap metric by 12.5 points, and half its wrong calls were harmless orientation reads.
