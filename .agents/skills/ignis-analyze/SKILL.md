---
name: ignis-analyze
description: Apply Senior Market Analytics to an eligible Ignis Market mission when a user requests insights, a decision brief, a report, or a dashboard grounded in collected social evidence.
---

# Ignis analysis

The output is a decision record whose claims can be traced to the current evidence frame. Design
for the person deciding whether to spend time or money on a market hypothesis.

Read the hypothesis, qualification, and Claim Ledger rules in
`specs/011-evidence-grounded-product-reset/contracts/` and the current MCP tool descriptions.
Those contracts and persisted mission records own the policy; this skill supplies the agent's
method, not a second set of thresholds or a report template.

## Analyze one confirmed question

1. Reopen the Market mission and confirmed Brief. Name the decision, core hypothesis, alternatives,
   null hypothesis, falsifiers, and conditions that would reverse the decision.
2. Read `get_mission_evidence_qualification_batch`. Judge support, contradiction, and context by
   the same relevance standard. Submit typed judgments with
   `submit_mission_evidence_qualifications`; inspect the batch again until its state is terminal.
3. Read the current frame identity and channel outcomes. Draft individually typed Claim Ledger
   candidates. Bind each candidate to exact observations or eligible measured-absence outcomes,
   including role and hypothesis target. Submit with `submit_mission_claims`, then inspect
   `get_mission_claims` for its render status. See [the claim example](examples/claim-ledger.md).
4. Read `get_mission_analysis`. Render only current permitted claims. If it returns a Gap Report,
   show failed gates, attempted probes, safe partial observations, and the smallest next probe.
   Call `generate_mission_artifact` only when a persistent report was requested.

An uploaded, purchased, or otherwise external dataset without mission-scoped provenance and
qualification has `CONTEXT_ONLY` status. It can shape a falsifiable question; it cannot supply a
Market verdict. Check unknown assumptions and contradictory evidence before recommending action.

Completion criterion: every rendered strategic statement has a current-frame Claim Ledger identity,
evidence binding, limitation, and condition that would change it; otherwise return the Gap Report.
