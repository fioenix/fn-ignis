# Decision Proposal: Decision-Grade Evidence Qualification

**Status:** Recommended; pending product-owner approval  
**Date:** 2026-09-25  
**Scope:** Post-v0.5 product validation and the next product priority

## Outcome

fn-ignis should not issue an Opportunity Index or a market verdict unless the supporting
observations are relevant to the confirmed Market Brief. A valid observation identifier proves
traceability, but it does not prove that the cited observation supports the conclusion.

The next plan should therefore make evidence qualification a first-class contract before adding
Live Alerts, more connector surfaces, or broader taxonomy coverage.

## Validation question

The validation tested whether v0.5 can help a requester decide if a lightweight AI operations
copilot for small Vietnamese retailers is worth pursuing. It exercised three supported journeys:

1. Attention-only discovery;
2. a direct Market mission with a confirmed Brief; and
3. an Attention-to-Market handoff.

The research used a seven-day Vietnam window and the configured development PostgreSQL database.
Before the product journeys, migrations `017` through `022` were applied to that development
database in one controlled operation. Counts and ordered identifier digests for `sources`,
`observations`, `mission_evidence`, `research_missions`, and `topic_clusters` were unchanged.
The migrated database had 17 of 17 public tables with RLS enabled and the nine targeted UUID
defaults set to `gen_random_uuid()`.

This was not a production migration. No production database was accessed.

## Observed results

### Existing baseline

The current seven-day Vietnam baseline returned 50 top clusters. None was `BREAKOUT` or
`SURGING`. A model-assisted review of the first 20 classified all 20 as news or entertainment
noise for the validation question. This result is time-sensitive and describes only the corpus
read on 2026-09-25.

### Attention-only

The Attention mission completed with 33 signals and three clusters:

- 30 YouTube signals and three Google signals;
- overall confidence `73.7` (`MEDIUM`), including coverage `40.0` and language precision `57.6`;
- `opportunity_index_applies: false`, as required;
- 14 conclusion citations, all carrying canonical observation identifiers; and
- no qualified Market handoff candidate at the validation threshold.

Two clusters were clear news or entertainment noise. The only plausible candidate, `ai xay
website`, was classified as adjacent with confidence `0.73` and received a handoff score of
`2.64/4`. Across all 33 Attention signals, three were initially labelled market-relevant, but none
met the validation confidence threshold of `0.60`.

### Direct Market

The direct Market mission completed with 51 signals across Google, YouTube, and Threads. The
scorecard reported `71.5` (`MEDIUM`), while also reporting that 49 percent of signals were
non-localized or entertainment outliers.

The analysis emitted four opportunities: one `UNVERIFIED_DEMAND_GAP` at `+3.8` and three
`SATURATED_SEGMENT` verdicts at `-35.5`, `-49.8`, and `-62.5`. Several cited supply signals were
unrelated films, drama, or motivational videos that happened to be returned for the probe query.
Of the first 50 signals reviewed, only two were market-relevant with confidence at or above
`0.60`.

### Attention-to-Market handoff

The handoff persisted the Attention mission and cluster lineage correctly. It completed with 60
new Market signals across Google, YouTube, TikTok Video Grid, and Reels. The scorecard reported
`79.9` (`MEDIUM`) while also reporting 58.3 percent non-localized or entertainment outliers.

The analysis emitted three `SATURATED_SEGMENT` verdicts, all at `-8.1`. Of the first 50 signals
reviewed, none was market-relevant with confidence at or above `0.60`.

The handoff preserved evidence roles correctly:

- all 33 inherited observations remained `ATTENTION_CONTEXT`;
- all citations used for Market conclusions were `MARKET_EVIDENCE`; and
- no inherited Attention observation was counted as Market evidence.

### Conclusion support

The two Market analyses contained 21 conclusion units across opportunities, strategic insights,
and actionable takeaways. A model-assisted review compared each conclusion with the citations
provided by the product:

- `0/21` reached support probability `>= 0.70`; and
- `0/21` reached probability `>= 0.70` for direct evidence of the target user's problem, buying
  behaviour, or adoption intent.

The highest support probability was `0.58`. These probabilities are review aids, not objective
ground truth. Manual inspection of the cited titles confirmed the central failure mode: the
product often treated query-matched but semantically unrelated content as market supply.

## What worked

The v0.5 operational and provenance contracts held across all three journeys:

- one confirmed workspace backed by the shared database;
- immutable Market Brief revisions;
- durable Attention-to-Market lineage;
- one completed, collision-safe journal for each run;
- no active writer claim after completion;
- Attention correctly withheld the Opportunity Index; and
- canonical observation identifiers and evidence roles were present on conclusion citations.

These are necessary foundations. They are not sufficient for decision quality.

## Defect found during validation

A cold server process can execute mission ingress before synchronizing database-backed probe
templates and TikTok UI-noise vocabulary. The first Attention and direct Market runs therefore
reported no TikTok signals even though the database contained the required vocabulary. Reading a
mission analysis first warmed the process, after which the handoff run collected 27 TikTok Video
Grid signals.

The ingress boundary must synchronize the vocabulary it depends on. The result of a mission must
not depend on whether an unrelated analysis tool was called earlier in the process lifetime.

## Recommended decision

Prioritize a **Decision-Grade Evidence Qualification** plan with these boundaries:

1. Synchronize database-backed vocabulary before every mission ingress path that depends on it,
   including the first mission after process startup.
2. Preserve raw observations at ingress. Relevance remains a downstream analytical decision in
   `QualityEvaluator`, not a destructive ingestion filter.
3. Add an explicit question-relevance dimension to the quality scorecard and cap confidence when
   qualified evidence is insufficient.
4. Make the Market surface fail closed: no Opportunity Index or market verdict when there is not
   enough relevant demand and supply evidence for the confirmed Brief.
5. Make Attention return no qualified handoff candidate when every cluster is noise, merely
   adjacent, or insufficiently supported.
6. Separate macro/news context from evidence used to estimate market demand and supply.
7. Add semantic negative controls: content that repeats a probe keyword but is unrelated to the
   research question must not support a conclusion.

Thresholds, minimum evidence counts, and the exact qualification model belong in the feature
specification. They should not be inferred from the temporary review thresholds used in this
validation.

## Alternatives not recommended

### Ship Live Alerts next

Rejected for now. Alerts would amplify verdicts that the validation found poorly supported.

### Expand taxonomies first

Rejected as the primary fix. Better category labels do not make an unrelated observation relevant
to a research question.

### Add more connectors first

Rejected as the primary fix. More input increases volume but does not repair the qualification
boundary. Connector coverage may be revisited after the system can distinguish relevant evidence
from query-matched noise.

### Delete low-relevance observations at ingress

Rejected. Raw observations are useful for audit and future analyses. Destructive ingress filtering
would also conflict with the existing rule that relevance depends on who is asking and what they
are trying to decide.

## Non-goals for the next plan

- adding a new connector;
- implementing Live Alerts or webhooks;
- expanding regional coverage;
- deleting raw observations;
- changing authentication or credential storage; and
- treating model-assisted review scores from this spike as production thresholds.

## Approval gate

This document records the validation and the recommended direction. It does not authorize an
implementation. After product-owner approval, Spec Kit should turn the recommendation into a
feature specification, plan, and dependency-ordered tasks with explicit acceptance thresholds.
