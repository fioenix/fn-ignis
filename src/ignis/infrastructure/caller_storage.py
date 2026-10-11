"""Native caller-root ownership for persistent local mission storage, without source grants."""
from contextvars import ContextVar
import hashlib
import os
import subprocess
import logging
import copy
from logging.handlers import RotatingFileHandler
from pathlib import Path
import stat
from threading import RLock
from urllib.parse import unquote, urlsplit

from fastmcp.server.middleware import Middleware
from fastmcp.exceptions import ToolError
from mcp.types import ClientCapabilities
from ignis.infrastructure.caller_configuration import load_caller_configuration


current_caller_storage = ContextVar('ignis_caller_storage', default=None)


class _CallerSecretFilter(logging.Filter):
    def filter(self, record):
        scope = current_caller_storage.get()
        if scope is None:
            return True
        try:
            message = record.getMessage()
            values = (scope.configuration.DATABASE_URL, scope.configuration.YOUTUBE_API_KEY)
            secrets = [value.get_secret_value() for value in values if value.get_secret_value()]
            uri = urlsplit(scope.configuration.DATABASE_URL.get_secret_value())
            secrets.extend(value for value in (uri.username, uri.password,
                unquote(uri.password or '')) if value)
            for secret in secrets:
                message = message.replace(secret, '[REDACTED]')
            record.msg, record.args = message, ()
            if record.exc_info is not None:
                record.msg += ' [exception=' + record.exc_info[0].__name__ + ']'
                record.exc_info, record.exc_text = None, None
        except Exception:
            record.msg, record.args = 'CALLER_DIAGNOSTIC_REDACTED', ()
            record.exc_info, record.exc_text = None, None
        return True


class _CallerLog(RotatingFileHandler):
    def __init__(self, scope):
        self.scope = scope
        super().__init__(scope.directory/'logs/ignis.log',maxBytes=262144,backupCount=2,delay=True)
        self.addFilter(_CallerSecretFilter())

    def _open(self):
        target = self.scope.check_path(Path(self.baseFilename))
        descriptor = os.open(target, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
        return os.fdopen(descriptor, 'a', encoding='utf-8')

    def emit(self, record):
        if current_caller_storage.get() is not self.scope or not record.name.startswith('ignis.'):
            return
        try:
            target = self.scope.check_path(Path(self.baseFilename))
            for suffix in ('','.1','.2'):
                self.scope.check_path(Path(str(target)+suffix))
            target.parent.mkdir(exist_ok=True)
            audit = copy.copy(record)
            # Persist bounded operational metadata, never arbitrary messages or source bodies.
            audit.msg = 'CALLER_OPERATIONAL_EVENT level=%d component=ignis' % record.levelno
            audit.args, audit.exc_info, audit.exc_text, audit.stack_info = (), None, None, None
            super().emit(audit)
        except Exception:
            # A diagnostic refusal cannot replace a mission outcome or disclose a secret.
            return


class CallerStorageScope:
    """One advertised local directory, pinned for one owning native lifespan."""

    def __init__(self, root):
        self.root = Path(root)
        self.directory = self.root / '.fnignis'
        self.database = self.directory / 'canonical.sqlite3'
        self.config_path = self.directory / '.env'
        self._config_snapshot = None
        self.log_handler = None
        self.components = None
        self.runtime = None
        self._identities = {}
        self._lock = RLock()
        self._pin(self.root, require_directory=True)
        self._pin(self.config_path)
        text, self._config_snapshot = self._read_configuration()
        self.configuration, self.database = load_caller_configuration(
            text, self.root, self.database)

    def _read_configuration(self):
        if not self.config_path.exists():
            return '', None
        info = self.config_path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_size > 32768:
            raise ToolError('CALLER_CONFIG_REFUSED')
        try:
            data = self.config_path.read_bytes()
            return data.decode('utf-8'), (info.st_dev, info.st_ino, hashlib.sha256(data).digest())
        except Exception:
            raise ToolError('CALLER_CONFIG_REFUSED') from None

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
            self._pin(self.config_path)
            if self._read_configuration()[1] != self._config_snapshot:
                raise ToolError('CALLER_CONFIG_CHANGED')
            if self.database is None:
                return
            self._pin(self.database)
            if self.database.exists() and not self.database.is_file():
                raise ToolError('CALLER_DATABASE_REFUSED')
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
        if hasattr(repository, '_get_pool'):
            original_pool = repository._get_pool
            async def pool():
                self.check()
                try:
                    result = await original_pool()
                    self.check()
                    return result
                except ToolError:
                    raise
                except Exception:
                    raise ToolError('CALLER_DATABASE_REFUSED') from None
            repository._get_pool = pool
            return
        original_connection = repository._get_connection
        original_write = repository._run_write
        def connection():
            self.check()
            try:
                result = original_connection()
            except Exception:
                raise ToolError('CALLER_DATABASE_REFUSED') from None
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


    def prepare_layout(self):
        """Protect caller-owned runtime files only after explicit workspace confirmation."""
        self.check()
        ignore = self.root / '.gitignore'
        if ignore.is_symlink() or (ignore.exists() and not ignore.is_file()):
            raise ToolError('CALLER_LAYOUT_REFUSED')
        def git(*arguments):
            return subprocess.run(['git','-C',str(self.root),*arguments], capture_output=True,
                timeout=5, check=False, env={'PATH':'/usr/bin:/bin:/usr/sbin:/sbin'})
        tracked = git('ls-files','--error-unmatch','--','.fnignis/.env')
        if tracked.returncode == 0:
            raise ToolError('CALLER_CONFIG_TRACKED')
        before = ignore.read_bytes() if ignore.exists() else None
        line = b'/.fnignis/'
        if before is None or line not in before.splitlines():
            with ignore.open('ab') as opened:
                opened.write((b'\n' if before and not before.endswith(b'\n') else b'') + line + b'\n')
        in_git = git('rev-parse','--show-toplevel')
        if in_git.returncode == 0 and git('check-ignore','--quiet','--','.fnignis/.env').returncode != 0:
            # Roll back only our exact append; never rewrite a concurrent owner edit.
            appended = (before or b'') + (b'\n' if before and not before.endswith(b'\n') else b'') + line + b'\n'
            if ignore.read_bytes() == appended:
                if before is None: ignore.unlink()
                else: ignore.write_bytes(before)
            raise ToolError('CALLER_LAYOUT_REFUSED')
        self.directory.mkdir(exist_ok=True)
        self.check_path(self.config_path)
        if not self.config_path.exists():
            descriptor = os.open(self.config_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(descriptor,'w') as opened:
                opened.write('# Optional caller-owned settings. Restart the native server after edits.\n')
            self._config_snapshot = self._read_configuration()[1]
        example = self.check_path(self.directory / '.env.example')
        if not example.exists():
            template = Path(__file__).parent / 'templates' / 'caller.env.example'
            with example.open('x') as opened: opened.write(template.read_text())
        self.check()
        if self.log_handler is None:
            self.log_handler = _CallerLog(self)
            logging.getLogger().addHandler(self.log_handler)


def _root_required(category, ctx, *, rpc_error="UNKNOWN", owner_state="UNKNOWN"):
    """Expose fixed refusal facts only; never serialize client or exception payloads."""
    capability = "UNKNOWN"
    try:
        declared = ctx.session.client_capabilities
        if type(declared) is ClientCapabilities:
            capability = "ADVERTISED" if declared.roots is not None else "NOT_ADVERTISED"
    except Exception:
        pass
    return ToolError(f"ROOT_REQUIRED category={category} roots_capability={capability} "
                     f"rpc_error={rpc_error} owner_state={owner_state}")


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
        if ctx is None or getattr(ctx, 'request_context', None) is None:
            raise _root_required('REQUEST_CONTEXT_ABSENT', ctx)
        try:
            roots = (await ctx.session.list_roots()).roots
        except Exception as error:
            kind = 'UNSUPPORTED' if type(error) is NotImplementedError else 'UNKNOWN'
            raise _root_required('ROOTS_RPC_UNAVAILABLE', ctx, rpc_error=kind) from None
        try:
            single = len(roots) == 1
        except Exception:
            single = False
        if not single: raise _root_required('ROOT_COUNT_INVALID', ctx)
        try:
            uri = urlsplit(str(roots[0].uri))
            valid_uri = uri.scheme == 'file' and uri.netloc in ('','localhost') and not uri.query and not uri.fragment
        except Exception:
            valid_uri = False
        if not valid_uri: raise _root_required('ROOT_URI_INVALID', ctx) from None
        try:
            path = Path(unquote(uri.path))
            valid_path = path.is_absolute() and '..' not in path.parts and path.is_dir()
        except Exception:
            valid_path = False
        if not valid_path: raise _root_required('ROOT_PATH_INVALID', ctx) from None
        try:
            owner = ctx.lifespan_context.get('mission_relay')
        except Exception:
            owner = None
        if owner is None:
            raise _root_required('OWNER_LIFESPAN_UNAVAILABLE', ctx, owner_state='ABSENT')
        if getattr(owner, 'closed', True):
            raise _root_required('OWNER_LIFESPAN_UNAVAILABLE', ctx, owner_state='CLOSED')
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
            for logger in (logging.getLogger(), *tuple(logging.Logger.manager.loggerDict.values())):
                if isinstance(logger, logging.Logger):
                    for handler in logger.handlers:
                        if not any(isinstance(item, _CallerSecretFilter) for item in handler.filters):
                            handler.addFilter(_CallerSecretFilter())
            if scope.components is None:
                try:
                    scope.components = self.compose(scope)
                    scope.runtime = self.runtime_for_scope(scope, owner)
                except ToolError:
                    raise
                except Exception:
                    raise ToolError('CALLER_COMPOSITION_REFUSED') from None
            try:
                return await call_next(context)
            except ToolError:
                raise
            except Exception:
                # The outer transport logs after this scoped context has been reset.
                raise ToolError('CALLER_OPERATION_REFUSED') from None
        finally:
            current_caller_storage.reset(token)
