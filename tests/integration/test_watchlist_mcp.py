"""T007: save_watchlist, get_watchlist and start_watchlist_run in their contract shape (Spec 016, US1)."""

import json
from uuid import uuid4

import pytest
import pytest_asyncio

from ignis.application.use_cases.create_research_workspace import CreateResearchWorkspaceUseCase
from ignis.infrastructure.persistence.workspace_repository import WorkspaceRepository
from ignis.interfaces.mcp import server as mcp_server

pytestmark = pytest.mark.asyncio

AUTHORITY = {"public_http": True, "official_api": True, "browser_session": False, "paid_quota": False}


def definition(*keywords, brands=None):
    return {"topics": [{
        "name": "Matcha drinks",
        "categories": ["đồ uống"],
        "keywords": list(keywords or ("matcha latte", "trà xanh")),
        "brands": brands if brands is not None else [
            {"platform": "tiktok", "account": "@BrandX", "declared_name": "Brand X"},
        ],
    }, {
        "name": "Cat litter",
        "keywords": ["cát vệ sinh mèo", "matcha latte"],
        "brands": [{"platform": "tiktok", "account": "brandx", "declared_name": "Brand X"}],
    }]}


@pytest_asyncio.fixture
async def tools(repository_case, tmp_path, monkeypatch):
    store = WorkspaceRepository(repository=repository_case.repository)
    creator = CreateResearchWorkspaceUseCase(store=store)
    root = tmp_path / "workspace"
    root.mkdir()
    workspace = await creator.confirm(await creator.propose(root, "Listening"), confirmation=True)
    components = {"repository": repository_case.repository, "workspace_store": store}
    from ignis.application.use_cases.create_attention_mission import CreateAttentionMissionUseCase
    components["create_attention_mission_use_case"] = CreateAttentionMissionUseCase(repository_case.repository, store)
    monkeypatch.setattr(mcp_server, "get_components", lambda: components)
    return str(workspace.workspace_id), repository_case.repository


async def call(handler, **kwargs):
    return json.loads(await getattr(mcp_server, handler)(**kwargs))


async def test_save_creates_revises_and_keeps_unchanged(tools):
    workspace, _ = tools
    created = await call("handle_save_watchlist", workspace_id=workspace, name="Matcha", definition=definition())
    assert created["status"] == "CREATED" and created["version"] == 1 and len(created["definition_digest"]) == 64
    watchlist = created["watchlist_id"]
    same = await call("handle_save_watchlist", workspace_id=workspace, name="matcha", definition=definition(),
                      watchlist_id=watchlist)
    assert same["status"] == "UNCHANGED" and same["version"] == 1
    revised = await call("handle_save_watchlist", workspace_id=workspace, name="Matcha",
                         definition=definition("matcha latte"), watchlist_id=watchlist)
    assert revised["status"] == "VERSION_ADDED" and revised["version"] == 2


@pytest.mark.parametrize("change,reason", [
    ({"definition": {"topics": []}}, "NO_TOPICS"),
    ({"workspace_id": str(uuid4())}, "WORKSPACE_SCOPE"),
    ({"name": " "}, "INVALID_DEFINITION"),
])
async def test_save_refusals(tools, change, reason):
    workspace, _ = tools
    request = {"workspace_id": workspace, "name": "Matcha", "definition": definition(), **change}
    refused = await call("handle_save_watchlist", **request)
    assert refused["status"] in {"INVALID", "BLOCKED"} and refused["reason_code"] == reason


async def test_save_refuses_taken_name_unknown_id_and_mismatches(tools):
    workspace, _ = tools
    first = await call("handle_save_watchlist", workspace_id=workspace, name="Matcha", definition=definition())
    taken = await call("handle_save_watchlist", workspace_id=workspace, name="MATCHA", definition=definition())
    assert taken["reason_code"] == "DUPLICATE_NAME"
    unknown = await call("handle_save_watchlist", workspace_id=workspace, name="Matcha", definition=definition(),
                         watchlist_id=str(uuid4()))
    assert unknown["status"] == "NOT_FOUND"
    renamed = await call("handle_save_watchlist", workspace_id=workspace, name="Other", definition=definition(),
                         watchlist_id=first["watchlist_id"])
    assert renamed["reason_code"] == "NAME_MISMATCH"


async def test_get_lists_versions_and_runs_without_observations(tools):
    workspace, _ = tools
    saved = await call("handle_save_watchlist", workspace_id=workspace, name="Matcha", definition=definition())
    read = await call("handle_get_watchlist", watchlist_id=saved["watchlist_id"])
    assert read["name"] == "Matcha" and read["workspace_id"] == workspace
    assert [v["version"] for v in read["versions"]] == [1]
    assert read["versions"][0]["definition"]["topics"][0]["brands"][0]["account"] == "brandx"
    assert read["runs"] == []
    assert (await call("handle_get_watchlist", watchlist_id=str(uuid4())))["status"] == "NOT_FOUND"
    assert (await call("handle_get_watchlist", watchlist_id="not-a-uuid"))["status"] == "INVALID"


async def test_run_is_an_attention_mission_on_the_current_version_with_brands_declared(tools):
    workspace, repository = tools
    saved = await call("handle_save_watchlist", workspace_id=workspace, name="Matcha", definition=definition())
    await call("handle_save_watchlist", workspace_id=workspace, name="Matcha",
               definition=definition("matcha latte"), watchlist_id=saved["watchlist_id"])
    run = await call("handle_start_watchlist_run", watchlist_id=saved["watchlist_id"],
                     allowed_resources=["youtube", "tiktok_search"], authority_boundary=AUTHORITY)
    assert run["status"] == "CREATED" and run["version"] == 2
    mission = await repository.get_mission(run["mission_id"])
    assert mission.surface == "ATTENTION" and str(mission.workspace_id) == workspace
    # Keywords of every topic, then brands by declared name, each once.
    assert mission.keywords == ["matcha latte", "cát vệ sinh mèo", "Brand X"]
    declared = await repository.list_mission_declared_accounts(mission.id)
    assert [(a.platform, a.account_key, a.declared_name) for a in declared] == [("tiktok", "brandx", "Brand X")]
    assert run["declared_accounts_status"] == "RECORDED"
    read = await call("handle_get_watchlist", watchlist_id=saved["watchlist_id"])
    assert [(r["mission_id"], r["version"]) for r in read["runs"]] == [(run["mission_id"], 2)]
    assert run["next_step"].startswith("Call execute_mission_ingress")


async def test_run_refuses_unknown_watchlist_and_missing_authority(tools):
    workspace, _ = tools
    unknown = await call("handle_start_watchlist_run", watchlist_id=str(uuid4()),
                         allowed_resources=["youtube"], authority_boundary=AUTHORITY)
    assert unknown["status"] == "NOT_FOUND"
    saved = await call("handle_save_watchlist", workspace_id=workspace, name="Matcha", definition=definition())
    missing = await call("handle_start_watchlist_run", watchlist_id=saved["watchlist_id"],
                         allowed_resources=["youtube"], authority_boundary="yes")
    assert missing["status"] == "INVALID"
    read = await call("handle_get_watchlist", watchlist_id=saved["watchlist_id"])
    assert read["runs"] == []
