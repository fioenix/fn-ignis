# Bounded Follow-up Contract

**Status**: T076 bounded MCP implementation has scoped engineering verification through actual stdio on SQLite and PostgreSQL, using synthetic private capability providers and offline connectors. The public tool accepts exactly the four arguments below; framework-injected context is not a public argument. Held source/session permission remains an independent requirement, and execution fails closed when its provider is missing; real provider integration is not established by these tests. Root measured 262 passing offline tests and 19 passing native PostgreSQL companion tests, with no failures, errors or skips in either scoped gate. Delegated PO accepted T076 within this scoped synthetic engineering verification. T077 child-result projection, T078 viewer integration and T079 real-client UAT remain pending. This execution capability is separate from the read-only viewer and recording tool.

`execute_mission_follow_up(mission_id, follow_up_work_id, expected_research_epoch, idempotency_key)` admits one already assigned gap-linked follow-up, then uses existing deterministic collection on a new child mission. No caller-supplied unrestricted query list or credential is accepted at execution time.

Before creating a child or contacting any connector, validate:

1. Authorized selected parent, matching recorded gap/work and explicit still-valid research assignment.
2. Exact epoch/version, compatible manifest/Brief and admitted input revisions.
3. Query/source scope within the recorded assignment; existing session/token authorization remains separately required.
4. Remaining deadline, stop conditions and cumulative quota/cost allowance, including unresolved reservations across earlier children.
5. No terminal research, requested cancellation, exhausted authority or new credential/source/Brief requirement. Such cases return blocked/authority-required with zero probes.

Atomically create the child identity, narrowed immutable manifest, parent relationship and conservative quota reservation. Idempotency/CAS permits one admission across racing calls; retries identify the same child. The child's execute path retains the existing writer lock and terminal lifecycle, masking and connector isolation. Parent COMPLETED is not reset. The follow-up tool never borrows viewing capability as execution authority.

Return child mission/run, parent work/gap/assignment, admitted/refused/terminal status, safe channel outcomes and result references. Failure/cancellation/partial data remain visible; no automatic retry or fresh child on uncertainty. Crash recovery must reconcile the existing child/writer/reservation, not silently rerun an uncertain probe or release uncertain budget.

Subsequent host qualification, cross-check and claim submission target the child's actual canonical frame using existing tools. Host handoff references the child result; synthesis shows the changed finding and its exact child scope. A child PERMITTED claim is never mislabeled as a parent PERMITTED claim. Inspecting parent and child does not create a composite frame. A changed research question follows existing market-revision/authority rules, not this same-question follow-up shortcut.

Acceptance traces a real gap → admitted work → child evidence/outcomes → qualification/counterevidence → revised finding/claim-or-gap. Also exercise concurrent duplicate admission, source/scope/epoch mismatch, exhausted quota, cancellation, expiry and process interruption. Assert unauthorized cases perform zero connector calls and no fabricated current permission.
