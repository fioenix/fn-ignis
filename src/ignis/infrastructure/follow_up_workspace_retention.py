"""Private root-owned generated-file lifecycle; no canonical evidence or grants are stored."""
import hashlib
import json
import os
from dataclasses import replace
from pathlib import Path
from threading import RLock
from uuid import uuid4

from ignis.application.ports.follow_up_execution_port import FollowUpExecutionBoundaryError
from ignis.application.ports.research_workspace_port import RunJournal
from ignis.infrastructure.persistence.workspace_repository import (
    WorkspaceRepository, _journal_payload, _utc_now, JOURNAL_PREFIX, JOURNAL_SEQUENCE_LIMIT,
    RunJournalExhaustedError,
)
from ignis.domain.research_workspace import JOURNAL_DIRNAME


def _hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _expiry(value):
    """None records persistent retention until explicit user deletion."""
    return None if value is None else value.isoformat()


class GeneratedWorkspaceRetention:
    """Privileged explicit root creation, before bootstrap; reopen is deletion-only."""

    def __init__(self, root, *, owner_reference, scope_digest, retention_until, create=False):
        self.root = Path(root)
        self.receipt = self.root/'generated-ownership.json'
        self.registry = self.root/'generated-files.json'
        self._lock = RLock()
        self.closed = not create
        self.active_run = False
        self.owner_reference, self.scope_digest = owner_reference, scope_digest
        self.retention_until = retention_until
        if create:
            self.root.mkdir(exist_ok=False)
            stat = self.root.stat()
            record = {'owner_reference':owner_reference,'scope_digest':scope_digest,
                'retention_until':_expiry(retention_until),'root_identity':[stat.st_dev,stat.st_ino],
                'creation_token':uuid4().hex}
            with self.receipt.open('x') as stream:
                json.dump(record,stream,sort_keys=True)
                stream.flush();os.fsync(stream.fileno())
            self._sync_directory()
            self._publish({'receipt_hash':_hash(self.receipt),'files':{},'directories':{},'purged':False})
        self._check_root()
        state = self._load()
        if state['purged']:
            self.closed = True

    def _sync_directory(self):
        descriptor = os.open(self.root,os.O_RDONLY)
        try:os.fsync(descriptor)
        finally:os.close(descriptor)

    def _check_root(self):
        if self.root.is_symlink() or self.receipt.is_symlink() or self.registry.is_symlink():
            raise FollowUpExecutionBoundaryError()
        record=json.loads(self.receipt.read_text())
        stat=self.root.stat()
        if (record['owner_reference']!=self.owner_reference or record['scope_digest']!=self.scope_digest
                or record['retention_until']!=_expiry(self.retention_until)
                or record['root_identity']!=[stat.st_dev,stat.st_ino]):
            raise FollowUpExecutionBoundaryError()

    def _load(self):
        self._check_root()
        state=json.loads(self.registry.read_text())
        if state['receipt_hash']!=_hash(self.receipt):raise FollowUpExecutionBoundaryError()
        return state

    def _publish(self,state):
        temporary=self.root/('.'+uuid4().hex+'.generated.tmp')
        try:
            with temporary.open('x') as stream:
                json.dump(state,stream,sort_keys=True)
                stream.flush();os.fsync(stream.fileno())
            os.replace(temporary,self.registry)
            self._sync_directory()
        finally:
            if temporary.exists():temporary.unlink()

    def _relative(self,path):
        path=Path(path)
        relative=path.relative_to(self.root)
        if '..' in relative.parts or not relative.parts:raise FollowUpExecutionBoundaryError()
        for ancestor in (path,*path.parents):
            if ancestor==self.root.parent:break
            if ancestor.is_symlink():raise FollowUpExecutionBoundaryError()
        return str(relative)

    def _parents(self,path,state):
        parents=list(path.parent.relative_to(self.root).parents)
        targets=[self.root/p for p in reversed(parents) if str(p)!='.']+[path.parent]
        for directory in targets:
            if directory==self.root:continue
            key=self._relative(directory)
            if directory.exists():
                identity=state['directories'].get(key)
                stat=directory.stat()
                if identity!=[stat.st_dev,stat.st_ino]:raise FollowUpExecutionBoundaryError()
            else:
                directory.mkdir()
                stat=directory.stat()
                state['directories'][key]=[stat.st_dev,stat.st_ino]
                self._publish(state)

    def _file_identity(self,path):
        self._relative(path)
        stat=path.stat()
        return [stat.st_dev,stat.st_ino]

    def _validate(self,path,record):
        identity=self._file_identity(path)
        if record['kind']=='generated':
            bindings=record.get('bindings',[])
            if (record.get('state') not in ('pending-creation','pending-replacement','settled')
                    or not bindings or (record['state']=='settled' and len(bindings)!=1)
                    or {'identity':identity,'hash':_hash(path)} not in bindings):
                raise FollowUpExecutionBoundaryError()
        elif identity not in record['identities']:
            raise FollowUpExecutionBoundaryError()

    def write(self,path,content,*,replace_existing=False):
        data=content.encode('utf-8')
        with self._lock:
            if self.closed:raise FollowUpExecutionBoundaryError()
            path=Path(path);key=self._relative(path);state=self._load()
            if replace_existing:
                old=state['files'].get(key)
                if old is None or not path.exists():raise FollowUpExecutionBoundaryError()
                self._validate(path,old)
                temporary=path.with_suffix(path.suffix+'.tmp')
                self.write(temporary,content)
                state=self._load();fresh=state['files'][self._relative(temporary)]
                state['files'][key]={'kind':'generated','state':'pending-replacement',
                    'bindings':old['bindings']+fresh['bindings']}
                self._publish(state)
                self._validate(path,old)
                os.replace(temporary,path)
                self._sync_directory()
                state['files'][key]=fresh
                del state['files'][self._relative(temporary)]
                self._publish(state)
                return
            self._parents(path,state)
            descriptor=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
            try:
                stat=os.fstat(descriptor)
                identity=[stat.st_dev,stat.st_ino]
                binding={'identity':identity,'hash':hashlib.sha256(data).hexdigest()}
                state['files'][key]={'kind':'generated','state':'pending-creation',
                    'bindings':[{'identity':identity,'hash':hashlib.sha256(b'').hexdigest()},binding]}
                # Identity and the allowed complete bytes are durable before payload writing.
                self._publish(state)
                with os.fdopen(descriptor,'wb',closefd=False) as stream:
                    stream.write(data);stream.flush();os.fsync(stream.fileno())
                state['files'][key]={'kind':'generated','state':'settled','bindings':[binding]}
                self._publish(state)
            except BaseException:
                # A failed newly-owned producer never returns an unregistered payload.
                stat=os.fstat(descriptor)
                if path.exists() and self._file_identity(path)==[stat.st_dev,stat.st_ino]:
                    path.unlink()
                raise
            finally:os.close(descriptor)

    def bind_bootstrap(self,prepared):
        with self._lock:
            if self.closed:raise FollowUpExecutionBoundaryError()
            prepared._check()
            if (prepared.owner_reference!=self.owner_reference
                    or prepared.collection_scope_digest!=self.scope_digest
                    or prepared.root!=self.root/'canonical'):
                raise FollowUpExecutionBoundaryError()
            state=self._load()
            directory=prepared.root.stat()
            state['directories'][self._relative(prepared.root)]=[directory.st_dev,directory.st_ino]
            state['files'][self._relative(prepared.path)]={'kind':'bootstrap-database',
                'identities':[list(prepared._identity)],'hashes':[],
                'bootstrap_receipt_hash':_hash(prepared.receipt)}
            self._publish(state)

    def seal_bootstrap(self,prepared):
        with self._lock:
            state=self._load()
            record=state['files'][self._relative(prepared.path)]
            self._validate(prepared.path,record)
            if record['bootstrap_receipt_hash']!=_hash(prepared.receipt):raise FollowUpExecutionBoundaryError()
            record['kind']='canonical-delegated'
            self._publish(state)

    def record_phase(self,name,value):
        if name != 'private_audit':raise FollowUpExecutionBoundaryError()
        with self._lock:
            state=self._load()
            if name in state and state[name]!=value:raise FollowUpExecutionBoundaryError()
            state[name]=value
            self._publish(state)

    def close(self):
        with self._lock:self.closed=True

    def purge(self,*,now):
        with self._lock:
            if self.active_run:raise FollowUpExecutionBoundaryError()
            self.closed=True
            if self.retention_until is None or now<self.retention_until:raise FollowUpExecutionBoundaryError()
            state=self._load()
            if state['purged']:return state['audit']
            # Validate exact producer directories and files before deleting; never inventory foreign entries.
            for key,identity in state['directories'].items():
                directory=self.root/key
                self._relative(directory)
                if directory.exists():
                    stat=directory.stat()
                    if [stat.st_dev,stat.st_ino]!=identity:raise FollowUpExecutionBoundaryError()
            for key,record in state['files'].items():
                path=self.root/key
                self._relative(path)
                if not path.exists():continue
                self._validate(path,record)
                if record['kind']=='canonical-delegated':raise FollowUpExecutionBoundaryError()
                if record['kind']=='bootstrap-database':
                    from ignis.infrastructure.follow_up_host_activation import PreparedCanonicalSQLite
                    PreparedCanonicalSQLite.purge_owned_bootstrap(
                        path, owner_reference=self.owner_reference, scope_digest=self.scope_digest,
                        receipt_hash=record['bootstrap_receipt_hash'], identity=record['identities'][0],
                        now=now, retention_until=self.retention_until)
            for key,record in state['files'].items():
                path=self.root/key
                if path.exists():
                    self._validate(path,record)
                    path.unlink()
            for key in sorted(state['directories'],key=lambda value:len(Path(value).parts),reverse=True):
                directory=self.root/key
                if directory.exists():
                    try:directory.rmdir()
                    except OSError as error:
                        import errno
                        if error.errno not in (errno.ENOTEMPTY,errno.EEXIST):raise
            self._sync_directory()
            audit={'receipt_hash':state['receipt_hash'],'registered_files':len(state['files']),
                   'purged':True,'purged_at':now.isoformat()}
            state['purged']=True;state['audit']=audit
            self._publish(state)
            return audit


class RetainedWorkspaceRepository(WorkspaceRepository):
    """Actual canonical repository operations with exact producer-file enrollment."""

    def __init__(self,repository,retention):
        super().__init__(repository)
        self.retention=retention

    async def create_owned_workspace(self,proposal):
        from ignis.domain.research_workspace import ResearchWorkspace
        if proposal.exists or proposal.requires_adoption:raise FollowUpExecutionBoundaryError()
        workspace=ResearchWorkspace(slug=proposal.slug,root_path=proposal.proposed_path,name=proposal.research_name)
        self.retention.write(workspace.manifest_path,workspace.manifest_json())
        return await self.save_research_workspace(workspace)

    async def allocate_run_journal(self,workspace,mission_id,run_id=None):
        started=_utc_now();stamp=started.strftime('%Y%m%d-%H%M%S');run_id=run_id or uuid4()
        for sequence in range(1,JOURNAL_SEQUENCE_LIMIT):
            path=workspace.root_path/JOURNAL_DIRNAME/f'{JOURNAL_PREFIX}{stamp}-{sequence:03d}.json'
            journal=RunJournal(run_id=run_id,mission_id=mission_id,workspace_id=workspace.workspace_id,
                journal_path=path,sequence=sequence,status='STARTED',started_at=started)
            try:self.retention.write(path,_journal_payload(journal))
            except FileExistsError:continue
            return await self.record_run_journal(journal)
        raise RunJournalExhaustedError('The exact owned journal allocation range is exhausted.')

    async def record_collection_plan(self,journal,plan):
        payload=json.loads(journal.journal_path.read_text())
        payload['collection_plan']=plan;payload['collection_plan_digest']=plan['plan_digest']
        self.retention.write(journal.journal_path,json.dumps(payload,indent=2,sort_keys=True)+'\n',replace_existing=True)

    async def _finish_run_journal(self,journal,status):
        finished=replace(journal,status=status,completed_at=_utc_now())
        payload=json.loads(journal.journal_path.read_text())
        self.retention.write(journal.journal_path,_journal_payload(finished,collection_plan=payload.get('collection_plan')),
                             replace_existing=True)
        return await self.record_run_journal(finished)
