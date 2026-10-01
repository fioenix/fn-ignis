"""Read one transaction-bound repository view using the existing row decoders."""

from contextlib import asynccontextmanager
from uuid import UUID

from ignis.application.ports.research_workspace_port import MissionEvidenceSnapshot


class SnapshotConnectionPool:
    """Pin nested read methods to the caller's read-only PostgreSQL transaction."""

    def __init__(self, connection):
        self._connection = connection

    @asynccontextmanager
    async def connection(self):
        yield self._connection


async def read_evidence_snapshot(reader, mission_id: UUID) -> MissionEvidenceSnapshot:
    return MissionEvidenceSnapshot(
        mission=await reader.get_mission(mission_id),
        manifest=await reader.get_mission_manifest(mission_id),
        brief=await reader.get_brief_revision_for_mission(mission_id),
        signals=tuple(await reader.get_mission_signals(mission_id)),
        qualifications=tuple(await reader.list_evidence_qualifications(mission_id)),
        outcomes=tuple(await reader.get_latest_completed_probe_outcomes(mission_id)),
        claims=tuple(await reader.list_mission_claims(mission_id, include_superseded=True)),
    )
