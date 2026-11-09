# Delivery Practices

Read this before substantial implementation, a TypeSafe judgment, or a material status report in this repository.

## TypeSafe Workflow Advisor

This policy applies only while working in this repository. Use the harness's existing
`typesafe-ai` skill for narrow semantic judgments in the agent's own workflow; read its
instructions and relevant live documentation before use. This is an instruction-level
integration, not an Ignis runtime feature. Keep shared skills, global harness configuration,
hooks, dependencies and connector behavior unchanged. If the skill is unavailable, disclose
that limitation and continue with ordinary source inspection and review.

### Conditional checkpoints

- **Task preflight:** when scope or optional context relevance is ambiguous, compare the
  approved outcome and scope with the proposed action; judge optional candidate excerpts.
  Include mandatory instructions, contracts and consumer dependencies regardless of ranking.
- **Failed correction:** when it is unclear whether a repair changed the failing behavior,
  compare the named acceptance invariant before and after. Follow the churn stop under Evidence-First Delivery;
  an advisory judgment cannot waive it.
- **Material status report:** when a completion or shipment claim needs semantic interpretation,
  compare that claim with observed evidence. Keep test-design acceptance, implementation
  verification, integration and shipment separate. Establish exact run/revision facts directly.

Use ordinary code and inspection for deterministic rules, counts, receipt checks and permissions.
Clear, small tasks need no additional inference; state a skipped semantic check briefly when
relevant. These checkpoints do not require a call on every command, turn or owner question.

### Request and response discipline

1. Prepare a bounded state: approved outcome, scope, proposed action and relevant evidence.
   Send only the fields the judgment needs and never cookies, tokens or secrets; the operator's
   user-scope TypeSafe data approval governs everything else. Use existing Keychain credential injection;
   never print credentials, write them into this repo or depend on a retired plugin's runner.
2. Batch independent questions over the same state. Use Choice for exclusive interpretations
   with an explicit insufficient-evidence option, Noul for a single yes/no condition, and Score
   for ordered degree rubrics. A later call requires changed evidence or a genuine dependency.
3. For claim checks use `SUPPORTED / CONTRADICTED / INSUFFICIENT`: missing supporting evidence
   is not affirmative contradiction. Unknown evidence is not permission. Confidence describes
   the answer distribution, not truth; evaluate thresholds on independent cases before adopting
   automatic routing. During this advisory setup, the agent reads the evidence and decides.
4. Preserve reviews and owner approval boundaries. A judgment cannot authorize external actions,
   remove mandatory context, accept a task, certify security or replace executed tests. On API
   failure, report that no judgment was obtained and continue ordinary inspection/review while
   retaining all safety restrictions; avoid polling or unbounded retries.
5. Retain only useful checkpoint metadata in `.handoff/`: model and question version, latency,
   token usage and the action taken. Reuse a result only while its state, questions and model
   policy remain unchanged. Evaluate total task latency, first-pass review gaps, repair rounds
   and false alerts; isolated API speed and prompt-development examples do not prove a speedup.

---

## Evidence-First Delivery

Apply these execution rules to work in this repository. Preserve approved product scope,
Spec Kit artifact ownership, review requirements and owner authority while reducing overhead.

- **Outcome before activity:** state the observable result and its acceptance evidence before
  substantial work. Name the authoritative checkout, revision and active spec; resolve conflicting
  sources before editing. Task counts are not a substitute for end-user progress.
- **Bounded steps:** give each step one behavior and an independently checkable result. Aim for
  2–5-minute actions inside larger tasks; split oversized bundles rather than adding ceremonies
  for each substep. Keep acceptance at the approved task boundary. Prefer an early working
  vertical slice within the approved dependency order; request a decision before resequencing
  that order or expanding scope. Accepted future-API tests remain test design, not a working UI.
- **Task-sized context:** read mandatory instructions completely, then retrieve relevant contracts,
  changed code and its consumers. Keep optional history and unrelated reports out of the working
  packet. When delegation is authorized, hand off that bounded packet, file ownership and exact
  verification targets; preserve other contributors' changes. Change model or effort settings
  only under applicable authority, not on an unmeasured assumption about speed.
- **Assertions before volume:** specify the failing invariant and a bad-behavior control before
  growing fixtures. Verify that relevant assertions reject the defect: exact counts rather than
  substring matches, source-observation identity rather than event ID alone, and specific failure
  reasons rather than generic nonempty text. A launch failure or absent target is not behavioral
  RED; distinguish test setup failures from failures of the intended implementation.
- **Churn stop:** after two independent corrections leave the same acceptance invariant failing,
  stop product edits before a third patch. Preserve the reproducer, map the authoritative state,
  update/revision path and stale consumers, and resume only with a coherent root-cause approach
  and a deterministic regression test. Retain independent review instead of bypassing it to save time.
- **Settlement, not polling:** use the host's supported long-job mechanism and work on independent
  tasks while it runs. Check status when the result is needed or an actionable event arrives.
  Retain one coherent evidence/ledger update per meaningful state change; consolidate repeated
  hashes, inventories and unchanged status notes. When nothing can proceed, report the actual
  blocker instead of looping. Owner decisions belong in direct questions, not hidden in files.
- **Observed state, not labels:** distinguish test-design acceptance, implementation verification,
  integration and shipment in every material status report. Verify the actual artifact/revision
  and freshly observed result. A checkout, installed-looking configuration or skill name alone
  does not prove a loaded integration; confirm harness discovery and actual execution when needed.
  State what was not checked. Missing evidence is unknown, not zero or affirmative disproof.
- **Safe evidence:** use dummy credentials for offline tests and prevent secret-bearing environment,
  headers, cookies and captured locals from entering test output. Sanitize diagnostics before
  retaining or sharing them; use explicitly authorized credentials only for live checks. A prior
  successful probe is neither blanket data-export permission nor proof of current readiness.
- **Measure the correction:** when investigating delivery speed, separate preparation, edits,
  verification, review/rework and handoff overhead. Account for overlapping waits and distinguish
  API time from total task time. Claim improvement only from comparable observed work, not demo
  latency or guessed provider behavior. Keep measurement proportional to the investigation.
