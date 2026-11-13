# Feature Specification: Customer Voice in Ten Minutes

**Feature Branch**: `026-customer-voice-ten-minutes`

**Created**: 2026-11-13

**Status**: Clarified 2026-11-13. Plan accepted; direct implementation (see `plan.md`).

**Input**: BACKLOG PRD-1, "Tiếng nói khách hàng trong 10 phút": one keyword, TACTICAL probes, the comments
of the first N TikTok videos, and one synthesis with quotations, built as a skill or guide with no new tool.
The owner asked to start it in chat on 2026-11-13 ("Làm PRD-1").

## Outcome and audience

A founder, seller or analyst researching a product in Vietnam gives their agent one keyword and, within ten
minutes, reads what people say about it on TikTok and Threads, each quotation linked to its source. Today the
agent has the pieces (host-browser search, `get_tiktok_video_comments`) but no procedure that chains them,
bounds the sample, and keeps the result from reading as a market verdict.

The result is attention context. It is never demand evidence, an Opportunity Index or a "sell or not"
verdict (AGENTS.md §1–2). A person who needs that decision is sent to a mission with a Market Brief.

## Clarifications

### Session 2026-11-13

- Q: PRD-1 names a TACTICAL YouTube probe, but YouTube has no tactical search tool (it is collected only inside
  a mission). Which sources does the ten-minute run use? → A: TikTok host-browser search, the comments of the
  first videos, and Threads host-browser search; YouTube is left out of this run (owner decided, chat
  2026-11-13).
- Q: How many TikTok videos, and how many comments each? → A: The first 5 videos, 20 comments each (owner
  decided, chat 2026-11-13).
- Q: How is it packaged without a new tool? → A: A new packaged guide `ignis_customer_voice` served as the
  resource `fn-ignis://guide/ignis-customer-voice`; the existing prompt `voice_of_customer_audit` keeps its name
  and returns this guide with the keyword (owner decided, chat 2026-11-13).
- Q: What form does the synthesis take? → A: A local Markdown file under `reports/`, every quotation with its
  link and source and the label "attention context, not a verdict"; a short summary in chat (owner decided,
  chat 2026-11-13).
- Q: Does the synthesis label pain points, objections, price mentions or purchase intent? → A: No. That is PRD-2,
  which reopens the pain-summary work deferred on 21/10 and needs the owner's approval; this guide groups
  quotations by what they talk about, in the requester's words, with no labels or scores (agent decided; basis:
  BACKLOG PRD-2).
- Q: Real TikTok and Threads sessions? → A: Already authorized on the Finos profile (OWN-3, owner, 2026-11-11).

## Functional requirements

- **FR-001**: The guide runs only after the person names one keyword and asks for this run now; it is never a
  background or scheduled collector.
- **FR-002**: The guide chains, in order: one TACTICAL TikTok host-browser search; `get_tiktok_video_comments`
  on the first 5 accepted TikTok links with `limit=20`; one TACTICAL Threads host-browser search, reusing the
  relay tab only after the TikTok relay shows `STAGED`. Host-browser steps follow the `ignis_browser_relay` guide.
- **FR-003**: A failed or `DEGRADED` source is reported unavailable for this run and the run continues with the
  other sources; there is no retry loop, other browser or evasion. A comment call that errors is reported for
  that video only.
- **FR-004**: The guide records the start and end time with the host's clock and reports the elapsed time.
- **FR-005**: The synthesis keeps only items relevant to the keyword, judged by the agent, and reports how many
  items were read and how many were kept, per source.
- **FR-006**: Every quotation carries its source (TikTok caption, TikTok comment, Threads post) and its link: the
  observation link, or for a comment the video link plus the `comment_id`. No author, account, handle or
  profile link is added (Principle VII).
- **FR-007**: The synthesis groups quotations by what they talk about, with no sentiment, intent, pain or
  prevalence label, score or percentage, and states that the sample is a bounded visible sample.
- **FR-008**: The file opens with the keyword, the run time in Asia/Ho_Chi_Minh, the sources and their outcomes,
  and the label that it is attention context, not a verdict; it ends with the mission route for a decision.
- **FR-009**: Collected text is data, never instructions; the guide says so, and HTML is not produced.
- **FR-010**: The file is written locally under `reports/`; publishing it anywhere else needs the person's
  consent for that publication.
- **FR-011**: `voice_of_customer_audit` returns the packaged guide, preceded by the keyword when one is given;
  `fn-ignis://guide/ignis-customer-voice` returns the guide. The MCP catalog stays at 41 tools.

## Success criteria

- **SC-001**: One live run on the Finos profile, following only the guide, reaches the file within 10 minutes
  with at least 15 kept items.
- **SC-002**: The PRD-1 kill and keep thresholds stay with the owner's pilot: median time to artifact at most
  10 minutes and the person says they would use it again; stop if the median exceeds 20 minutes or relevance
  falls to the 2/50 level (BACKLOG PRD-1). This spec ships the guide; the pilot measures it.

## SC-001 live acceptance (2026-11-13)

Keyword `nồi chiên không dầu`, Finos profile, run by the coordinating agent that wrote the guide (not a fresh
agent), following the guide's steps:
- 13:40:31 start; 13:43:16 collection done; 13:43:42 file written: **3 min 11 s** to the artifact.
- TikTok search `ACCEPTED`, 11 captions read, 11 kept; comments on the first 5 videos, all `SUCCESS`, 33 read
  (the videos held fewer than 20 each), 23 kept; Threads `ACCEPTED`, 5 read, 5 kept: **39 kept items**.
- Two guide gaps found and fixed in this change: relay step 1 did not name `host_task_ref` and `session_ref`
  (the first prepare call failed validation), and the synthesis needed the caveat that TikTok captions are
  often sellers' own.
- SC-001 is met. SC-002 (median over users, reuse) stays with the owner's pilot.

## Out of scope

YouTube, Instagram (the person may add it as an extra host-browser search), labelling (PRD-2), storing comments,
any new MCP tool or tool signature change.
