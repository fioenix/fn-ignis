"""Every watchlist tool reads and writes the caller's store (Spec 016).

The caller-storage middleware scopes a tool by its name or by a mission or workspace argument.
`save_watchlist` carries `workspace_id`, but `get_watchlist` and `start_watchlist_run` carry only
`watchlist_id`, so they used to reach the global store and could not find a watchlist that
`save_watchlist` had just written to the caller's.
"""
import pytest

from ignis.infrastructure.caller_storage import current_caller_storage
from tests.unit.test_caller_root_startup_folder import _consumer


@pytest.mark.asyncio
@pytest.mark.parametrize('name,arguments', [
    ('save_watchlist', {'workspace_id': 'w', 'name': 'n', 'definition': {}}),
    ('save_watchlist', {'watchlist_id': 'x', 'name': 'n', 'definition': {}}),
    ('set_watchlist_listening_plan', {'watchlist_id': 'x', 'goal': 'Track.', 'period_kind': 'week', 'snapshots_per_period': 3}),
    ('get_watchlist', {'watchlist_id': 'x'}),
    ('start_watchlist_run', {'watchlist_id': 'x', 'allowed_resources': [], 'authority_boundary': {}}),
    ('get_watchlist_period_snapshot', {'watchlist_id': 'x', 'period_kind': 'week'}),
])
async def test_watchlist_tools_run_in_the_caller_store(tmp_path, monkeypatch, name, arguments):
    monkeypatch.delenv('IGNIS_CALLER_ROOT', raising=False)
    monkeypatch.chdir(tmp_path)
    middleware, context, dispatch, calls = _consumer()
    context.message.name, context.message.arguments = name, arguments
    result = await middleware.on_call_tool(context, dispatch)
    assert result == {'selected_root': tmp_path}, f'{name} ran outside the caller store'
    assert calls == ['compose', 'runtime', 'dispatch']
    assert current_caller_storage.get() is None
