"""Synthetic owned-file retention; no real storage or credential authority."""
from pathlib import Path
import pytest
from tests.unit.test_follow_up_provider_bridge import setup_bridge

from tests.unit import test_follow_up_root_composition as setup
from ignis.infrastructure import follow_up_root_composition as driver


async def actual_parent(tmp_path):
    _,_,_,_,plugin,calls,credentials,quota,_,_=setup_bridge()
    brief,receipt=setup.framing()
    class Clusterer:
        async def cluster_signals(self,signals):return []
    result=await driver.bootstrap_confirmed_parent(root=tmp_path/'owned-driver',brief=brief,receipt=receipt,
        instruction=setup.INSTRUCTION,resolve_credential=plugin._resolve_credential,
        transport=plugin._transport,quota_manager=quota,clusterer=Clusterer())
    store=result['executor']._workspace_store
    mission_id=result['host'].confirmation.selected_parent_id
    snapshot=await store.load_mission_evidence_snapshot(mission_id)
    workspace=await store.get_research_workspace(snapshot.mission.workspace_id)
    journal=await store.latest_run_journal(mission_id)
    return result,workspace.manifest_path,journal.journal_path,calls,credentials


@pytest.mark.asyncio
async def test_actual_canonical_expiry_removes_owned_workspace_metadata(tmp_path):
    print('PHASE ACTUAL_PARENT_BEGIN',flush=True)
    result,manifest,journal,calls,credentials=await actual_parent(tmp_path)
    print('PHASE ACTUAL_PARENT_COMPLETE',flush=True)
    assert manifest.is_file() and journal.is_file()
    assert 'collection_plan' in journal.read_text()
    foreign=tmp_path/'foreign';foreign.write_bytes(b'Foreign owner bytes')
    host=result['host']
    host.clock=lambda:host.confirmation.bounds.retention_until
    print('PHASE EXPLICIT_EXPIRY_BEGIN',flush=True)
    await driver.expire_owned_storage(host,result['canonical'],result['repository'],result['accounting'])
    print('PHASE EXPLICIT_EXPIRY_COMPLETE',flush=True)
    assert not result['canonical'].path.exists()
    assert not manifest.exists(), 'Owned workspace manifest escaped explicit seven-day disposition'
    assert not journal.exists(), 'Owned collection-plan journal escaped explicit seven-day disposition'
    assert foreign.read_bytes()==b'Foreign owner bytes'
    assert len(calls)==len(credentials)==2


@pytest.mark.asyncio
async def test_metadata_purge_failure_reopens_delete_only_preserving_foreign(tmp_path,monkeypatch):
    from ignis.infrastructure.follow_up_workspace_retention import GeneratedWorkspaceRetention
    result,manifest,journal,calls,credentials=await actual_parent(tmp_path)
    metadata=result['canonical'].generated_metadata
    original=metadata.receipt.read_bytes()
    foreign=manifest.parent/'foreign-user-note.txt';foreign.write_bytes(b'Foreign owner bytes')
    host=result['host'];host.clock=lambda:host.confirmation.bounds.retention_until
    original_unlink=Path.unlink
    def failed(path,*args,**kwargs):
        if path==journal:raise OSError('Synthetic registered journal first deletion failure')
        return original_unlink(path,*args,**kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(Path,'unlink',failed)
        with pytest.raises(OSError):
            await driver.expire_owned_storage(host,result['canonical'],result['repository'],result['accounting'])
    assert host._revoked and result['canonical'].closed and metadata.closed
    assert journal.exists() and metadata.receipt.read_bytes()==original
    reopened=GeneratedWorkspaceRetention(metadata.root,owner_reference=metadata.owner_reference,
        scope_digest=metadata.scope_digest,retention_until=metadata.retention_until)
    result['canonical'].generated_metadata=reopened
    audit=await driver.expire_owned_storage(host,result['canonical'],result['repository'],result['accounting'])
    assert audit['metadata_audit']['purged'] and not manifest.exists() and not journal.exists()
    assert metadata.receipt.read_bytes()==original and foreign.read_bytes()==b'Foreign owner bytes'
    assert len(calls)==len(credentials)==2


@pytest.mark.parametrize('change',['bytes','replacement','symlink'])
@pytest.mark.asyncio
async def test_changed_owned_metadata_refuses_and_preserves_foreign(tmp_path,change):
    from ignis.application.ports.follow_up_execution_port import FollowUpExecutionBoundaryError
    result,manifest,journal,calls,credentials=await actual_parent(tmp_path)
    original=manifest.read_bytes()
    foreign=tmp_path/'foreign-change';foreign.write_bytes(b'Foreign changed payload')
    if change=='bytes':manifest.write_bytes(b'Changed bytes after producer settlement')
    elif change=='replacement':
        replacement=tmp_path/'replacement';replacement.write_bytes(b'Foreign replaced payload');replacement.replace(manifest)
    else:manifest.unlink();manifest.symlink_to(foreign)
    host=result['host'];host.clock=lambda:host.confirmation.bounds.retention_until
    with pytest.raises(FollowUpExecutionBoundaryError):
        await driver.expire_owned_storage(host,result['canonical'],result['repository'],result['accounting'])
    assert manifest.exists() and journal.exists() and host._revoked
    assert foreign.read_bytes()==b'Foreign changed payload'
    assert len(calls)==len(credentials)==2


@pytest.mark.asyncio
async def test_failed_bootstrap_original_receipt_cleans_owned_metadata_without_mission_confirmation(tmp_path):
    from datetime import datetime,timedelta,timezone
    from ignis.infrastructure.follow_up_workspace_retention import GeneratedWorkspaceRetention,RetainedWorkspaceRepository
    from ignis.infrastructure.follow_up_host_activation import PreparedCanonicalSQLite
    from ignis.application.use_cases.create_research_workspace import CreateResearchWorkspaceUseCase
    now=datetime.now(timezone.utc);expiry=now+timedelta(days=7)
    metadata=GeneratedWorkspaceRetention(tmp_path/'failed-bootstrap',owner_reference='synthetic-approved-collection',
        scope_digest='a'*64,retention_until=expiry,create=True)
    prepared=PreparedCanonicalSQLite(metadata.root/'canonical',owner_reference=metadata.owner_reference,
        collection_scope_digest=metadata.scope_digest)
    metadata.bind_bootstrap(prepared)
    repository=prepared.repository
    await repository._ensure_schema()
    store=RetainedWorkspaceRepository(repository,metadata)
    proposal=await CreateResearchWorkspaceUseCase(store).propose(metadata.root,'Failed synthetic bootstrap')
    workspace=await store.create_owned_workspace(proposal)
    assert workspace.manifest_path.is_file()
    # Simulate failure before any Brief/mission confirmation. No invented canonical IDs or source payload.
    await repository.close();prepared._closed=True;metadata.close()
    original=metadata.receipt.read_bytes();bootstrap=prepared.receipt.read_bytes()
    reopened=GeneratedWorkspaceRetention(metadata.root,owner_reference=metadata.owner_reference,
        scope_digest=metadata.scope_digest,retention_until=expiry)
    audit=reopened.purge(now=expiry)
    assert audit['purged'] and not prepared.path.exists() and not workspace.manifest_path.exists()
    assert metadata.receipt.read_bytes()==original and prepared.receipt.read_bytes()==bootstrap
    assert not proposal.proposed_path.exists()

"""Actual generated-file controls on disposable local storage only."""
from datetime import datetime, timedelta, timezone
import json
import pytest
from ignis.application.ports.follow_up_execution_port import FollowUpExecutionBoundaryError
from ignis.infrastructure.follow_up_workspace_retention import GeneratedWorkspaceRetention


@pytest.mark.parametrize('change', ['empty_workspace', 'historical_journal'])
def test_settled_changed_content_is_preserved_at_expiry(tmp_path, change):
    expiry=datetime.now(timezone.utc)+timedelta(days=7)
    retention=GeneratedWorkspaceRetention(tmp_path/'owned',owner_reference='synthetic-owner',
        scope_digest='a'*64,retention_until=expiry,create=True)
    if change=='empty_workspace':
        path=retention.root/'workspace.json'
        retention.write(path,'{"name":"Synthetic owned workspace"}\n')
        changed=b''
    else:
        path=retention.root/'journals'/'run.json'
        changed=b'{"status":"STARTED"}\n'
        retention.write(path,changed.decode())
        retention.write(path,'{"status":"COMPLETED"}\n',replace_existing=True)
    before=path.stat();identity=(before.st_dev,before.st_ino)
    path.write_bytes(changed)
    after=path.stat()
    assert (after.st_dev,after.st_ino)==identity
    # The original implementation accepts both mutations, then physically deletes them.
    try:
        retention._validate(path,retention._load()['files'][str(path.relative_to(retention.root))])
        accepted=True
    except FollowUpExecutionBoundaryError:
        accepted=False
    print(f'CONTROL {change} original_predicate_accepted={accepted}',flush=True)
    try:
        retention.purge(now=expiry)
        refused=False
    except FollowUpExecutionBoundaryError:
        refused=True
    assert path.exists(), 'Expiry physically deleted settled changed content'
    assert path.read_bytes()==changed
    assert (path.stat().st_dev,path.stat().st_ino)==identity
    assert refused and not accepted


@pytest.mark.parametrize('after_replace', [False, True])
def test_interrupted_replacement_reopens_delete_only_with_exact_pairs(tmp_path, monkeypatch, after_replace):
    import os
    expiry=datetime.now(timezone.utc)+timedelta(days=7)
    retention=GeneratedWorkspaceRetention(tmp_path/'pending',owner_reference='synthetic-owner',
        scope_digest='a'*64,retention_until=expiry,create=True)
    path=retention.root/'journal.json'
    retention.write(path,'{"status":"STARTED"}\n')
    original_replace=os.replace
    def interrupted(source,destination):
        if destination==path:
            if after_replace:original_replace(source,destination)
            raise OSError('Synthetic replacement interruption')
        return original_replace(source,destination)
    with monkeypatch.context() as patch:
        patch.setattr(os,'replace',interrupted)
        with pytest.raises(OSError,match='Synthetic replacement interruption'):
            retention.write(path,'{"status":"COMPLETED"}\n',replace_existing=True)
    reopened=GeneratedWorkspaceRetention(retention.root,owner_reference=retention.owner_reference,
        scope_digest=retention.scope_digest,retention_until=expiry)
    assert reopened.closed
    with pytest.raises(FollowUpExecutionBoundaryError):reopened.write(path,'Forbidden retry ingress')
    assert reopened.purge(now=expiry)['purged']
    assert not path.exists() and not path.with_suffix('.json.tmp').exists()


def test_pending_replacement_refuses_cross_product_content(tmp_path,monkeypatch):
    import os
    expiry=datetime.now(timezone.utc)+timedelta(days=7)
    retention=GeneratedWorkspaceRetention(tmp_path/'pending-pairs',owner_reference='synthetic-owner',
        scope_digest='a'*64,retention_until=expiry,create=True)
    path=retention.root/'journal.json';old=b'{"status":"STARTED"}\n'
    retention.write(path,old.decode())
    original_replace=os.replace
    def interrupted(source,destination):
        original_replace(source,destination)
        if destination==path:raise OSError('Synthetic post-replacement interruption')
    with monkeypatch.context() as patch:
        patch.setattr(os,'replace',interrupted)
        with pytest.raises(OSError):retention.write(path,'{"status":"COMPLETED"}\n',replace_existing=True)
    identity=(path.stat().st_dev,path.stat().st_ino)
    path.write_bytes(old)
    with pytest.raises(FollowUpExecutionBoundaryError):retention.purge(now=expiry)
    assert path.read_bytes()==old and (path.stat().st_dev,path.stat().st_ino)==identity


def test_interrupted_creation_preserves_registered_empty_recovery(tmp_path,monkeypatch):
    import os
    from pathlib import Path
    expiry=datetime.now(timezone.utc)+timedelta(days=7)
    retention=GeneratedWorkspaceRetention(tmp_path/'creation',owner_reference='synthetic-owner',
        scope_digest='a'*64,retention_until=expiry,create=True)
    path=retention.root/'workspace.json'
    original_unlink=Path.unlink
    def interrupted_stream(*args,**kwargs):raise OSError('Synthetic payload opening interruption')
    def interrupted_unlink(candidate,*args,**kwargs):
        if candidate==path:raise OSError('Synthetic owned-file cleanup interruption')
        return original_unlink(candidate,*args,**kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(os,'fdopen',interrupted_stream);patch.setattr(Path,'unlink',interrupted_unlink)
        with pytest.raises(OSError):retention.write(path,'{"name":"Synthetic"}\n')
    assert path.read_bytes()==b''
    reopened=GeneratedWorkspaceRetention(retention.root,owner_reference=retention.owner_reference,
        scope_digest=retention.scope_digest,retention_until=expiry)
    assert reopened.closed and reopened.purge(now=expiry)['purged'] and not path.exists()
