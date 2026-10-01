# Decision: Mission-Bound Evidence-Grounded Ignis

**Status:** Accepted
**Date:** 2026-09-29
**Scope:** Product category, autonomy boundary, research method, and breaking runtime direction

## Context

Ignis was designed around two runtime tracks: an optional always-on trend radar and on-demand
research missions. The background track spends connector quota, compute, storage, and maintenance
before a user has named a decision it should serve. Its shared baseline also makes it easy for a
later analysis to inherit observations whose query, audience, timeframe, and evidence role were not
chosen for that decision.

The competitive review found that connector breadth, generic deep research, citation generation,
and polished dashboards are already available from commercial suites, general research agents, and
composable open-source stacks. Ignis does not gain a durable position by becoming a smaller
Brandwatch or “Perplexity for social.”

The product opportunity is a research instrument for people who want to collect social evidence
themselves and need the system to expose missingness, preserve counterevidence, and refuse a market
verdict when the evidence frame cannot support it.

## Decision

Ignis becomes an **evidence-grounded social market research agent** that starts only from an
explicit user or host-agent task.

- There is no always-on radar, scheduled discovery, daily auto-collection, or idle-state autonomous
  work.
- After task assignment, Ignis may act autonomously inside the confirmed mission boundary and must
  stop at a terminal task state or at a new authority, cost, or scope boundary.
- The product exposes two independent capability families: `ignis-collect` for bounded social
  evidence collection and `ignis-analyze` for Senior Market Analytics over an eligible evidence
  frame.
- Both capabilities share one evidence control plane covering mission scope, provenance, channel
  state, evidence qualification, counterevidence, sufficiency, claim traceability, and corpus
  identity.
- Market research must test a core hypothesis against alternative and null hypotheses. It must
  preserve evidence that weakens the preferred explanation.
- Strategic inference fails closed. Missing, unauthenticated, rate-limited, failed, or unrequested
  surfaces are not zero. An insufficient frame produces an actionable gap report, not a market
  verdict.
- `ATTENTION` remains exploratory and cannot emit commercial demand or Opportunity Index verdicts.
  `MARKET` remains hypothesis-driven and requires a confirmed immutable Brief.

The public category uses **evidence-grounded**. **Evidence-gated** names the internal mechanism that
permits or withholds a conclusion.

## Product reasoning constraints

- **Outcome thinking:** the task starts from the decision and the finished state, not from a
  connector or report template.
- **Design thinking:** the system listens to actual social evidence, shows collection friction and
  missingness, and returns the next useful action for the person making the decision.
- **Critical thinking:** the system makes assumptions explicit, searches for disconfirming evidence,
  keeps competing explanations, and separates observation from inference.

## Breaking cutover

The worker, scheduler, daily-discovery reports, unattended alerts, and public operations dedicated
to the old background model are removed in one breaking release without a deprecation period.
Public operations that depend on an unscoped shared trend corpus must either be removed or replaced
by a mission-bound contract; the implementation plan records the exact inventory and the owner must
approve any MCP signature removal before code changes begin.

Existing scheduled baseline data does not become mission evidence automatically. It is inventoried
and either retained as a read-only historical archive for a stated reason or proposed for
target-specific, recoverable deletion. This decision does not itself authorize deleting data.

## Beachhead

The first validation audience is founders, operators, independent analysts, consultants, and small
teams researching consumer markets in Vietnam. This choice defines the pilot corpus and language
experience; it does not prove product-market fit or universal coverage.

## Consequences

### Benefits

- Resource use traces to an explicit user outcome.
- Every strategic conclusion is tied to the exact collection and qualification frame that permits
  it.
- Confirmation-bias resistance becomes product behavior rather than a report-writing suggestion.
- General host agents can become distribution channels without becoming the authority that decides
  whether evidence is sufficient.

### Costs

- Ignis deliberately gives up continuous monitoring, crisis alerts, and baseline trend accumulation.
- Users sometimes receive a refusal and must authorize or run another probe before a verdict.
- The breaking release removes familiar tools and deployment surfaces.
- Hypothesis, claim, and evidence contracts add method and storage complexity that Ignis must carry
  instead of outsourcing to a generic narrative model.

## Superseded direction

This decision supersedes the 2026-09-01 Dual-Track Market Intelligence Architecture and every active
statement that presents the optional background radar, worker sweep, or daily discovery as current
product behavior. It does not supersede the accepted Dual-Surface Research Workspace decision from
2026-09-21; the `ATTENTION` and `MARKET` distinction remains part of the new product.

## Implementation authority

This decision authorizes specification and planning. It does not by itself authorize writing or
applying a database migration, removing an MCP signature, deleting baseline data, bumping a version,
tagging, or releasing. Those actions retain their repository-specific owner gates.
