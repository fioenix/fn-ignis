# AGX-2 Result

**Date**: 2026-11-14 | **Eval**: Spec 028, intent set `2026-11-13.3` (46 intents, 16 traps), 3 runs
per model, pooled | **Cost**: $7.46 for three rounds

| Model | Catalog | Wrong first calls on traps | Non-trap first calls OK | Runs with a trap-tool call | Reached terminal |
| --- | --- | --- | --- | --- | --- |
| Sonnet | baseline `8cd56e09` | 12/48 | 85/90 | 15/138 | 119/138 |
| Sonnet | round 1 `716daf85` | 8/48 | 85/90 | 9/138 | 121/138 |
| Sonnet | round 2 `ade51859` | 5/48 (−58%) | 87/90 | 4/138 | 128/138 |
| Sonnet | final `1dbc7b58` | **6/48** (−50%) | 86/90 | 6/138 | 125/138 |
| Haiku | baseline `8cd56e09` | 11/48 | 84/90 | 13/138 | 119/138 |
| Haiku | round 1 `716daf85` | 12/48 | 84/90 | 9/138 | 122/138 |
| Haiku | round 2 `ade51859` | 7/48 (−36%) | 85/90 | 5/138 | 125/138 |
| Haiku | final `1dbc7b58` | **7/48** (−36%) | 84/90 | 7/138 | 125/138 |

Every final-round metric stays within the 10-point stability bar on both models (largest spread
8.7, Haiku). The final catalog is round 2 plus the code-review corrections (legacy and Attention
outputs disclosed in `get_mission_analysis`, wording fixes in the other four).

## Verdict

- **SC-001** (final catalog): met on Sonnet at exactly the target (6/48, at most 6), **not met on
  Haiku** (7/48, target at most 5).
- **SC-002**: met; final non-trap first-call accuracy is 86/90 (Sonnet, +1) and 84/90 (Haiku, ±0).
- **SC-003**: met; each description was checked against its handler (see `plan.md`).

## What changed between rounds

- Round 1 made each description state what the tool does, its preconditions, refusals and the
  next tool. It removed every `verify_connectors_health` trap call (T06, T14, T10, W13), but both
  models still called `discover_market_opportunities` for an Opportunity Index or white spaces
  (M14, M15): the tool's name kept pulling them in.
- Round 2 opened the `discover_market_opportunities` and `get_mission_analysis` descriptions with
  where those outputs actually live (`get_mission_claims`). M14 and M15 dropped to one call
  between the two models. Disclosing the legacy scored topics in the final round brought M14 back on
  Sonnet (3/3).

## Still open

- **M16** ("recommend a product from Attention mission m-7"): both models call
  `get_mission_analysis` in every run of rounds 2 and final.
- **M14** on Sonnet: `discover_market_opportunities` for an Opportunity Index, 3/3 in the final round.
- **W10** (top commenters): both models call `get_mission_analysis`. That tool is not a trap there,
  but it is not an acceptable path either.
- The remaining pull looks name-driven. Renaming or hiding `discover_market_opportunities` is a
  signature change, which the owner decides (AGENTS.md section 8; OWN-4, AGX-7).

## Limits

The traps and the descriptions were both written by the agent, and round 2 was tuned after seeing
round 1, so these numbers may overstate the gain on real users' wording. All rounds are reported;
no round was dropped.
