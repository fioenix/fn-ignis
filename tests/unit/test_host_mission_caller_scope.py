"""A MISSION host search submits into the caller store it was prepared in (Spec 012).

The caller-storage middleware scopes a tool by its name or by a mission, workspace or watchlist
argument. `prepare_host_browser_search` carries `mission_id`, but `submit_host_browser_search`
carries only the request's ids, so it used to reach the global store, could not find the
mission's research workspace there and failed every live MISSION ingestion.
"""
from types import SimpleNamespace

import pytest

from ignis.infrastructure.caller_storage import current_caller_storage
from ignis.interfaces.mcp import server


class _Scope:
    def __init__(self, components):
        self.components = components

    def check(self):
        pass


class _Repository:
    async def get_mission(self, mission_id):
        return SimpleNamespace(id=mission_id)


class _Service:
    def __init__(self):
        self.submitted = []

    async def prepare_mission(self, executor, mission_id, host_task_ref, session_ref, lifetime, authorized):
        return {"request_id": "request", "mission_id": str(mission_id)}

    def mode(self, request_id, host_task_ref, session_ref):
        return "MISSION"

    async def submit_mission(self, executor, request_id, host_task_ref, session_ref):
        self.submitted.append((executor, current_caller_storage.get()))
        return {"status": "ACCEPTED"}


@pytest.fixture
def service(monkeypatch):
    fake = _Service()
    monkeypatch.setattr(server, "_host_browser_search_service", fake)
    monkeypatch.setattr(server, "_host_mission_scopes", {})
    monkeypatch.setattr(server, "_COMPONENTS", None)
    monkeypatch.setattr(server, "_init_components", lambda: {"execute_mission_use_case": "global"})
    return fake


async def _prepare(scope):
    token = current_caller_storage.set(scope)
    try:
        return await server.handle_prepare_host_browser_search(
            "task", "chrome", [], 20, 600, True, mode="MISSION", mission_id="mission")
    finally:
        current_caller_storage.reset(token)


@pytest.mark.asyncio
async def test_mission_submit_uses_the_store_it_was_prepared_in(service):
    scope = _Scope({"repository": _Repository(), "execute_mission_use_case": "caller"})
    assert (await _prepare(scope))["request_id"] == "request"

    receipt = await server.handle_submit_host_browser_search("request", "task", "chrome")

    assert receipt == {"status": "ACCEPTED"}
    assert service.submitted == [("caller", scope)], "the submission left the caller store"
    assert current_caller_storage.get() is None
    assert server._host_mission_scopes == {}


@pytest.mark.asyncio
async def test_mission_prepared_in_the_global_store_submits_there(service):
    server._COMPONENTS = {"repository": _Repository(), "execute_mission_use_case": "global"}
    request = await server.handle_prepare_host_browser_search(
        "task", "chrome", [], 20, 600, True, mode="MISSION", mission_id="mission")
    assert request["request_id"] == "request"

    await server.handle_submit_host_browser_search("request", "task", "chrome")

    assert service.submitted == [("global", None)]
