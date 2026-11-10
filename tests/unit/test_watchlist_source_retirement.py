"""Spec 022 reduces only new watchlist run authority, never stored history."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from tests.unit.test_mission_manifest import _manifest
from tests.unit.test_source_retirement import RETIRED


@pytest.mark.asyncio
@pytest.mark.parametrize('resources', [('youtube', 'reels'), ('reels', 'google')])
async def test_watchlist_reduces_new_run_without_rewriting_old_authority(monkeypatch, resources):
    from ignis.application.use_cases import watchlists
    from ignis.domain.research_workspace import MissionOutputType

    watchlist = SimpleNamespace(id=str(uuid4()), name='Existing list', workspace_id=str(uuid4()),
                                current=SimpleNamespace(version=1, definition=object()))
    mission = SimpleNamespace(id=uuid4(), shortcode='VN-NEW', keywords=['tea'])
    repo = SimpleNamespace(get_watchlist=AsyncMock(return_value=watchlist), record_watchlist_run=AsyncMock())
    create = SimpleNamespace(execute=AsyncMock(return_value=mission))
    monkeypatch.setattr(watchlists, 'run_keywords', lambda d: ['tea'])
    monkeypatch.setattr(watchlists, 'run_brands', lambda d: [])
    monkeypatch.setattr(watchlists.SetMissionDeclaredAccountsUseCase, 'execute', AsyncMock(return_value={}))
    authority = {'allowed_resources': list(resources), 'authority_boundary': {'public_http': True}}
    original = json.loads(json.dumps(authority))
    seen = []

    def build(payload):
        seen.append(payload['allowed_resources'])
        return _manifest(required_channels=tuple(payload['allowed_resources']), optional_channels=(),
                         output_type=MissionOutputType.ATTENTION_REPORT)

    result = await watchlists.StartWatchlistRunUseCase(repo, Mock(), create).execute(watchlist.id, authority, build)
    assert authority == original
    assert result['retired_resources'] == [
        {'surface': surface, 'reason_code': 'SURFACE_RETIRED'} for surface in resources if surface in RETIRED
    ]
    if 'youtube' in resources:
        assert result['status'] == 'CREATED'
        assert seen == [['youtube']]
        assert create.execute.await_args.kwargs['manifest'].allowed_resources == ('youtube',)
        repo.record_watchlist_run.assert_awaited_once()
    else:
        assert result['status'] == 'BLOCKED' and result['reason_code'] == 'SURFACE_RETIRED'
        assert not seen
        create.execute.assert_not_awaited()
        repo.record_watchlist_run.assert_not_awaited()
