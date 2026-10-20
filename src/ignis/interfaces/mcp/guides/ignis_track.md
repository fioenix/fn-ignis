# Ignis tracking artifact

Use this guide when a person wants to follow an Ignis research mission. Ignis renders no tracking
page. You read one bounded snapshot and generate an artifact in whatever form your host supports:
a Markdown file, an HTML page or a canvas. The artifact helps the person see what the mission
collected and why a conclusion is permitted or withheld. It is never a market verdict, and it is
never a control surface: it must not start, pause or cancel mission work.

## Read

1. Select one mission explicitly. A follow-up child is a different mission and is read separately.
2. Call `get_mission_relay_snapshot` with that `mission_id` and an explicit `page_size` from 1 to
   200. Pass `run_id` only when the person selected a run.
3. Page events with `after_revision` and `after_ordinal` taken from `event_page.next_cursor`.
   Page evidence with `evidence_offset` set to the returned `next_evidence_offset`. Every page you
   combine must carry the same `revision` as the first read. If a page has a different `revision`,
   or `event_page.resync_required` is true, discard the pages and start again from the first read.
4. Use a snapshot only when its `status` is `OK`. A response with `REFUSED` or `UNAVAILABLE` and a
   `reason_code` is a failed read, never empty data. A `ROOT_REQUIRED` tool error means Ignis
   cannot reach the caller's storage; report it rather than retrying elsewhere.
5. Reject a snapshot whose `mission_id`, `run_id` or `frame_digest` does not match the scope you
   selected or the pages you are combining.

## When to generate

Generate or regenerate the artifact only:

- when the person asks for it; or
- at a milestone inside your own active turn: collection settled, qualification recorded, a claim
  or gap changed, or research work ended.

Do not poll, set timers or schedule refreshes. Do not read the snapshot again after your turn
ends. Each artifact comes from one coherent read: a first successful snapshot plus any further
pages with the same `revision`. Show that read's `read_at`, `revision`, `counts` and `claim_gate`.

## What to show

Take every value from the snapshot. Show:

- mission ID, `surface` (`MARKET` or `ATTENTION`), `revision` and `read_at`;
- the run: `run_id` echoes only a run you selected; when it is null, show
  `research.current_run_id` if research is available, otherwise say the run is unknown;
- `frame_digest`, or `frame_pending_reason` when no frame is bound;
- `collection_state`, or "unknown" when it is null;
- each entry in `channels` with its `platform`, `connector_surface`, `status`, `signals_collected`
  and `note`;
- evidence rows with `title`, `source_url`, `published_at`, `captured_at`, `evidence_role`,
  `direction`, `qualification_relation` and the `source_policy` status;
- the claim gate: `claim_gate.state`, `claim_gate.render_status` and `claim_gate.reason_code`;
  permitted claims from `claim_gate.claims` with their evidence bindings; otherwise
  `claim_gate.gap_report`; earlier claims from `claim_gate.history` labeled as history;
- research work and findings from `research` when its `availability` is `AVAILABLE`, otherwise
  say research is unknown. For each finding, show `latest_recorded` (the newest revision) and
  `current_eligible` (eligible for the current frame) separately; a finding with `text_withheld`
  true is shown as withheld, never as empty text. Label work `activity` with
  `provenance` `HOST_REPORTED` as reported by the host, and items with `recorded_provenance`
  `HARNESS_OBSERVED` as observed by Ignis;
- `related_results`: follow-up child missions, each of which must be selected and read on its own;
- totals from `counts` with the evidence page shown (`evidence_offset`, `page_size`).

Every artifact states that it is a point-in-time snapshot taken at `read_at`, not a live view.

## Display rules

| State | Show it only when the snapshot says so |
|---|---|
| Permitted claim | `claim_gate.state` is `CURRENT`, `render_status` is `PERMITTED`, and the claim is in `claim_gate.claims` with the same `frame_digest`. |
| Withheld or gap | `claim_gate.state` is `PENDING` or `UNAVAILABLE`, `render_status` is `WITHHELD`, or a `gap_report` is present. Show the `reason_code`. |
| Missing or unavailable | A channel `status` is null (not measured), `NOT_REQUESTED` (outside this run's plan) or `AUTH_REQUIRED`, `RATE_LIMITED`, `DEGRADED` or `FAILED` (unavailable); `frame_pending_reason` is set; or a time or metric is null. Say which. `EMPTY_NO_DATA` means the channel ran and matched nothing for this query, which is not zero demand. |
| Stale | `claim_gate.state` is `STALE` or `HISTORY`, or a later read failed or returned a different `frame_digest`. |
| Point in time | Always: show `read_at` and never call the artifact live. |

Also:

- Never render a withheld, stale or historical claim as permitted, and never restate it as a
  conclusion in your own words.
- Never turn an unavailable, unrequested or unmeasured channel into zero demand. A null count is
  unknown; a measured zero is zero.
- Never add metrics, scores, confidence, trends or activity that the snapshot does not contain.
- Evidence: `metric_value` and `growth_velocity` are raw popularity, not demand. Only rows whose
  `qualification_relation` is `QUALIFIED_SUPPORT` or `QUALIFIED_CONTRADICTION` bear on the
  question; `CONTEXT_ONLY`, `EXCLUDED_IRRELEVANT`, `UNASSESSED` and the `ATTENTION_CONTEXT` role
  are never support. Show contradicting evidence as visibly as supporting evidence. An
  `ATTENTION` mission makes no market claim.
- Sources: show the actual channel and outcome. The snapshot does not carry the query text; do
  not reconstruct it. Noise filtering does not establish market relevance.
- Cleaning and provenance: show recorded qualification and source policy with their times; keep
  unknowns visible.
- Research: show recorded specialist work and handoffs only; unknown capacity stays visible.
- Cross-check: shared observations are not independent corroboration.
- Synthesis: keep source-bound finding revisions separate from permitted claims and gaps.
- Timeline: use recorded timestamps and label each item current or historical.
- Colour always comes with a text label. All essential content must be readable as static,
  structured text without scripts, motion, web fonts or network access.

## After a failed read or a frame change

The next artifact withdraws current permission from every claim shown earlier and labels the last
successful read as stale, with its `read_at`. Show the failure `reason_code` or the new
`frame_digest`. Do not carry earlier permitted claims forward.

## Replay

A replay is an optional form of the artifact for a person who wants to watch how a mission
reached the state of one read. It plays back that read's event journal and ends on the read
itself. Everything in "What to show" and "Display rules" holds at every step.

1. Build from one coherent read, as in "Read", with its complete event journal: page events until
   `event_page.next_cursor` is null. A read whose event journal is missing or incomplete gets the
   static artifact only.
2. Make one step per event in `(revision, ordinal)` order, timed by its `recorded_at`; show
   `occurred_at`, when set, as a labelled detail. A step changes the picture only through its
   event's `kind`, `provenance`, `reason`, `run_id`, `work_id`, `handoff_id`, `finding_id`,
   `claim_id` and `evidence_references`:
   - `OBSERVATIONS_COMMITTED` adds the observations it references, except that a `reason` of
     `MEMBERSHIP_PRUNED` removes them; `MEMBERSHIP_REATTACHED` adds them back.
   - An observation takes its qualification colour at the event that records its
     `qualification_relation`, labelled with its frame when that event's
     `qualification_frame_fingerprint` is not the read's `frame_digest`.
   - A claim's status at a step is the `reason` of its latest `CLAIM_GATE_CHANGED` event, shown as
     recorded history with that event's time.
3. End on the read step at `read_at`, showing the read's own `claim_gate`, `counts`, `channels`,
   `research` and `related_results`. Current permission appears only here, and only for claims
   in `claim_gate.claims`.
4. Put the read's complete static content beside the replay; the read step matches it. When the
   person prefers reduced motion, open on the final step.

Keep every replayed value traceable to the read:

- Label the artifact a replay of the read at `read_at`. Its clock shows recorded event times and
  stops at `read_at`.
- Each figure names its source: a snapshot field, or a count of the distinct identifiers present
  after the step, such as observations committed and not pruned. A figure changes only at the
  step whose event changes it and holds still between steps. A bar or percentage names both
  counts it divides.
- A value that no event establishes, such as a channel's `signals_collected`, first appears at
  the read step and shows as not yet recorded before it. A channel or research state that is null
  or unavailable in the read keeps that state from the first step.
- Unless spacing is proportional to `recorded_at`, say the replay is paced by event order, not
  elapsed time, and show the actual elapsed time separately, for example as a timeline with each
  event at its `recorded_at` and the longest gap labelled.
- Motion traces recorded events. Ambient motion, such as a glow or a slow rotation, stays
  constant through the replay and is labelled decorative.
- Draw a node only for a stage, channel or specialist the read contains, and attach work,
  handoff and finding steps to it by their identifiers.
- Playback controls, such as play, pause or jump to a step, move only the replay and show step
  numbers rather than percent complete.

## Where it goes

Write the artifact to a local file by default and tell the person its path. Before publishing it
to any host or service outside the person's machine, such as a shared page, a document service or
a chat channel, ask for consent for that specific publication. Consent for one publication does
not cover the next.
