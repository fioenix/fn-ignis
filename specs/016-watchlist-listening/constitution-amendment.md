# Proposed Constitution Amendment: Host Routines and Listening Periods

**Status**: Proposed, 2026-10-21. Not in force. The owner ratifies or rejects it; until then
`.specify/memory/constitution.md` (2.1.0) governs, and this file changes nothing.

**Source**: the accepted decision record
[`docs/decisions/2026-10-21-listening-first-product-direction.md`](../../docs/decisions/2026-10-21-listening-first-product-direction.md),
section "Relation to earlier decisions", which names both changes and leaves them to an amendment.

**Version**: MINOR (2.1.0 → 2.2.0, or the next MINOR if Spec 015's privacy amendment is ratified
first). Both changes narrow or clarify existing guidance for a new use; no principle is removed.

## Change 1: Principle I, recurring runs belong to the host

Current text:

> - Ignis MUST start collection or analysis only after a user or host agent explicitly assigns a
>   task. It MUST NOT run an always-on radar, unattended scheduled sweep, autonomous daily discovery,
>   or background collection loop.

Proposed text:

> - Ignis MUST start collection or analysis only after a user or host agent explicitly assigns a
>   task. Ignis itself MUST NOT contain a scheduler, worker, always-on radar or background
>   collection loop, and MUST NOT discover topics on its own.
> - A user MAY ask their own agent to run one watchlist on a recurring schedule through the host's
>   native scheduler. Each firing is a separate explicit task: one watchlist run, bounded by the
>   watchlist version, the run's own stated authority and the per-channel daily request ceilings.
>   An agent MUST NOT set up, widen or resume such a routine without the user's explicit request,
>   and the user MUST be able to see, pause and remove it in the host.

## Change 2: Principle III, the clock for listening periods

Current text:

> - Time-window queries MUST use an ingestion clock whose provenance is exact. Publication time is a
>   separate fact and MUST NOT silently substitute for ingestion time. Legacy observations whose
>   ingestion time was never recorded keep `observed_at = NULL` with explicit provenance.

Proposed text:

> - Collection windows, evidence frames and every other time-window query MUST use an ingestion
>   clock whose provenance is exact. Legacy observations whose ingestion time was never recorded keep
>   `observed_at = NULL` with explicit provenance.
> - A listening period (a calendar day, week or month of a watchlist) places each observation by its
>   publication time when a plausible one exists, and otherwise by its ingestion date, flagged as
>   such. The basis MUST be stated with every figure; publication time MUST NOT silently substitute
>   for ingestion time anywhere else.

## Impact report

- **Specs 016 and 017**: Spec 016 Part B (period comparison) and Spec 017 (host routines) may merge
  only after ratification. Spec 016 Part A (watchlists, versions, runs) needs neither change.
- **Code**: no existing behaviour changes. Collection windows, evidence frames, claim admission and
  every current time-window query keep the ingestion clock.
- **Documents to update on ratification**: `.specify/memory/constitution.md` (both bullets, Sync
  Impact Report, version line); `CLAUDE.md` "Architecture: Mission-Bound Research" and
  "Operational Boundary" ("cannot ... launch recurring collection" gains "except a host routine the
  user asked for"); `AGENTS.md` section 1; the 2026-09-29 decision record gains a pointer to the
  2026-10-21 one. Templates under `.specify/templates/` carry no wording on either point.
- **Tests**: `tests/unit/test_ignis_skills.py` keeps "daily" and "scheduler" out of the collection
  and analysis skills; routine guidance lives only in the Spec 017 guide, so that check stays.
