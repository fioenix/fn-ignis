# Workspace and Mission Contracts

These contracts describe the boundary between a host Agent and fn-ignis. Exact MCP tool names
and serialization wrappers are implementation details to be selected during task execution; the
semantics below are fixed by the feature specification.

## Workspace proposal

The proposal operation is read-only and MUST NOT create a manifest, database, journal, or child
directory.

```json
{
  "operation": "propose_workspace",
  "host_workspace": "/workspace/project",
  "research_name": "AI customer service",
  "proposed_path": "/workspace/project/.ignis/research/ai-customer-service",
  "requires_confirmation": true
}
```

The host workspace path is supplied by the Agent environment. The proposal MUST reject paths
outside that workspace and invalid or reserved slugs.

## Workspace confirmation

```json
{
  "operation": "confirm_workspace",
  "proposed_path": "/workspace/project/.ignis/research/ai-customer-service",
  "confirmation": true
}
```

The result identifies the workspace and its manifest status. Reuse is allowed for a matching
manifest and the workspace's logical record scope in the configured shared Ignis database.
Adoption of a non-empty folder without a manifest requires a separate explicit confirmation and
preserves unrelated files.

## Attention mission

```json
{
  "surface": "ATTENTION",
  "workspace_id": "workspace-uuid",
  "geo": "VN",
  "timeframe": "7d",
  "seed": "optional user query"
}
```

The result MUST include ranked topics or clusters, momentum/freshness signals, source coverage
or diversity, and evidence citations. It MUST NOT include an Opportunity Index.

## Market Brief confirmation

```json
{
  "surface": "MARKET",
  "workspace_id": "workspace-uuid",
  "parent_attention_mission_id": "optional-mission-uuid",
  "parent_cluster_id": "optional-cluster-uuid",
  "decision": "Should we test this product direction?",
  "target_user": "VN fashion retailers with ...",
  "problem": "...",
  "geo": "VN",
  "timeframe": "30d",
  "hypothesis": "...",
  "falsifiers": ["..."],
  "confirmed_by": "requester-identity"
}
```

The operation MUST reject incomplete fields, persist only the confirmed revision, and return a
new Market mission identity under the selected `workspace_id`. Draft Q&A messages are not part of
this contract and are not stored.

## Market revision

A revision references the earlier Market mission for lineage but creates a new immutable Brief
revision and mission. The new mission MUST run against its own Brief. Earlier Attention or Market
observations MAY be returned as context with their lineage, but MUST NOT be silently promoted to
supporting evidence.

## Analysis response boundary

Every analysis response MUST identify:

- the workspace and mission;
- the surface;
- the Brief revision when the surface is `MARKET`;
- channel status and evidence counts;
- citations or an explicit no-data/degraded status; and
- whether a value is Attention context, Market evidence, or a derived conclusion.

All records returned by the contract MUST belong to the requested `workspace_id`; a workspace
scope mismatch is an error, not an empty result.

The Opportunity Index field is valid only for `MARKET` responses.
