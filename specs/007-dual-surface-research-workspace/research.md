# Phase 0 Research: Dual-Surface Research Workspace

## Decision 1: Make the research workspace the durable boundary

**Decision:** Store one research below the host workspace at
`.ignis/research/<research-slug>/`, after the requester confirms the proposed path.

**Rationale:** Claude Cowork, Claude Code, and Codex already provide the host workspace and chat
context. Chat-session identity is not stable enough to own research data, while a child folder is
visible, addressable across Agent hosts, and independent of the originating Agent process.

**Alternatives considered:**

- Auto-create a folder at a default path: rejected because durable writes require explicit user
  confirmation.
- Use the chat session as the research boundary: rejected because the same research may continue
  in another host or chat.
- Use only the chat session as the research boundary: rejected because chat identity is owned by
  the host tool and does not define a durable database scope.

## Decision 2: Use one shared Ignis database with logical research scopes

**Decision:** One Ignis installation uses one configured database for all Ignis data. SQLite-local
is the default; PostgreSQL is optional. Research records are separated inside the shared schema
by `workspace_id` and mission foreign keys. The research folder contains the manifest, journals,
and artifacts, not a second database.

**Rationale:** SQLite is already the project's zero-configuration backend, while PostgreSQL is
the supported configured backend for larger installations. A shared database avoids per-research
database sprawl and keeps the existing source, observation, and mission-evidence contract in one
place. Logical workspace scoping preserves research isolation without creating another source of
truth.

**Alternatives considered:**

- Give each research a separate database: rejected because it creates database sprawl, complicates
  backend setup, and prevents one Ignis installation from sharing its existing storage contract.
- Store every record as independent JSON files: rejected because mission evidence, uniqueness,
  transactions, and concurrent writers need relational invariants.
- Treat a copied folder as a standalone backup: rejected because the canonical records live in the
  configured Ignis database; a separate backup/export contract is a later feature.

## Decision 3: Separate Attention from Market analysis

**Decision:** `ATTENTION` is exploratory and may run without a hypothesis. `MARKET` is gated by a
confirmed, falsifiable Market Brief and is the only surface that emits an Opportunity Index.

**Rationale:** Attention measures what is receiving attention; Market analysis tests a commercial
question. A shared score would turn a signal into a verdict and conceal the different evidence
standards.

**Alternatives considered:**

- Run the same six-step market workflow for every Attention request: rejected because it forces a
  thesis before discovery.
- Emit Opportunity Index for both surfaces: rejected because attention is not demand or supply.
- Use one mutable mission that changes surface: rejected because it blurs lineage and makes old
  evidence appear to support a new question.

## Decision 4: Persist only confirmed Market Brief revisions

**Decision:** The Agent conducts adaptive Q&A in chat context. Only a requester-confirmed Brief
containing `decision`, `target_user`, `problem`, `geo`, `timeframe`, `hypothesis`, and
`falsifiers` is persisted. Confirmed revisions are immutable.

**Rationale:** The durable contract is the decision frame that authorized the probes, not an
abandoned conversation transcript. Immutable revisions preserve the meaning of earlier
evidence.

**Alternatives considered:**

- Persist the full Q&A transcript: rejected for unnecessary retention and because the confirmed
  Brief is the reproducible input.
- Persist an editable Brief in place: rejected because changing a hypothesis after evidence
  exists rewrites history.
- Allow Market probes with partial fields: rejected because the result would not have a clear
  decision, user, scope, or falsifier.

## Decision 5: Treat Attention handoff as context, not Market proof

**Decision:** Selecting an Attention topic creates a new Market draft with explicit lineage. The
Market mission runs its own probes after Brief confirmation. Earlier Attention observations may
be linked as context but are not automatically counted as support for the Market hypothesis.

**Rationale:** The same topic can be interesting without representing demand, intent, or a viable
supply gap. Fresh Market evidence protects that distinction.

**Alternatives considered:**

- Reuse Attention observations as Market evidence automatically: rejected because the collection
  question and evidence role differ.
- Start a Market mission without explicit topic selection: rejected because the Agent would infer
  commercial scope the requester never chose.

## Decision 6: Allow independent mission concurrency, but one writer per mission

**Decision:** Different missions in one workspace may run concurrently. The same mission has one
active writer; a conflicting run creates a new revision or fails clearly. Run journals use
exclusive collision-safe creation.

**Rationale:** Parallel Attention and Market work is useful, while two writers mutating one mission
would make evidence and state ambiguous. T023 establishes the required exclusive journal pattern.

**Alternatives considered:**

- Lock the entire workspace for every run: rejected because unrelated missions would block one
  another.
- Allow multiple writers for one mission: rejected because last-write-wins would corrupt lineage.
- Use existence checks before journal writes: rejected because a race can still overwrite a path
  between check and write.
