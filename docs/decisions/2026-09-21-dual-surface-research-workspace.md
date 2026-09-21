# Decision: Dual-Surface Research Workspace

**Status:** Accepted
**Date:** 2026-09-21
**Scope:** Product and storage boundary for the next research workflow

## Context

fn-ignis needs to support two different user intents in one research experience:

- discovering what is receiving attention; and
- investigating whether a selected topic represents a market opportunity.

These intents use related observations but require different questions, evidence standards,
and conclusions. A chat session is owned by the host Agent tool (Claude Cowork, Claude Code,
or Codex), so it is not a durable fn-ignis domain boundary.

## Decision

fn-ignis will use two independent analytical surfaces backed by one configured shared Ignis
database and a logical research workspace scope:

- `ATTENTION` is exploratory trend discovery.
- `MARKET` is hypothesis-driven market investigation.

One research is represented by a child workspace inside the current host workspace:

```text
<current-workspace>/.ignis/research/<research-slug>/
```

The workspace is local-first and is ignored by Git by default. The Agent asks for the research
name or slug, shows the proposed path, and creates the workspace only after user confirmation.

## Analytical contract

### ATTENTION

`ATTENTION` may start without a hypothesis or Market Brief. It returns:

- ranked topics or clusters;
- momentum and freshness signals;
- source diversity and coverage;
- evidence citations; and
- candidate topics that the user may select for a Market investigation.

`ATTENTION` must not emit an `Opportunity Index` or present attention as commercial demand.

### MARKET

`MARKET` may start directly or be created from an explicitly selected Attention topic. It
cannot run until the requester confirms a `Market Brief` containing:

- `decision`;
- `target_user`;
- `problem`;
- `geo`;
- `timeframe`;
- `hypothesis`; and
- `falsifiers`.

The Q&A is adaptive and asks one question at a time. It has at most seven primary questions,
allows the requester to edit the draft, and persists no abandoned transcript. Confirmation is
the explicit boundary that turns the draft into a durable Brief and authorizes Market probes.

The Market output may include demand and supply analysis, Voice of Customer evidence,
confidence, falsifiers, `Opportunity Index`, and a next-validation plan. The `Opportunity
Index` belongs only to `MARKET`.

## Handoff and revision rules

Selecting an Attention topic creates a new Market mission draft. Attention observations are
context and lineage for that draft, not Market proof. Market probes must produce evidence
against the confirmed Market Brief.

A confirmed Market Brief is immutable. If the requester changes the hypothesis or any other
required field, fn-ignis creates a new Brief revision and Market mission. The new mission runs
its own Market probes. Earlier evidence may remain linked as context or lineage, but is not
automatically counted as support for the new hypothesis.

## Workspace ownership and storage

The Ignis installation has one configured database shared by all Ignis research and baseline
data. SQLite-local is the default; PostgreSQL is an optional configured backend. Research data is
separated logically inside that shared schema by `workspace_id` and mission foreign keys. A
research workspace is therefore a user-visible filesystem scope and a database scope, not a
separate database:

```text
.ignis/research/<research-slug>/
├── manifest.json
├── briefs/
├── missions/
├── evidence/
├── journals/
└── artifacts/
```

The configured Ignis database is the canonical record store. JSON, HTML, journals, and other
workspace files are projections, run records, exports, or artifacts with provenance; they must
not silently become a second source of truth. Every research-owned record must carry or be
reachable through `workspace_id`; cross-workspace reads and evidence links are rejected.

The workspace folder may be reopened by another supported Agent host connected to the same Ignis
database. Copying the folder alone is not a standalone research backup; database backup/export is
required for portability. An existing child folder may be reused only when it has a valid matching
manifest. A non-empty folder without a manifest requires explicit user confirmation before it
is adopted, and adoption must not delete or overwrite unrelated files.

## Concurrency contract

- Multiple agents may read a research workspace concurrently.
- Different missions may run concurrently.
- A single mission has one writer; a second run must create a new revision or fail clearly.
- SQLite transactions and WAL-style coordination protect canonical state.
- Each run has an exclusive, collision-safe journal; run state must never be updated through
  whole-file overwrite of a path another run may hold.

## Consequences

### Benefits

- Attention discovery is not forced to pretend it already has a market thesis.
- Market conclusions have an explicit, requester-confirmed hypothesis and falsifiers.
- A research is addressable across Agent hosts connected to the same Ignis installation and
  independent of chat-session identity.
- Immutable Brief revisions preserve evidence lineage and prevent retroactive reinterpretation.
- Local-first storage avoids accidentally committing raw research data to the product repository.

### Costs

- A new Market hypothesis requires a fresh probe run.
- The system does not retain abandoned Q&A wording for later replay.
- Shared SQLite/PostgreSQL storage and workspace-level concurrency require explicit scoping,
  locking, and migration discipline.
- Users must confirm a workspace location/name before durable research state is created.

## Out of scope for this decision

- Implementing the workspace storage layer.
- Defining a standalone database backup/export format for copying a research outside its Ignis
  installation.
- Defining the final UI for Attention cards or Market reports.
- Changing the existing Opportunity Index formula.
- Adding new connectors or changing connector authentication.
- Automatically publishing or committing research artifacts.

## Implementation direction

The next implementation work should translate this decision into a feature specification and
dependency-ordered tasks. The specification must preserve the distinction between Agent chat
metadata, research workspace identity, Attention evidence, Market evidence, and immutable
Brief revisions.
