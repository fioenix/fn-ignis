"""Native caller-root ownership for persistent local mission storage, without source grants."""
from contextvars import ContextVar
from pathlib import Path
import stat
from threading import RLock
from urllib.parse import unquote, urlsplit

from fastmcp.server.middleware import Middleware
from fastmcp.exceptions import ToolError


current_caller_storage = ContextVar('ignis_caller_storage', default=None)


class CallerStorageScope:
    """One advertised local directory, pinned for one owning native lifespan."""

    def __init__(self, root):
        self.root = Path(root)
        self.directory = self.root / '.fnignis'
        self.database = self.directory / 'canonical.sqlite3'
        self.components = None
        self.runtime = None
        self._identities = {}
        self._lock = RLock()
        self._pin(self.root, require_directory=True)

    def _pin(self, path, *, require_directory=False):
        for node in reversed((path, *path.parents)):
            if node.is_symlink(): raise ToolError('CALLER_STORAGE_SCOPE_REFUSED')
            if not node.exists():
                if node in self._identities: raise ToolError('CALLER_STORAGE_SCOPE_REFUSED')
                continue
            info = node.lstat()
            if node != path or require_directory:
                if not stat.S_ISDIR(info.st_mode): raise ToolError('CALLER_STORAGE_SCOPE_REFUSED')
            elif not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
                raise ToolError('CALLER_STORAGE_SCOPE_REFUSED')
            identity = (info.st_dev, info.st_ino)
            if node in self._identities and self._identities[node] != identity:
                raise ToolError('CALLER_STORAGE_SCOPE_REFUSED')
            self._identities[node] = identity

    def check(self):
        with self._lock:
            if not self.root.is_dir(): raise ToolError('CALLER_STORAGE_SCOPE_REFUSED')
            self._pin(self.root, require_directory=True)
            self._pin(self.directory, require_directory=True)
            self._pin(self.database)
            for suffix in ('-journal','-wal','-shm'):
                if Path(str(self.database)+suffix).is_symlink():
                    raise ToolError('CALLER_STORAGE_SCOPE_REFUSED')

    def check_path(self, path):
        path = Path(path)
        if not path.is_absolute() or '..' in path.parts or self.directory not in path.parents:
            raise ToolError('CALLER_STORAGE_SCOPE_REFUSED')
        with self._lock:
            self.check()
            # Payload files may be atomically replaced by their owner; pin ancestry only.
            self._pin(path.parent, require_directory=True)
            if path.is_symlink(): raise ToolError('CALLER_STORAGE_SCOPE_REFUSED')
        return path

    def guard_repository(self, repository):
        original_connection = repository._get_connection
        original_write = repository._run_write
        def connection():
            self.check()
            result = original_connection()
            self.check()
            return result
        async def write(operation):
            self.check()
            def guarded():
                self.check()
                result = operation()
                self.check()
                return result
            return await original_write(guarded)
        repository._get_connection = connection
        repository._run_write = write


class CallerStorageMiddleware(Middleware):
    """Scope existing mission tool schemas using actual request/session roots only."""

    def __init__(self, compose, runtime_for_scope):
        self.compose = compose
        self.runtime_for_scope = runtime_for_scope

    async def on_call_tool(self, context, call_next):
        name = context.message.name
        arguments = context.message.arguments or {}
        if not ('mission' in name or 'research_workspace' in name or name == 'confirm_market_brief'
                or 'mission_id' in arguments or 'workspace_id' in arguments):
            return await call_next(context)
        ctx = context.fastmcp_context
        if ctx is None or ctx.request_context is None:
            raise ToolError('ROOT_REQUIRED')
        try:
            roots = (await ctx.session.list_roots()).roots
        except Exception:
            raise ToolError('ROOT_REQUIRED') from None
        if len(roots) != 1: raise ToolError('ROOT_REQUIRED')
        uri = urlsplit(str(roots[0].uri))
        if uri.scheme != 'file' or uri.netloc not in ('','localhost') or uri.query or uri.fragment:
            raise ToolError('ROOT_REQUIRED')
        path = Path(unquote(uri.path))
        if not path.is_absolute() or '..' in path.parts or not path.is_dir():
            raise ToolError('ROOT_REQUIRED')
        owner = ctx.lifespan_context.get('mission_relay')
        if owner is None or owner.closed: raise ToolError('ROOT_REQUIRED')
        key = str(path)
        scope = owner.caller_scopes.get(key)
        if scope is None:
            scope = CallerStorageScope(path)
            owner.caller_scopes[key] = scope
        scope.check()
        if 'host_workspace' in arguments and Path(arguments['host_workspace']) != scope.root:
            raise ToolError('CALLER_STORAGE_SCOPE_REFUSED')
        if 'proposed_path' in arguments:
            scope.check_path(arguments['proposed_path'])
        token = current_caller_storage.set(scope)
        try:
            if scope.components is None:
                scope.components = self.compose(scope)
                scope.runtime = self.runtime_for_scope(scope, owner)
            return await call_next(context)
        finally:
            current_caller_storage.reset(token)
