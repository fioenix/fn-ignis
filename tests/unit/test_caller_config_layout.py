"""Explicit caller configuration must select storage or refuse without installation fallback."""
from pathlib import Path
import pytest
from test_caller_storage_native import native_client, payload


@pytest.mark.asyncio
async def test_native_explicit_caller_sqlite_connection_wins_and_restarts_stably(tmp_path):
    root=tmp_path/'caller';root.mkdir();storage=root/'.fnignis';storage.mkdir()
    target=storage/'selected.sqlite3'
    config=storage/'.env';config.write_text('DATABASE_URL=sqlite:///'+str(target)+'\n');config.chmod(0o600)
    async with native_client(tmp_path,root) as client:
        proposal=payload(await client.call_tool('propose_research_workspace',
            {'host_workspace':str(root),'research_name':'Configured local store'}))
        workspace=payload(await client.call_tool('confirm_research_workspace',
            {'proposed_path':proposal['proposed_path'],'confirmation':True}))
        assert workspace['status']=='CREATED'
    assert target.is_file(), 'Caller connection was ignored in favor of default storage.'
    assert not (storage/'canonical.sqlite3').exists()
    async with native_client(tmp_path,root) as client:
        result=payload(await client.call_tool('list_research_workspaces',{}))
        assert workspace['workspace_id'] in str(result)
    assert not (tmp_path/'unselected.sqlite3').exists()


@pytest.mark.asyncio
async def test_native_invalid_caller_connection_refuses_without_fallback_or_secret_output(tmp_path):
    root=tmp_path/'caller';root.mkdir();storage=root/'.fnignis';storage.mkdir()
    config=storage/'.env';config.write_text('DATABASE_URL=unsupported://dummy-user:SECRET_CANARY@invalid/database\n');config.chmod(0o600)
    async with native_client(tmp_path,root) as client:
        result=await client.call_tool('propose_research_workspace',
            {'host_workspace':str(root),'research_name':'Refused config'},raise_on_error=False)
    assert result.is_error and 'CALLER_CONFIG_REFUSED' in result.content[0].text
    assert 'SECRET_CANARY' not in str(result)
    assert 'SECRET_CANARY' not in (tmp_path/'native-stdio.log').read_text()
    assert not (storage/'canonical.sqlite3').exists()
    assert not (tmp_path/'unselected.sqlite3').exists()


@pytest.mark.asyncio
async def test_native_changed_configuration_refuses_cached_backend(tmp_path):
    root=tmp_path/'caller';root.mkdir();storage=root/'.fnignis';storage.mkdir()
    config=storage/'.env';config.write_text('# Original\n');config.chmod(0o600)
    async with native_client(tmp_path,root) as client:
        proposal=payload(await client.call_tool('propose_research_workspace',
            {'host_workspace':str(root),'research_name':'Stable config'}))
        config.write_text('# Changed in place\n')
        result=await client.call_tool('confirm_research_workspace',
            {'proposed_path':proposal['proposed_path'],'confirmation':True},raise_on_error=False)
        assert result.is_error and 'CALLER_CONFIG_CHANGED' in result.content[0].text
    assert not (storage/'canonical.sqlite3').exists()


@pytest.mark.asyncio
async def test_native_failing_connection_never_creates_default_database(tmp_path):
    root=tmp_path/'caller';root.mkdir();storage=root/'.fnignis';storage.mkdir()
    target=storage/'not-a-database';target.mkdir()
    config=storage/'.env';config.write_text('DATABASE_URL=sqlite:///'+str(target)+'\n');config.chmod(0o600)
    async with native_client(tmp_path,root) as client:
        result=await client.call_tool('propose_research_workspace',
            {'host_workspace':str(root),'research_name':'Failed connection'},raise_on_error=False)
        assert result.is_error and 'CALLER_DATABASE_REFUSED' in result.content[0].text
    assert not (storage/'canonical.sqlite3').exists()


def test_layout_preserves_user_files_and_protects_generated_config(tmp_path):
    import subprocess
    from ignis.infrastructure.caller_storage import CallerStorageScope
    subprocess.run(['git','init','-q',str(tmp_path)],check=True)
    ignore=tmp_path/'.gitignore';ignore.write_bytes(b'# Owner bytes\n')
    scope=CallerStorageScope(tmp_path);scope.prepare_layout()
    assert ignore.read_bytes()==b'# Owner bytes\n/.fnignis/\n'
    assert (scope.config_path.stat().st_mode & 0o777)==0o600
    assert subprocess.run(['git','-C',str(tmp_path),'check-ignore','--quiet','--','.fnignis/.env']).returncode==0
    before=scope.config_path.read_bytes();scope.prepare_layout()
    assert scope.config_path.read_bytes()==before
    assert set(item.name for item in scope.directory.iterdir())=={'.env','.env.example'}
    assert 'YOUR_KEY' in (scope.directory/'.env.example').read_text()
    import logging
    logging.getLogger().removeHandler(scope.log_handler);scope.log_handler.close()


def test_tracked_config_refuses_setup_without_rewriting_user_files(tmp_path):
    import subprocess
    from fastmcp.exceptions import ToolError
    from ignis.infrastructure.caller_storage import CallerStorageScope
    subprocess.run(['git','init','-q',str(tmp_path)],check=True)
    storage=tmp_path/'.fnignis';storage.mkdir();config=storage/'.env'
    config.write_text('# Owner config\n');config.chmod(0o600)
    subprocess.run(['git','-C',str(tmp_path),'add','.fnignis/.env'],check=True)
    scope=CallerStorageScope(tmp_path)
    with pytest.raises(ToolError,match='^CALLER_CONFIG_TRACKED$'):scope.prepare_layout()
    assert config.read_text()=='# Owner config\n' and not (tmp_path/'.gitignore').exists()


@pytest.mark.asyncio
async def test_offline_postgres_pool_failure_is_sanitized_without_sqlite_fallback(tmp_path,monkeypatch):
    from fastmcp.exceptions import ToolError
    from ignis.infrastructure.caller_storage import CallerStorageScope
    from ignis.infrastructure.persistence import create_repository
    from ignis.infrastructure.persistence import postgres_repository
    storage=tmp_path/'.fnignis';storage.mkdir();config=storage/'.env'
    config.write_text('DATABASE_URL=postgresql://dummy:SECRET_CANARY@invalid/db\nDB_MIN_POOL_SIZE=2\nDB_MAX_POOL_SIZE=4\n');config.chmod(0o600)
    scope=CallerStorageScope(tmp_path)
    closed=[]
    class OfflinePool:
        def __init__(self,**kwargs):
            assert kwargs['min_size']==2 and kwargs['max_size']==4
        async def open(self):pass
        async def close(self):closed.append(True)
    monkeypatch.setattr(postgres_repository,'AsyncConnectionPool',OfflinePool)
    repository=create_repository(scope.configuration.DATABASE_URL.get_secret_value(),
        min_pool_size=2,max_pool_size=4)
    async def failed(pool):raise RuntimeError(repository._dsn)
    monkeypatch.setattr(repository,'_refuse_an_unbackfilled_corpus',failed)
    scope.guard_repository(repository)
    for attempt in range(2):
        with pytest.raises(ToolError,match='^CALLER_DATABASE_REFUSED$') as error:await repository._get_pool()
        assert 'SECRET_CANARY' not in str(error.value)
    assert closed==[True,True] and repository._pool is None
    assert scope.database is None and not (storage/'canonical.sqlite3').exists()


def test_scoped_logs_bound_size_and_never_persist_message_bodies(tmp_path):
    import logging
    from ignis.infrastructure.caller_storage import CallerStorageScope,current_caller_storage
    scope=CallerStorageScope(tmp_path);scope.prepare_layout()
    token=current_caller_storage.set(scope)
    try:
        for index in range(8000):
            scope.log_handler.handle(logging.LogRecord('ignis.storage',logging.WARNING,__file__,1,
                'SOURCE_BODY SECRET_CANARY',(),None))
    finally:
        current_caller_storage.reset(token)
        logging.getLogger().removeHandler(scope.log_handler);scope.log_handler.close()
    files=list((scope.directory/'logs').iterdir())
    assert len(files)<=3 and all(item.stat().st_size<=262144 for item in files)
    assert all('SOURCE_BODY' not in item.read_text() and 'SECRET_CANARY' not in item.read_text() for item in files)


def test_log_symlink_refuses_foreign_write_and_new_logs_are_private(tmp_path):
    import logging
    from ignis.infrastructure.caller_storage import CallerStorageScope,current_caller_storage
    scope=CallerStorageScope(tmp_path);scope.prepare_layout()
    logs=scope.directory/'logs';logs.mkdir();foreign=tmp_path/'foreign.txt';foreign.write_text('UNCHANGED')
    target=logs/'ignis.log';target.symlink_to(foreign)
    token=current_caller_storage.set(scope)
    try:
        record=logging.LogRecord('ignis.storage',logging.WARNING,__file__,1,'BODY',(),None)
        scope.log_handler.handle(record)
        assert foreign.read_text()=='UNCHANGED'
        target.unlink();scope.log_handler.handle(record)
        assert target.stat().st_mode & 0o777==0o600
    finally:
        current_caller_storage.reset(token)
        logging.getLogger().removeHandler(scope.log_handler);scope.log_handler.close()


def test_configuration_scope_and_literal_allowlist_refuse_without_echo(tmp_path):
    from fastmcp.exceptions import ToolError
    from ignis.infrastructure.caller_configuration import load_caller_configuration
    from ignis.infrastructure.caller_storage import CallerStorageScope
    default=tmp_path/'.fnignis/canonical.sqlite3'
    for text,reason in [('UNREVIEWED=SECRET_CANARY\n','CALLER_CONFIG_REFUSED'),
        ('DATABASE_URL=${SECRET_CANARY}\n','CALLER_CONFIG_REFUSED'),
        ('DATABASE_URL=sqlite:////outside/canary.sqlite3\n','ROOT_SCOPE_REQUIRED')]:
        with pytest.raises(ToolError,match='^'+reason+'$') as error:
            load_caller_configuration(text,tmp_path,default)
        assert 'SECRET_CANARY' not in str(error.value)
    storage=tmp_path/'.fnignis';storage.mkdir();foreign=tmp_path/'foreign-config'
    foreign.write_text('SECRET_CANARY');(storage/'.env').symlink_to(foreign)
    with pytest.raises(ToolError,match='^CALLER_STORAGE_SCOPE_REFUSED$'):CallerStorageScope(tmp_path)
    assert foreign.read_text()=='SECRET_CANARY'


@pytest.mark.asyncio
async def test_scoped_filter_sanitizes_after_await_and_suppresses_exception_payload(tmp_path):
    import asyncio,logging
    from ignis.infrastructure.caller_storage import CallerStorageScope,current_caller_storage,_CallerSecretFilter
    storage=tmp_path/'.fnignis';storage.mkdir();config=storage/'.env'
    dsn='postgresql://dummy:SECRET_CANARY@invalid/db'
    config.write_text('DATABASE_URL='+dsn+'\nYOUTUBE_API_KEY=KEY_CANARY\n');config.chmod(0o600)
    scope=CallerStorageScope(tmp_path);token=current_caller_storage.set(scope)
    async def background():
        await asyncio.sleep(0)
        try:raise RuntimeError(dsn+' KEY_CANARY')
        except RuntimeError:
            import sys
            record=logging.LogRecord('ignis.storage',logging.ERROR,__file__,1,
                dsn+' KEY_CANARY',(),sys.exc_info())
        assert _CallerSecretFilter().filter(record)
        assert 'SECRET_CANARY' not in record.getMessage() and 'KEY_CANARY' not in record.getMessage()
        assert record.exc_info is None and record.exc_text is None
    try:task=asyncio.create_task(background())
    finally:current_caller_storage.reset(token)
    await task


@pytest.mark.asyncio
async def test_native_existing_manifest_confirmation_runs_protected_setup(tmp_path):
    from ignis.domain.research_workspace import ResearchWorkspace
    from ignis.infrastructure.persistence.workspace_repository import WorkspaceRepository
    root=tmp_path/'caller';root.mkdir()
    workspace=ResearchWorkspace(name='Existing research',slug='existing',root_path=root/'.fnignis/research/existing')
    WorkspaceRepository.write_manifest(workspace)
    manifest=workspace.root_path/'workspace.json';before=manifest.read_bytes()
    async with native_client(tmp_path,root) as client:
        proposal=payload(await client.call_tool('propose_research_workspace',
            {'host_workspace':str(root),'research_name':'Existing research','slug':'existing'}))
        declined=await client.call_tool('confirm_research_workspace',
            {'proposed_path':proposal['proposed_path'],'confirmation':False})
        assert not (root/'.fnignis/.env').exists() and not (root/'.gitignore').exists()
        result=payload(await client.call_tool('confirm_research_workspace',
            {'proposed_path':proposal['proposed_path'],'confirmation':True}))
        assert result['workspace_id']==str(workspace.workspace_id)
    assert (root/'.fnignis/.env').is_file(), 'Reused confirmation bypassed config protection.'
    assert (root/'.fnignis/.env.example').is_file()
    assert (root/'.gitignore').read_bytes()==b'/.fnignis/\n'
    assert manifest.read_bytes()==before


@pytest.mark.asyncio
async def test_native_existing_manifest_refuses_tracked_config_on_confirmation(tmp_path):
    import subprocess
    from ignis.domain.research_workspace import ResearchWorkspace
    from ignis.infrastructure.persistence.workspace_repository import WorkspaceRepository
    root=tmp_path/'caller';root.mkdir();subprocess.run(['git','init','-q',str(root)],check=True)
    workspace=ResearchWorkspace(name='Existing research',slug='existing',root_path=root/'.fnignis/research/existing')
    WorkspaceRepository.write_manifest(workspace)
    config=root/'.fnignis/.env';config.write_text('# Owner config\n');config.chmod(0o600)
    subprocess.run(['git','-C',str(root),'add','.fnignis/.env'],check=True)
    manifest=workspace.root_path/'workspace.json';before=manifest.read_bytes()
    async with native_client(tmp_path,root) as client:
        proposal=payload(await client.call_tool('propose_research_workspace',
            {'host_workspace':str(root),'research_name':'Existing research','slug':'existing'}))
        result=await client.call_tool('confirm_research_workspace',
            {'proposed_path':proposal['proposed_path'],'confirmation':True},raise_on_error=False)
        assert result.is_error and 'CALLER_CONFIG_TRACKED' in result.content[0].text
    assert config.read_text()=='# Owner config\n' and manifest.read_bytes()==before
    assert not (root/'.gitignore').exists()
