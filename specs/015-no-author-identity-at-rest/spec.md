# Feature Specification: No Author Identity at Rest

**Feature Branch**: `codex/no-author-identity-at-rest`

**Created**: 2026-10-20

**Status**: Draft

**Input**: Owner description (20/10/2026): "Ignis only needs an aggregate view of the market and
consumer taste; it does not need to know WHO said something." Make "Ignis stores no author
identity" an invariant enforced by tests rather than a claim. Approved defaults: count distinct
authors per mission through an unlinkable per-mission marker, and keep only a content identifier
as the reference to the original content.

## Outcome and audience

A person researching a Vietnamese consumer market with Ignis, often through their own personal
platform accounts, gets market and taste evidence without Ignis keeping a record of who wrote any
post, comment or review. They can still tell whether a pattern comes from many independent voices
or from a few accounts repeating themselves, and they can still open the original content to
verify it.

The decision this supports is the owner's product promise: Ignis analyses what the market says,
not who says it. The observable proof is that no durable store, tool response, report or log
produced by Ignis contains an author's identity, verified by an automated check that every
connector must pass.

The audience is founders, operators and analysts, including people preparing or starting a
business who have no business-tier platform access. That audience is the constitution's stated
beachhead, not an independently measured segment.

## Context: current state (observed 20/10/2026 on `main` at `11f4025`)

The current code does not meet this promise. Observed by reading the code, not by inspecting
production data:

- TikTok search observations keep the author's handle and display name, and their content links
  embed the handle.
- YouTube observations keep the channel identifier and channel title.
- Threads and Instagram Reels observations keep the author's username and account identifier; one
  Reels path also keeps the full caption without redaction.
- TikTok comment pseudonymization uses one fixed salt shared by every mission and keeps only four
  hexadecimal characters, so markers link the same person across missions and collide often.
- Research report citations display an author or channel field.
- Text redaction covers email addresses, phone numbers and secrets, not handles, @mentions or
  personal names.

The local caller database inspected held five observations and none carried a username. The dev
PostgreSQL corpus was not inspected because no connection was available in that session.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Research without keeping who said it (Priority: P1)

A founder runs a market mission that collects posts, videos, comments and reviews through official
APIs and their own browser session. Every observation Ignis keeps carries the content, its metrics,
the platform, the platform's content identifier and its times, and nothing that identifies the
author.

**Why this priority**: This is the promise itself. Without it the other stories have no purpose.

**Independent Test**: Run a mission against fixture sources in which every author field each
supported connector can return is filled with a recognisable identity value. Search every durable
store, tool response, generated report and log produced by the run for those values; none appear,
and the mission still produces its observations and claims.

**Acceptance Scenarios**:

1. **Given** a connector returns a post with a handle, a display name and an account identifier,
   **When** the observation is kept, **Then** none of those values is kept and the platform and
   content identifier are.
2. **Given** a platform whose content links normally embed the author's handle, **When** the user
   opens the evidence from a report or tracking artifact, **Then** the link they receive contains no
   handle and still opens the original content where the platform supports that.
3. **Given** a research report or Gap Report is generated, **When** the user reads a citation,
   **Then** it shows platform, content reference, time and metrics, and no author or channel.
4. **Given** the operator configured their own accounts for self-content exclusion, **When** their
   own content appears in collection, **Then** it is still excluded and no author identity is kept.
5. **Given** an agent submits host browser results that include author fields, **When** Ignis
   accepts the submission, **Then** the author fields are dropped and the rest of the submission is
   accepted.

---

### User Story 2 - Tell many voices from one voice (Priority: P2)

An analyst sees 50 observations praising a product and needs to know whether they come from 50
people or from 3 accounts posting repeatedly. Within one mission, Ignis reports how many distinct
authors stand behind a pattern and how concentrated it is, without knowing who they are.

**Why this priority**: Seeding and astroturfing are common in Vietnamese social commerce. Without
this, removing identity would weaken the analysis the product exists to deliver.

**Independent Test**: Feed one mission a fixture of observations with a known author distribution
and confirm the distinct-author count and concentration match ground truth; feed the same authors to
a second mission and confirm no marker matches between the two.

**Acceptance Scenarios**:

1. **Given** 10 observations from 2 authors in one mission, **When** the user asks how many
   distinct authors stand behind them, **Then** the answer is 2.
2. **Given** the same author appears in two missions, **When** the two missions' markers are
   compared, **Then** they differ and cannot be matched.
3. **Given** a mission's evidence is deleted under its retention policy, **When** deletion
   completes, **Then** nothing that could turn that mission's markers back into identities remains.
4. **Given** an observation whose source reported no author, **When** distinct authors are counted,
   **Then** it is counted as unknown and never merged with a known author.

---

### User Story 3 - Handles inside the content itself (Priority: P3)

Comments and reviews often name other people with @mentions. Ignis keeps the wording that matters
for market analysis and replaces platform handles and @mentions with a neutral placeholder.

**Why this priority**: Content text is the main remaining place an identity can enter storage after
author fields are removed, but it carries less risk than structured author fields.

**Independent Test**: Collect fixture comments containing @mentions and handles in several
positions and forms; kept text contains the placeholder and none of the handles, and the remaining
wording is unchanged.

**Acceptance Scenarios**:

1. **Given** a comment "@linh.nguyen mua ở đâu vậy", **When** it is kept, **Then** the stored text
   reads "@[user] mua ở đâu vậy".
2. **Given** a review containing an email address or phone number, **When** it is kept, **Then**
   the existing redaction still applies.

---

### User Story 4 - Know what older data already holds (Priority: P4)

The owner needs to know how much author identity already sits in existing caller storage and in the
dev PostgreSQL corpus before deciding whether to delete or anonymise it.

**Why this priority**: The invariant protects new data only. Older data needs a separate,
owner-approved disposition and must not be changed silently.

**Independent Test**: Run the inventory against a fixture database seeded with known identity
fields; it reports counts per store and field, displays no identity value and writes nothing.

**Acceptance Scenarios**:

1. **Given** an existing store, **When** the inventory runs, **Then** it reports, per store and per
   field, how many records hold author identity, and shows none of the values.
2. **Given** the inventory has run, **When** no owner disposition is recorded, **Then** no existing
   record is changed.
3. **Given** the owner approves a disposition, **When** it is applied, **Then** a manifest of the
   targets exists beforehand and a readback afterwards proves the result.

---

### Edge Cases

- A source offers neither a content identifier nor a link free of identity: the observation is
  refused with a visible reason and counted as a collection limitation, never kept with identity.
- A platform cannot open content from an identity-free link: the evidence shows platform and
  content identifier with an explicit "link unavailable" label.
- The account behind a post is a brand or a shop, not a person: it is treated like any other
  author. Brand presence is derived from the content and from the market lexicons, not from the
  posting account.
- An error or log line echoes a raw platform payload: author fields are removed before it is
  written.
- A follow-up run or a later run of the same mission adds observations: markers stay consistent
  with earlier runs of that mission.
- A future connector returns an author field under a new name: the conformance check fails until
  the connector removes it.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Ignis MUST NOT keep the identity of a content author (handle, display name, platform
  account identifier, profile link or avatar) in any durable store it writes: canonical database,
  caller storage files, run journals, follow-up storage, generated reports and artifacts, and logs.
- **FR-002**: Ignis MUST NOT return author identity in any tool response, prompt or resource.
- **FR-003**: Author identity MUST be removed where collected data enters Ignis, before its first
  durable write, for every connector and for agent-submitted host browser results.
- **FR-004**: Self-content exclusion of the operator's own accounts MUST keep working, decided
  before author identity is removed.
- **FR-005**: Each kept observation MUST reference its original content by platform and the
  platform's content identifier. Any link shown to the user MUST be produced from that reference
  and MUST NOT contain author identity.
- **FR-006**: When neither a content identifier nor an identity-free link can be obtained, Ignis
  MUST refuse the observation with a visible, countable reason.
- **FR-007**: Within one mission, Ignis MUST give each observation an author marker that is the same
  for the same author across every run and follow-up of that mission, and different across
  missions.
- **FR-008**: The secret that makes a mission's markers MUST stay in the caller's own storage, MUST
  NOT appear in any response, report, export or log, and MUST be destroyed when that mission's
  evidence is deleted.
- **FR-009**: Analysis MUST be able to state, per mission and per channel, the number of distinct
  authors behind a set of observations and how concentrated the observations are among them.
- **FR-010**: An observation with no reported author MUST carry an explicit unknown marker that is
  never counted as the same author as another observation.
- **FR-011**: Kept content text MUST have platform handles and @mentions replaced by a neutral
  placeholder; existing redaction of email addresses, phone numbers and secrets MUST continue.
- **FR-012**: User documentation MUST state that personal names written in free text are not
  guaranteed to be removed, and MUST state what is removed.
- **FR-013**: An automated conformance check MUST fail when any connector, ingress path, report,
  response or log produced from a fixture carrying author identity in every known author field
  contains any of those values. Every connector, including future ones, MUST pass it.
- **FR-014**: Ignis MUST provide a read-only inventory of author identity already held in caller
  storage and in a configured PostgreSQL database, reporting counts per store and field without
  displaying values.
- **FR-015**: Existing data MUST NOT be changed without an explicit owner disposition. An approved
  change MUST publish a manifest of its targets before acting and a readback after.
- **FR-016**: Report and tracking citations MUST show platform, content reference, time and
  metrics, and MUST NOT show an author or channel.
- **FR-017**: Operator account identities supplied for self-content exclusion MAY remain in runtime
  configuration as the operator's own data, and MUST NOT be copied into observations.

### Key Entities

- **Observation**: one kept sighting of content. Holds content text, metrics, platform, content
  identifier, collection and publication times, and an author marker; holds no author identity.
- **Content reference**: platform plus the platform's content identifier, from which a link is
  produced for display.
- **Author marker**: a value that tells whether two observations in one mission share an author
  and reveals nothing else. Known or unknown.
- **Mission marker secret**: the caller-held secret that makes one mission's markers; lives and
  dies with that mission's evidence.
- **Refusal reason**: a visible, counted record that a sighting was not kept because no
  identity-free reference existed.
- **Legacy identity inventory**: counts of author identity per store and field in existing data,
  without values.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Across a fixture corpus covering every supported connector and agent-submitted
  results, 0 author identity values appear in any durable store, tool response, report or log.
- **SC-002**: On a fixture of ten thousand distinct authors in one mission, the distinct-author count
  matches ground truth exactly.
- **SC-003**: For the same set of authors placed in two missions, 0 markers match between the
  missions.
- **SC-004**: For every platform that can open content from an identity-free link, 100% of kept
  observations give the user a working link; every other observation shows its content identifier
  with an explicit label.
- **SC-005**: Self-content exclusion still excludes 100% of the operator's fixture content.
- **SC-006**: The legacy inventory completes with 0 writes and 0 displayed identity values.
- **SC-007**: A deliberately leaking fixture connector fails the conformance check, proving the
  check is not vacuous.
- **SC-008**: An existing mission fixture produces the same claims, permissions and Gap Report
  outcome before and after the change, apart from removed author fields.

## Assumptions

- The owner principle of 20/10/2026 governs: Ignis serves aggregate market and taste analysis and
  never needs to know who said something.
- Brand and shop accounts are treated as authors and are not kept. Analysis of competitor accounts
  as accounts is out of scope; brand presence comes from content and lexicons. This is the main
  scope choice to confirm in clarification.
- Personal names in free text are handled on a best-effort basis and are outside the strict
  invariant (FR-012).
- Processing identity in memory during collection is still processing under Law 91/2025/QH15.
  This feature minimises what is kept; it does not by itself establish legal compliance, which
  needs separate legal review.
- Mission retention policy is unchanged; the marker secret's lifetime follows it.
- The spec is numbered 015 because Spec 014 lives on the unmerged branch
  `codex/ignis-relay-checkout` (PR #51). This branch starts from `main` at `11f4025`. When Spec 014
  merges, its snapshot and evidence rows fall under FR-002 and FR-016.
- The constitution has no explicit privacy principle. Adding one is an owner decision under its
  amendment rule; this spec proposes it and does not assume it.
- Changing existing dev or production data stays an owner decision (FR-015); the inventory is the
  only part of User Story 4 this feature performs on its own.
