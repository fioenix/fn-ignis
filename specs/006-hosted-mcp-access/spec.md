# Feature Specification: Dual-Mode MCP Access

**Feature Directory**: `specs/006-hosted-mcp-access`
**Created**: 2026-09-13
**Status**: Draft
**Input**: Preserve local open-source MCP access while adding a hosted MCP service for non-technical
users, initially supporting Claude Desktop, Claude Code, and Codex with Google OAuth.

---

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Connect to Hosted Ignis Without Local Setup (Priority: P1)

As a non-technical team member, I want to add a hosted Ignis connector to my supported AI client,
sign in with Google, and use the approved research tools without installing Python, running Docker,
or managing database credentials.

**Why this priority**: The hosted service has no user value unless a team member can connect and
complete a real Ignis task from the clients the pilot team already uses.

**Independent Test**: Invite one authorized pilot member, connect from each supported client, and
execute one read operation and one member-permitted mission operation without any local Ignis
runtime.

**Acceptance Scenarios**:

1. **Given** an invited member using Claude Desktop, **When** they add the hosted connector and
   complete Google sign-in, **Then** they can discover and invoke the member-visible Ignis tools.
2. **Given** an invited member using Claude Code, **When** they add the same hosted endpoint and
   complete Google sign-in, **Then** they can invoke the same member-visible tool contract.
3. **Given** an invited member using Codex, **When** they add the same hosted endpoint and complete
   Google sign-in, **Then** they can invoke the same member-visible tool contract.
4. **Given** a Google account that has not been invited, **When** it completes identity-provider
   authentication, **Then** Ignis refuses workspace access and records the denied attempt without
   disclosing workspace data.

---

### User Story 2 - Keep the Open-Source Local Experience (Priority: P1)

As a self-hosted operator, I want the existing local MCP server to remain available over standard
input/output with zero-configuration SQLite so that the open-source product does not depend on the
hosted service, a cloud account, or Google authentication.

**Why this priority**: Hosted convenience is an additional delivery mode, not a replacement for the
open-source product promise.

**Independent Test**: Bootstrap a clean local checkout without hosted-service or Google OAuth
configuration and invoke the local MCP tool catalog from a supported local client.

**Acceptance Scenarios**:

1. **Given** a clean open-source checkout, **When** bootstrap completes, **Then** the local MCP
   server runs over standard input/output against SQLite without contacting the hosted control
   plane.
2. **Given** hosted-service authentication is unavailable, **When** an operator uses local mode,
   **Then** all locally supported tools remain usable under the existing self-hosted trust model.
3. **Given** a tool available in both delivery modes, **When** equivalent inputs and evidence are
   supplied, **Then** both modes apply the same domain and scoring rules.

---

### User Story 3 - Share One Pilot Workspace With Individual Accountability (Priority: P2)

As the pilot owner, I want invited members to share one FINOLABS workspace while every action is
attributed to an individual identity, so collaboration is immediate without losing revocation,
authorization, or auditability.

**Why this priority**: A shared token would be faster to distribute but would make misuse,
revocation, and pilot learning impossible to attribute to a person.

**Independent Test**: Have two invited members use different clients to work with the same mission,
then verify shared visibility, distinct actor attribution, and independent revocation.

**Acceptance Scenarios**:

1. **Given** two active workspace members, **When** one creates a mission, **Then** the other can
   read it according to the shared-workspace policy.
2. **Given** two members invoke the same tool, **When** the audit trail is inspected, **Then** each
   invocation is attributed to the correct member and client.
3. **Given** one member is revoked, **When** that member retries with an existing session, **Then**
   access is refused while other members remain unaffected.
4. **Given** a member attempts an administrator-only operation, **When** authorization is checked,
   **Then** the operation is refused without changing shared state.

---

### User Story 4 - Receive Hosted Artifacts That Can Be Opened Remotely (Priority: P3)

As a hosted user, I want generated reports to open from my client without access to the server's
filesystem, while keeping report access private to authorized workspace members.

**Why this priority**: Returning a server-local path is unusable for a remote client and would make
the hosted experience incomplete.

**Independent Test**: Generate a report from each supported client, open the returned location from
a separate device, and verify that unauthorized or expired access is refused.

**Acceptance Scenarios**:

1. **Given** an authorized member requests an artifact, **When** generation succeeds, **Then** the
   response contains a time-limited remote location rather than a server-local file path.
2. **Given** an artifact link has expired or its requester is unauthorized, **When** the content is
   requested, **Then** access is refused without revealing the artifact.
3. **Given** a self-hosted local user requests the same artifact, **When** local mode is active,
   **Then** the existing local-file delivery remains available.

---

### User Story 5 - Operate the Pilot Without Silent Partial Readiness (Priority: P3)

As the service operator, I want the hosted endpoint to refuse traffic when its identity, storage,
or evidence schema is not ready, so a successful deployment label cannot conceal an unusable or
unsafe service.

**Why this priority**: This repository has previously produced correct-looking status from the
wrong surface; the hosted service must prove readiness from the dependencies that own the result.

**Independent Test**: Start the service against healthy dependencies and against each deliberately
broken prerequisite, then verify that only the healthy state accepts MCP traffic.

**Acceptance Scenarios**:

1. **Given** identity storage, workspace membership, and the evidence schema are ready, **When** the
   readiness surface is queried, **Then** it reports ready and authenticated MCP traffic is
   accepted.
2. **Given** any required dependency is absent or incompatible, **When** the service starts or
   retries initialization, **Then** readiness remains closed and no MCP tool can mutate data.
3. **Given** the process is alive but a required dependency is unavailable, **When** health and
   readiness are queried, **Then** liveness and readiness report different states.

### Edge Cases

- A member starts Google authorization in one client and completes it after the service restarts.
- One person connects through more than one supported client at the same time.
- Google returns an authenticated account whose email is unverified, changed, or no longer matches
  the invitation; authorization uses the provider's stable subject and current membership state,
  not email alone.
- A previously valid member is revoked while an access token remains unexpired.
- An OAuth token has a valid signature but the wrong audience, resource, issuer, or requested scope.
- The identity provider succeeds while workspace membership storage is unavailable.
- A member calls an administrator-only, credential-management, or browser-session tool.
- A hosted connector requires a browser runtime that is intentionally absent from the service.
- Artifact generation succeeds but remote storage fails, or an artifact link expires while a user
  is viewing it.
- A cold service instance starts during client connection or authorization callback handling.
- The hosted runtime is deployed before the production evidence migration has been verified.
- Local mode is started without any hosted-service or Google OAuth configuration.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Ignis MUST support two explicit MCP delivery modes: local standard input/output for
  open-source self-hosting and authenticated remote HTTP for the hosted service.
- **FR-002**: Local mode MUST remain operable without the hosted service, hosted credentials, a
  cloud account, or a network database.
- **FR-003**: The hosted mode MUST expose one remote MCP endpoint compatible with Claude Desktop,
  Claude Code, and Codex.
- **FR-004**: Tools shared by local and hosted modes MUST use one domain implementation and one
  tool contract rather than maintaining transport-specific business logic.
- **FR-005**: Google OAuth MUST be the first hosted identity provider.
- **FR-006**: Successful identity-provider authentication MUST NOT grant access unless the Google
  identity belongs to an active, explicitly invited workspace member.
- **FR-007**: The pilot MUST operate as one shared FINOLABS workspace. It MUST NOT claim data
  isolation between pilot members.
- **FR-008**: Every hosted request MUST be evaluated against current workspace membership even when
  the presented access token has not expired.
- **FR-009**: Hosted authorization MUST distinguish at least member and administrator capabilities.
- **FR-010**: The hosted tool catalog MUST classify every tool as member-visible,
  administrator-only, or unavailable in hosted mode before the service accepts pilot users.
- **FR-011**: Members MUST NOT be able to change connector credentials, global runtime
  configuration, access policy, or other administrator-owned state.
- **FR-012**: Browser-session authentication and other capabilities unavailable in the hosted
  runtime MUST fail explicitly and MUST NOT be reported as healthy or available.
- **FR-013**: Every hosted tool invocation MUST record the workspace, stable member identity,
  client identity when available, tool name, start time, outcome, duration, and a correlation ID.
- **FR-014**: Audit records MUST exclude access tokens, authorization codes, connector secrets, and
  raw credential payloads.
- **FR-015**: Revoking one member MUST block that member without rotating credentials or disrupting
  other members.
- **FR-016**: Authorization sessions, client registrations, and signing identity MUST survive
  normal process restarts without requiring every member to reconnect.
- **FR-017**: Hosted authentication MUST validate token issuer, audience/resource, expiry, and
  required scopes and MUST fail closed when validation cannot be completed.
- **FR-018**: Hosted artifacts MUST be delivered through access-controlled, expiring remote
  locations. Server-local paths MUST NOT be returned as usable hosted artifacts.
- **FR-019**: Local artifact generation MUST retain the existing self-hosted local-file behavior.
- **FR-020**: The service MUST expose distinct liveness and readiness outcomes; liveness MUST NOT be
  presented as proof that identity, storage, and evidence dependencies are ready.
- **FR-021**: Hosted MCP traffic MUST remain closed when authentication state, workspace membership,
  required database schema, or the production evidence cutover is incomplete.
- **FR-022**: Hosted deployment MUST keep secrets out of repository files, client configuration,
  user-visible errors, and audit payloads.
- **FR-023**: The hosted service MUST operate without relying on durable files on its compute
  instance.
- **FR-024**: The hosted service MUST expose usage measurements sufficient to attribute tool calls,
  connector calls, failures, and cost-driving work to a member and workspace.
- **FR-025**: The pilot MUST use a provider-portable application contract so changing compute or
  artifact-storage vendors does not change the MCP tool contract or member identity.
- **FR-026**: Activating hosted runtime against the production corpus MUST depend on the production
  source/observation migration completing with its canonical verifier status, not merely on schema
  files being present.

### Key Entities

- **Workspace**: The collaboration and authorization boundary. The pilot has exactly one shared
  FINOLABS workspace, while the entity remains explicit so a future SaaS release can add more
  workspaces without redefining member identity.
- **Workspace Member**: An invited Google identity, its stable provider subject, current status,
  role, invitation details, and revocation state.
- **Authorization Session**: A client authorization grant and its lifecycle. It is separate from
  connector credentials used to collect market data.
- **Tool Policy**: The hosted-mode classification and minimum role for each MCP tool.
- **Invocation Audit**: Immutable attribution and outcome data for one hosted tool invocation,
  excluding secrets and raw credentials.
- **Hosted Artifact**: A generated report owned by the workspace, with access policy, expiry, and a
  remote retrieval location.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: An invited first-time pilot member can connect and complete one Ignis research action
  from each of Claude Desktop, Claude Code, and Codex in no more than five minutes per client,
  without installing Ignis locally.
- **SC-002**: All three supported clients pass the same acceptance journey: authenticate, discover
  permitted tools, execute one read action, execute one member-permitted mission action, and receive
  the result.
- **SC-003**: In an authorization test set covering unauthenticated, uninvited, revoked, member, and
  administrator identities, 100% of requests receive the expected allow or deny outcome.
- **SC-004**: 100% of hosted tool invocations in the pilot acceptance run have an audit record with
  the correct member, workspace, tool, outcome, and correlation ID, with zero secrets present.
- **SC-005**: Revoked members lose access within 60 seconds without affecting another active
  member's session.
- **SC-006**: A normal service restart preserves active client authorization; no invited member must
  reconnect solely because compute restarted.
- **SC-007**: When the service is warm, 95% of pilot connection and tool-discovery attempts expose
  the permitted catalog within five seconds. Cold-start behavior is measured and reported
  separately rather than included silently.
- **SC-008**: Every deliberately broken readiness prerequisite refuses MCP traffic and leaves the
  shared corpus unchanged.
- **SC-009**: Every hosted artifact in the acceptance run opens from a remote client while
  authorized, and every expired or unauthorized retrieval attempt is refused.
- **SC-010**: The existing local bootstrap and MCP acceptance journey succeeds without hosted
  configuration, demonstrating that hosted delivery did not become a dependency of open-source
  mode.
- **SC-011**: Pilot compute and artifact-delivery infrastructure remains at or below USD 10 per
  month under the measured pilot workload, excluding the existing database, domain registration,
  and third-party connector quotas.

## Assumptions

- Pilot members have Google accounts and can complete browser-based OAuth authorization.
- Membership is invitation-only; successful Google authentication does not create an active member
  automatically.
- One shared workspace is acceptable for the pilot. Per-member data isolation, customer-created
  workspaces, billing, subscriptions, and self-service organization administration are future SaaS
  scope.
- The initial hosted runtime supports HTTP-capable connectors. Operator-side browser connectors
  remain part of local self-hosted mode until a separate remote-browser design is approved.
- The existing production PostgreSQL corpus remains the system of record for hosted research data.
- Hosted runtime activation waits for the source/observation production cutover to return
  `VERIFIED` against a baseline generated from the exact quiesced production snapshot.
- The current 39-tool catalog is a starting inventory, not an authorization decision; every tool
  must be classified before pilot access opens.
- Compute placement, artifact storage, and cost controls belong to the implementation plan. The
  requirements intentionally keep the client-facing contract portable across providers.

## Out of Scope

- Multi-workspace tenancy and data isolation between paying customers.
- Billing, subscriptions, usage-based charging, plans, and customer self-service signup.
- A web administration console; the pilot only requires a controlled way to invite, role, and
  revoke members.
- Porting the application to an edge-isolate runtime.
- Running interactive browser-login connectors inside the hosted service.
- Changing Opportunity Index or source/observation semantics.
- Shipping or activating the hosted service as part of this specification-only change.
