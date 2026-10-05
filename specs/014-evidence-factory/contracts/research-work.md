# Host Research Work Contract

**Status**: Additive MCP protocol design approved with the technical plan; not implemented and not a scheduler or provider integration.

`record_mission_research_work(mission_id, command)` accepts a typed discriminated command. All mutations require authorized host context, current expected revision/epoch, idempotency key and exact bounded mission scope. Unknown fields/operations are refused. The call records work; it never spawns a specialist, invokes a model, authenticates or collects.

| Command | Required payload and effect |
|---|---|
| `ASSIGN_RESEARCH` | Explicit host task reference, finite authority envelope and declared capability; creates a new research assignment/epoch. No grant inferred from viewing or free-form analysis policy. |
| `ASSIGN_WORK` | Assignment, question/expertise, known assignee, input bindings and dependencies; records bounded work. |
| `START_WORK` | Work/version/fence, actual execution receipt and provenance; admits start under valid authority. |
| `RECORD_ACTIVITY` | Work/fence, actual still-active receipt and finite freshness boundary; cannot revive a terminal work item. |
| `WAIT_WORK` / `RESUME_WORK` | Exact state version and recorded waiting/resumption reason. Resume is separately checked against remaining authority. |
| `SUBMIT_HANDOFF` | Version/fence, evidence/result references, limitations, open questions and optional finding revisions; commits result and lifecycle/event together. |
| `ACK_HANDOFF` | Consumer/version and accepted/rejected disposition, preserving dependency/input revision identity. |
| `END_WORK` | Completed, failed, cancelled, insufficient-evidence or interrupted disposition and inspectable safe reason. Completion without a result is not silently synthesized. |
| `REQUEST_CANCEL` / `ACK_STOP` | Distinct request and acknowledged-stop receipts; authority fenced immediately for new admissions. |
| `END_RESEARCH` | Explicit assignment terminal disposition and epoch fence; no future child work without a new explicit assignment. |

Command response includes applied/idempotent/refused disposition, immutable receipt/event references, current work/assignment version and safe reason. An identical retry returns the original disposition; changed payload under the same key is a conflict. Concurrent or obsolete results cannot overwrite current findings. Record a safe rejection reason rather than leaking rejected content.

Host-provided identity, start time or capability is `HOST_REPORTED`, not independently verified execution. Harness-recorded transaction facts are `HARNESS_OBSERVED`. Actual host agent delegation and overlapping execution must be demonstrated separately in SC-012; two fabricated start commands do not satisfy it. Sequential capability is honestly rendered as sequential work.

Finding payloads distinguish descriptive inference from strategic candidates, preserve counterevidence/alternatives and reference exact input revisions. No prompt/transcript/hidden reasoning is accepted. Typed safe fields plus sanitization apply before persistence/outward projection. Statements that require strategic permission remain gated by current-frame Claim Ledger; the viewer performs no semantic judging to grant that permission.

The host owns model authorization, execution and spending. Ignis enforces its explicit work/collection boundaries but does not report unmeasured token costs or claim to preempt a remote agent merely by recording cancellation. Pending cancellation/unknown execution remain visible until an actual stop receipt or authority boundary applies.
