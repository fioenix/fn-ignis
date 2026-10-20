"""Native protocol roots must bind caller storage without changing public tool inputs."""
import json
import os
import sys
from fastmcp.client.transports import StdioTransport
from pathlib import Path
import pytest
from fastmcp import Client
from ignis.interfaces.mcp import server
import ignis.config as config


def native_client(tmp_path, opened, client_roots=()):
    """Start the server in ``opened``, as an agent host does for the folder a session was opened in."""
    repository = Path(__file__).resolve().parents[2]
    isolated = tmp_path / 'native-isolated.env'
    isolated.write_text('DATABASE_URL=sqlite:///' + str(tmp_path / 'unselected.sqlite3') + '\nYOUTUBE_API_KEY=\nIGNIS_ENCRYPTION_KEY=\n')
    return Client(StdioTransport(command=sys.executable,
        args=['-m', 'ignis.interfaces.mcp.server'], cwd=str(opened), keep_alive=False,
        env={'IGNIS_ENV_FILE':str(isolated), 'IGNIS_ENV_ISOLATED':'1',
             'PYTHONPATH':os.pathsep.join((str(repository/'src'),str(repository)))},
        log_file=tmp_path/'native-stdio.log'), roots=[root.as_uri() for root in client_roots] or None,
        mode="legacy", timeout=20)


def payload(result):
    return json.loads(result.content[0].text)


@pytest.mark.asyncio
async def test_native_single_root_proposes_caller_fnignis_not_legacy_install_storage(tmp_path, monkeypatch):
    root = tmp_path / 'caller'
    root.mkdir()
    monkeypatch.setattr(server, '_COMPONENTS', None)
    monkeypatch.setattr(config.settings, 'DATABASE_URL', 'sqlite:///:memory:')
    async with native_client(tmp_path, root) as client:
        result = payload(await client.call_tool('propose_research_workspace',
            {'host_workspace':str(root),'research_name':'Synthetic native storage'}))
    assert result['proposed_path'] == str(root / '.fnignis/research/synthetic-native-storage')
    assert not (root / '.ignis').exists()
    assert not (tmp_path / "unselected.sqlite3").exists()


@pytest.mark.asyncio
async def test_native_client_roots_never_redirect_storage_away_from_the_opened_folder(tmp_path, monkeypatch):
    opened, other = tmp_path/'opened', tmp_path/'other'
    opened.mkdir()
    other.mkdir()
    monkeypatch.setattr(server, '_COMPONENTS', None)
    monkeypatch.setattr(config.settings, 'DATABASE_URL', 'sqlite:///:memory:')
    async with native_client(tmp_path, opened, [other, opened]) as client:
        result = payload(await client.call_tool('propose_research_workspace',
            {'host_workspace':str(opened),'research_name':'Synthetic native storage'}))
        refused = await client.call_tool('propose_research_workspace',
            {'host_workspace':str(other),'research_name':'Synthetic native storage'},raise_on_error=False)
    assert result['proposed_path'] == str(opened / '.fnignis/research/synthetic-native-storage')
    assert refused.is_error and 'CALLER_STORAGE_SCOPE_REFUSED' in refused.content[0].text
    assert server._COMPONENTS is None
    assert not (other/'.fnignis').exists()


@pytest.mark.asyncio
async def test_native_workspace_and_mission_survive_fresh_process_without_ingress(tmp_path):
    root = tmp_path/'caller'
    root.mkdir()
    async with native_client(tmp_path, root) as client:
        proposal = payload(await client.call_tool('propose_research_workspace',
            {'host_workspace':str(root),'research_name':'Offline retained evidence'}))
        workspace = payload(await client.call_tool('confirm_research_workspace',
            {'proposed_path':proposal['proposed_path'],'confirmation':True}))
        assert workspace['status'] == 'CREATED'
        mission = payload(await client.call_tool('create_attention_mission', {
            'workspace_id':workspace['workspace_id'], 'title':'Offline retained mission',
            'requested_outcome':'Read retained canonical evidence', 'allowed_resources':['youtube'],
            'authority_boundary':{'public_http':False,'official_api':False,'browser_session':False,'paid_quota':False},
            'output_type':'COLLECTION_FRAME','stop_conditions':['explicit completion'],
            'retention_policy':'Retain until explicit requester deletion', 'platforms':['youtube']}))
        assert mission['status'] == 'CREATED'
        first = payload(await client.call_tool('get_mission_analysis',{'mission_id':mission['mission_id']}))
    database=root/'.fnignis/canonical.sqlite3'
    manifest=Path(proposal['proposed_path'])/'workspace.json'
    assert database.is_file() and manifest.is_file()
    identity=(database.stat().st_dev,database.stat().st_ino)
    # Offline fixture uses the production repository to persist an explicit terminal result;
    # it does not represent a provider run or renew any source capability.
    from ignis.infrastructure.persistence.sqlite_repository import SqliteTrendRepository
    repository=SqliteTrendRepository(str(database))
    retained=await repository.get_mission(mission['mission_id'])
    retained.status='COMPLETED'
    retained.summary='Offline terminal fixture; no provider call'
    await repository.update_mission(retained)
    await repository.close()
    first['mission']['status']='COMPLETED'
    first['mission']['summary']=retained.summary
    async with native_client(tmp_path,root) as client:
        terminal=await client.call_tool('execute_mission_ingress',{'mission_id':mission['mission_id']},raise_on_error=False)
        terminal_payload=payload(terminal)
        assert terminal_payload['status']=='TERMINAL'
        assert terminal_payload['reason_code']=='MISSION_ALREADY_TERMINAL'
        assert terminal_payload['terminal_state']=='COMPLETED'
        second=payload(await client.call_tool('get_mission_analysis',{'mission_id':mission['mission_id']}))
        workspaces=payload(await client.call_tool('list_research_workspaces',{}))
        assert second == first
        assert workspace['workspace_id'] in json.dumps(workspaces)
        refusal=await client.call_tool('propose_research_workspace',
            {'host_workspace':str(tmp_path),'research_name':'Foreign'},raise_on_error=False)
        assert refusal.is_error and 'CALLER_STORAGE_SCOPE_REFUSED' in refusal.content[0].text
    assert (database.stat().st_dev,database.stat().st_ino)==identity
    assert not (tmp_path/'unselected.sqlite3').exists()


@pytest.mark.asyncio
async def test_native_symlink_and_root_replacement_refuse_without_writing_foreign(tmp_path):
    root=tmp_path/'caller'
    root.mkdir()
    foreign=tmp_path/'foreign'
    foreign.mkdir()
    (root/'.fnignis').symlink_to(foreign,target_is_directory=True)
    async with native_client(tmp_path,root) as client:
        result=await client.call_tool('propose_research_workspace',
            {'host_workspace':str(root),'research_name':'Refused'},raise_on_error=False)
        assert result.is_error and 'CALLER_STORAGE_SCOPE_REFUSED' in result.content[0].text
    assert list(foreign.iterdir())==[]
    (root/'.fnignis').unlink()
    async with native_client(tmp_path,root) as client:
        await client.call_tool('propose_research_workspace',{'host_workspace':str(root),'research_name':'Pinned'})
        root.rename(tmp_path/'original-caller')
        root.mkdir()
        result=await client.call_tool('list_research_workspaces',{},raise_on_error=False)
        assert result.is_error and 'ROOT_REQUIRED category=STARTUP_ROOT_CHANGED' in result.content[0].text
    assert list(root.iterdir())==[]


@pytest.mark.asyncio
@pytest.mark.parametrize('attack', ['journal_directory', 'plan_temporary'])
async def test_scoped_journal_writer_never_changes_foreign_symlink_target(tmp_path, attack):
    from datetime import datetime, timezone
    from uuid import uuid4
    from ignis.infrastructure.caller_storage import CallerStorageScope
    from ignis.infrastructure.persistence.sqlite_repository import SqliteTrendRepository
    from ignis.infrastructure.persistence.workspace_repository import WorkspaceRepository
    from ignis.application.ports.research_workspace_port import RunJournal
    from ignis.domain.research_workspace import ResearchWorkspace, JOURNAL_DIRNAME
    from fastmcp.exceptions import ToolError
    root=tmp_path/'caller'
    root.mkdir()
    scope=CallerStorageScope(root)
    repository=SqliteTrendRepository(str(scope.database))
    scope.guard_repository(repository)
    store=WorkspaceRepository(repository,path_guard=scope.check_path)
    workspace=ResearchWorkspace(workspace_id=uuid4(),slug='offline',name='Offline',
        root_path=root/'.fnignis/research/offline')
    workspace.root_path.mkdir(parents=True)
    foreign=tmp_path/'foreign'
    foreign.mkdir()
    try:
        if attack=='journal_directory':
            (workspace.root_path/JOURNAL_DIRNAME).symlink_to(foreign,target_is_directory=True)
            try:
                await store.allocate_run_journal(workspace,uuid4())
            except ToolError:
                pass
            assert list(foreign.iterdir())==[], 'Scoped writer created a journal outside caller root.'
        else:
            journal_path=workspace.root_path/'journal.json'
            journal_path.write_text('{}')
            target=foreign/'retained.txt'
            target.write_text('Foreign original')
            identity=(target.stat().st_dev,target.stat().st_ino)
            journal_path.with_suffix('.json.tmp').symlink_to(target)
            journal=RunJournal(run_id=uuid4(),mission_id=uuid4(),workspace_id=workspace.workspace_id,
                journal_path=journal_path,sequence=1,status='STARTED',started_at=datetime.now(timezone.utc))
            try:
                await store.record_collection_plan(journal,{'plan_digest':'a'*64})
            except ToolError:
                pass
            assert target.read_text()=='Foreign original', 'Scoped temporary writer overwrote foreign content.'
            assert (target.stat().st_dev,target.stat().st_ino)==identity
    finally:
        await repository.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('outcome', ['success', 'source_error', 'cancelled'])
async def test_finalization_scope_refusal_preserves_original_outcome_and_foreign_bytes(tmp_path, outcome):
    import asyncio
    from ignis.domain.entities import ResearchMission
    from ignis.domain.research_workspace import ResearchWorkspace
    from ignis.infrastructure.caller_storage import CallerStorageScope
    from ignis.infrastructure.persistence.sqlite_repository import SqliteTrendRepository
    from ignis.infrastructure.persistence.workspace_repository import WorkspaceRepository
    root=tmp_path/'caller'
    root.mkdir()
    scope=CallerStorageScope(root)
    repository=SqliteTrendRepository(str(scope.database))
    scope.guard_repository(repository)
    store=WorkspaceRepository(repository,path_guard=scope.check_path)
    workspace=ResearchWorkspace(slug='finalization',root_path=scope.directory/'research/finalization')
    workspace.root_path.mkdir(parents=True)
    await store.save_research_workspace(workspace)
    mission=ResearchMission(title='Offline finalization',keywords=['offline'],workspace_id=workspace.workspace_id)
    await repository.create_mission(mission)
    foreign=tmp_path/'foreign.txt'
    foreign.write_text('Foreign original bytes')
    identity=(foreign.stat().st_dev,foreign.stat().st_ino)
    original_error=RuntimeError('Original offline source failure')
    expected_cancel=[]
    async def run():
        async with store.mission_run(workspace,mission.id) as journal:
            if outcome=='success':
                mission.status='COMPLETED'
                await repository.update_mission(mission)
            journal.journal_path.unlink()
            journal.journal_path.symlink_to(foreign)
            if outcome=='source_error':
                raise original_error
            if outcome=='cancelled':
                asyncio.current_task().cancel('Original requested cancellation')
                try:
                    await asyncio.sleep(0)
                except asyncio.CancelledError as exc:
                    expected_cancel.append(exc.args)
                    raise
        return 'Original completed result'
    worker=asyncio.create_task(run())
    try:
        result=None
        raised=None
        try:
            result=await worker
        except BaseException as exc:
            raised=exc
        assert foreign.read_text()=='Foreign original bytes'
        assert (foreign.stat().st_dev,foreign.stat().st_ino)==identity
        assert await store.get_mission_writer_claim(mission.id) is None
        journals=await repository.list_run_journals(mission.id)
        assert len(journals)==1 and journals[0].status=='STARTED'
        if outcome=='success':
            assert raised is None, 'Scope refusal masked original successful execution.'
            assert result=='Original completed result'
            assert (await repository.get_mission(mission.id)).status=='COMPLETED'
        elif outcome=='source_error':
            assert raised is original_error, 'Scope refusal replaced the original source exception.'
        else:
            assert isinstance(raised,asyncio.CancelledError), 'Scope refusal replaced requested cancellation.'
            assert raised.args==expected_cancel[0]
            assert worker.cancelled()
    finally:
        await repository.close()
