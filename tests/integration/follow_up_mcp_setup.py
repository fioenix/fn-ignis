"""Canonical synthetic connector identity shared by pytest and native MCP fixtures."""

import json


def native_executor(repository, probe_file, *, entered=None, gate=None, cleanup_entered=None, cleanup_gate=None):
    """Actual accepted executor with synthetic offline ingress, never real source authority."""
    from pathlib import Path
    from ignis.application.use_cases.execute_mission import ExecuteMissionUseCase
    from ignis.infrastructure.connectors.registry import ConnectorPluginRegistry
    from ignis.infrastructure.persistence.workspace_repository import WorkspaceRepository
    from tests.integration.test_mission_follow_up import OfflinePlugin, EmptyClusterer, Ingress
    class NativeOfflinePlugin(OfflinePlugin):
        async def search_signals(self, keywords, geo, timeframe, attestation=None, **kwargs):
            path = Path(probe_file)
            calls = json.loads(path.read_text()) if path.exists() else []
            calls.append(list(keywords))
            path.write_text(json.dumps(calls))
            if entered is not None:
                entered.set()
            if gate is not None:
                import asyncio
                try:
                    await gate.wait()
                except asyncio.CancelledError:
                    if cleanup_entered is not None:
                        cleanup_entered.set()
                    if cleanup_gate is not None:
                        await cleanup_gate.wait()
                    raise
            if attestation is not None:
                for keyword in keywords:
                    attestation.executed(keyword)
            return []
    registry = ConnectorPluginRegistry(repository)
    registry.register(NativeOfflinePlugin(Ingress()))
    store = WorkspaceRepository(repository)
    executor = ExecuteMissionUseCase(repository, registry, EmptyClusterer(), store)
    return executor, registry, store
