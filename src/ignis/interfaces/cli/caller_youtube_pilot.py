"""Finite local YouTube pilot run for one confirmed caller mission.

The trusted host's direct, bounded invocation of this command is the source-use origin. The
packet and confirmation files are constraints and audit inputs, never automatic grants. Queries,
budgets, window and retention come only from the confirmed packet; there are no flags for them.
One original run is allocated per mission; any later invocation refuses instead of starting a new
run, renewing time or resetting counts. Caller data persists until explicit user deletion.
"""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
from uuid import UUID, uuid4


class _Refused(Exception):
    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


def _load_constraints(packet_path, confirmation_path):
    from ignis.infrastructure.follow_up_root_composition import validate_brief_confirmation
    try:
        packet_bytes = Path(packet_path).read_bytes()
        confirmation = json.loads(Path(confirmation_path).read_text())
        if hashlib.sha256(packet_bytes).hexdigest() != confirmation['packet_sha256']:
            raise ValueError
        packet = json.loads(packet_bytes)
        brief, instruction = packet['payload'], packet['collection_instruction']
        validate_brief_confirmation(brief, confirmation['receipt'], instruction)
    except (OSError, ValueError, KeyError, TypeError):
        raise _Refused('EXACT_CONFIRMED_PACKET_REQUIRED') from None
    return brief, instruction


def _scope(root):
    """Non-provisioning checked caller scope; aliases, replacements and config drift refuse."""
    from ignis.infrastructure.caller_storage import CallerStorageScope
    root = Path(root).absolute()
    store = root / '.fnignis' / 'canonical.sqlite3'
    if root.is_symlink() or (root / '.fnignis').is_symlink() or store.is_symlink():
        raise _Refused('CALLER_SCOPE_REFUSED')
    if not (root / '.fnignis').is_dir() or not store.is_file():
        raise _Refused('CALLER_STORE_REQUIRED')
    try:
        scope = CallerStorageScope(root)
        scope.check()
    except Exception:
        raise _Refused('CALLER_SCOPE_REFUSED') from None
    if scope.database != store:
        raise _Refused('CALLER_SCOPE_REFUSED')
    return root, scope


def _checked(scope, path):
    try:
        return scope.check_path(path)
    except Exception:
        raise _Refused('CALLER_SCOPE_REFUSED') from None


def _publish(scope, path, payload):
    """Checked atomic publication of a replaceable run output file."""
    import os
    _checked(scope, path)
    temporary = path.with_name('.' + path.name + '.' + uuid4().hex + '.tmp')
    with temporary.open('x') as stream:
        stream.write(json.dumps(payload, sort_keys=True))
    try:
        _checked(scope, path)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _decoded(value):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return value
    return value


_PARENT_PROGRESS_TABLES = frozenset({'mission_progress_revisions', 'mission_progress_events',
                                     'mission_progress_commands'})


async def _preflight(store, mission_id, brief, instruction, root, scope):
    """Read-only checks on the existing caller store; no schema initialization or write."""
    import sqlite3
    import tempfile
    from ignis.infrastructure.persistence.sqlite_repository import SqliteTrendRepository
    with tempfile.TemporaryDirectory() as directory:
        reference = SqliteTrendRepository(str(Path(directory) / 'reference.sqlite3'))
        await reference._ensure_schema()
        await reference.close()
        with sqlite3.connect(Path(directory, 'reference.sqlite3').as_uri() + '?mode=ro', uri=True) as connection:
            required = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    try:
        connection = sqlite3.connect(store.as_uri() + '?mode=ro', uri=True)
    except sqlite3.Error:
        raise _Refused('CALLER_STORE_REQUIRED') from None
    try:
        present = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not required <= present:
            raise _Refused('CALLER_SCHEMA_INCOMPLETE')
        # The parent writer records progress; it must already exist, never be created during a run.
        # Optional child workflow tables are not required for a parent-only run.
        if not _PARENT_PROGRESS_TABLES <= present:
            raise _Refused('CALLER_PARENT_PROGRESS_SCHEMA_REQUIRED')
        mission = connection.execute('SELECT status, keywords, platforms, geo_code, timeframe, workspace_id, '
            'brief_revision_id FROM research_missions WHERE id=?', (str(mission_id),)).fetchone()
        if mission is None:
            raise _Refused('CONFIRMED_CALLER_MISSION_REQUIRED')
        fields = ('decision', 'target_user', 'problem', 'geo', 'timeframe', 'hypothesis', 'falsifiers',
                  'alternative_hypotheses', 'null_hypothesis', 'kill_criteria', 'revision_rule')
        revision = connection.execute('SELECT ' + ', '.join(fields) + ', workspace_id FROM market_brief_revisions '
            'WHERE id=? AND mission_id=?', (mission[6], str(mission_id))).fetchone()
        manifest = connection.execute('SELECT required_channels, optional_channels, authority_boundary, '
            'quota_budget, retention_policy, analysis_policy FROM mission_manifests WHERE mission_id=?',
            (str(mission_id),)).fetchone()
        workspace = connection.execute('SELECT root_path, status FROM research_workspaces WHERE id=?',
                                       (mission[5],)).fetchone() if mission[5] else None
    except sqlite3.Error:
        raise _Refused('CALLER_SCHEMA_INCOMPLETE') from None
    finally:
        connection.close()
    if revision is None or manifest is None or workspace is None:
        raise _Refused('CONFIRMED_CALLER_MISSION_REQUIRED')
    if any(_decoded(revision[index]) != brief[name] for index, name in enumerate(fields)) or revision[11] != mission[5]:
        raise _Refused('CONFIRMED_BRIEF_MISMATCH')
    boundary = _decoded(manifest[2]) or {}
    research = root / '.fnignis' / 'research'
    workspace_root = Path(workspace[0])
    if not workspace_root.is_absolute() or research not in workspace_root.parents:
        raise _Refused('CONFIRMED_SCOPE_MISMATCH')
    # Lexical containment plus pinned, symlink-free ancestry; pinning the manifest path also pins
    # the admitted workspace directory itself, so a later replacement or alias refuses.
    _checked(scope, workspace_root / 'workspace.json')
    if (_decoded(mission[1]) != instruction['queries'][:1] or _decoded(mission[2]) != ['youtube']
            or mission[3] != 'VN' or mission[4] != '30d' or _decoded(manifest[0]) != ['youtube']
            or _decoded(manifest[1]) not in ([], None)
            or boundary != {'public_http': False, 'official_api': True, 'browser_session': False, 'paid_quota': False}
            or _decoded(manifest[3]) != {'queries': instruction['search_calls'], 'youtube_search_calls': instruction['search_calls']}
            or manifest[4] != 'caller-retained-until-explicit-user-deletion' or manifest[5] != 'evidence-gated-v1'
            ):
        raise _Refused('CONFIRMED_SCOPE_MISMATCH')
    if mission[0] != 'PENDING':
        raise _Refused('PARENT_NOT_UNEXECUTED')
    return workspace_root


async def _run(args, *, transport, resolve_credential):
    from datetime import datetime, timezone
    import httpx
    from ignis.application.use_cases.execute_mission import ExecuteMissionUseCase
    from ignis.application.youtube_quota import YouTubeQuotaManager
    from ignis.domain.youtube_quota import YouTubeQuotaPolicy
    from ignis.infrastructure.clustering.semantic_clusterer import SemanticClusterer
    from ignis.infrastructure.connectors.registry import ConnectorPluginRegistry
    from ignis.infrastructure.follow_up_caller_activation import CallerSourceActivation
    from ignis.infrastructure.follow_up_host_activation import RootHostController
    from ignis.infrastructure.follow_up_provider_bridge import HostBoundYouTubePlugin, HostProviderBridge
    from ignis.infrastructure.follow_up_root_composition import _close_accounting, confirmation_at_approved_invocation
    from ignis.infrastructure.follow_up_run_storage import DurableRunCallBudget, PrivateRunStorage
    from ignis.infrastructure.persistence.sqlite_repository import SqliteTrendRepository
    from ignis.infrastructure.persistence.workspace_repository import WorkspaceRepository
    root, scope = _scope(args.caller_root)
    store_path = scope.database
    try:
        mission_id = UUID(args.mission_id)
    except ValueError:
        raise _Refused('MISSION_ID_REQUIRED') from None
    brief, instruction = _load_constraints(args.packet, args.confirmation)
    run_root = root / '.fnignis' / 'follow-up' / str(mission_id)
    if run_root.exists() or run_root.is_symlink():
        # The original run exists; completed, expired or uncertain runs are never replaced.
        raise _Refused('ORIGINAL_RUN_ALREADY_ALLOCATED')
    workspace_root = await _preflight(store_path, mission_id, brief, instruction, root, scope)
    follow = root / '.fnignis' / 'follow-up'
    _checked(scope, follow / 'probe')
    follow.mkdir(exist_ok=True)
    _checked(scope, run_root / 'probe')
    try:
        # Exclusive creation: exactly one concurrent invocation allocates the original run.
        run_root.mkdir()
    except FileExistsError:
        raise _Refused('ORIGINAL_RUN_ALREADY_ALLOCATED') from None
    owned = {}
    repository = None
    try:
        confirmation = confirmation_at_approved_invocation(instruction, mission_id=mission_id, run_id=uuid4())
        bounds = confirmation.bounds
        marker = run_root / 'run.json'
        _checked(scope, marker)
        marker.write_text(json.dumps({'run_id': str(bounds.run_id),
            'started_at': bounds.started_at.isoformat(), 'deadline': bounds.deadline.isoformat(),
            'queries': list(bounds.queries), 'video_limit': bounds.video_limit, 'search_calls': bounds.search_calls,
            'other_calls': bounds.other_calls, 'retention': instruction['retention'],
            'owner_reference': instruction['reference']}, sort_keys=True, ensure_ascii=False))
        registry = ConnectorPluginRegistry()
        owned['host'] = host = RootHostController(confirmation, registry, scope_path=run_root / 'root-scope.json',
            create=True, clock=lambda: datetime.now(timezone.utc))
        owned['accounting'] = accounting = PrivateRunStorage(run_root / 'accounting',
            authorize=host.authorize_storage, create=True)
        host.enroll_storage(accounting)
        budget = DurableRunCallBudget(bounds, storage=accounting, register=True, clock=host.clock)
        owned['registered'] = True
        identity = accounting.path.stat()
        # Immutable original recovery identity: ledger inode plus the run marker digest.
        recovery = run_root / 'ledger.json'
        _checked(scope, recovery)
        recovery.write_text(json.dumps({'device': identity.st_dev, 'inode': identity.st_ino,
            'run_sha256': hashlib.sha256(marker.read_bytes()).hexdigest()}))
        scope.check()
        repository = SqliteTrendRepository(str(store_path))
        scope.guard_repository(repository)
        def path_guard(path):
            # Revisit the admitted workspace branch before every workspace/journal path use.
            scope.check_path(workspace_root / 'workspace.json')
            return scope.check_path(path)
        store = WorkspaceRepository(repository=repository, path_guard=path_guard)
        if transport is None:
            # Official HTTP transport, owned by this run and created only after preflight and allocation.
            owned['transport'] = transport = httpx.AsyncHTTPTransport()
        bridge = HostProviderBridge(host, budget, selected_parent_id=mission_id)
        plugin = HostBoundYouTubePlugin(bridge=bridge, resolve_credential=resolve_credential, transport=transport,
            quota_manager=YouTubeQuotaManager(repository, YouTubeQuotaPolicy()))
        registry.register(plugin)
        base = ExecuteMissionUseCase(repository=repository, registry=ConnectorPluginRegistry(repository=repository),
            clusterer=SemanticClusterer(), workspace_store=store)
        scope.components = {'repository': repository, 'workspace_store': store, 'execute_mission_use_case': base}
        owned['activation'] = activation = CallerSourceActivation(scope=scope, host=host, bridge=bridge, plugin=plugin)
        result = await activation.run_parent(mission_id)
        return {**result, 'run_id': str(bounds.run_id), 'child_status': 'NOT_ADMITTED_NO_RECORDED_GENUINE_GAP',
            'bounds': {'search_calls': bounds.search_calls, 'other_calls': bounds.other_calls,
                'video_limit': bounds.video_limit, 'run_minutes': instruction['run_minutes'],
                'queries': list(bounds.queries), 'retention': instruction['retention']}}
    finally:
        # Owned settlement: an interrupt during cleanup cannot abandon any phase.
        settlement = asyncio.ensure_future(_settle(owned, run_root, repository, scope))
        cancelled = False
        while not settlement.done():
            try:
                await asyncio.shield(settlement)
            except asyncio.CancelledError:
                cancelled = True
        settlement.result()
        if cancelled:
            # Cancellation first seen during cleanup is re-raised after every phase settled.
            raise asyncio.CancelledError()


async def _settle(owned, run_root, repository, scope):
    """Attempt every allocated cleanup phase independently; record only fixed phase states."""
    from ignis.infrastructure.follow_up_root_composition import _close_accounting
    phases = {'host': 'NOT_ALLOCATED', 'accounting': 'NOT_ALLOCATED', 'transport': 'NOT_ALLOCATED',
              'repository': 'NOT_ALLOCATED', 'receipt': 'PENDING'}
    activation = owned.get('activation')
    if activation is not None:
        try:
            await activation.close()
        except Exception:
            pass
        phases['host'] = 'CLOSED' if activation.revoked else 'PENDING'
        phases['accounting'] = 'CLOSED' if activation.accounting_close == 'CLOSED' else 'PENDING'
    else:
        if 'host' in owned:
            try:
                await owned['host'].revoke()
                phases['host'] = 'CLOSED'
            except Exception:
                phases['host'] = 'PENDING'
        if owned.get('registered'):
            try:
                closure = _close_accounting(owned['accounting'], owned['host'].confirmation.bounds)
            except Exception:
                closure = 'PENDING'
            phases['accounting'] = 'CLOSED' if closure == 'CLOSED' else 'PENDING'
    if 'transport' in owned:
        try:
            await owned['transport'].aclose()
            phases['transport'] = 'CLOSED'
        except Exception:
            phases['transport'] = 'PENDING'
    if repository is not None:
        try:
            await repository.close()
            phases['repository'] = 'CLOSED'
        except Exception:
            phases['repository'] = 'PENDING'
    settled = all(state in ('CLOSED', 'NOT_ALLOCATED') for name, state in phases.items() if name != 'receipt')
    disposition = 'CLOSED' if settled else 'PENDING'
    try:
        phases['receipt'] = 'CLOSED'
        _publish(scope, run_root / 'closure.json', {'disposition': disposition,
            'accounting_close': phases['accounting'], 'phases': phases})
    except Exception:
        phases['receipt'] = 'PENDING'
        disposition = 'PENDING'
    _LAST['closure'] = {'disposition': disposition, 'accounting_close': phases['accounting'], 'phases': phases}
    if owned.get('registered'):
        try:
            _LAST['accounting'] = owned['accounting'].counts(owned['host'].confirmation.bounds)
        except Exception:
            _LAST['accounting'] = None


_LAST = {}


def _close_only(args):
    """Close the original run's ledger only: no host, provider, resolver, transport or new run."""
    from datetime import datetime
    from ignis.infrastructure.follow_up_provider_bridge import RunBounds
    from ignis.infrastructure.follow_up_root_composition import _close_accounting
    from ignis.infrastructure.follow_up_run_storage import PrivateRunStorage
    root, scope = _scope(args.caller_root)
    try:
        mission_id = UUID(args.mission_id)
    except ValueError:
        raise _Refused('MISSION_ID_REQUIRED') from None
    run_root = root / '.fnignis' / 'follow-up' / str(mission_id)
    ledger = run_root / 'accounting' / 'private-run.sqlite3'
    for path in (run_root / 'run.json', run_root / 'ledger.json', run_root / 'closure.json', ledger):
        _checked(scope, path)
    if not ledger.is_file():
        raise _Refused('ORIGINAL_RUN_REQUIRED')
    try:
        marker_bytes = (run_root / 'run.json').read_bytes()
        marker = json.loads(marker_bytes)
        identity = json.loads((run_root / 'ledger.json').read_text())
        if hashlib.sha256(marker_bytes).hexdigest() != identity['run_sha256']:
            raise _Refused('ORIGINAL_RUN_MARKER_MISMATCH')
        bounds = RunBounds(run_id=UUID(marker['run_id']), started_at=datetime.fromisoformat(marker['started_at']),
            deadline=datetime.fromisoformat(marker['deadline']), retention_until=None,
            queries=tuple(marker['queries']), video_limit=marker['video_limit'],
            search_calls=marker['search_calls'], other_calls=marker['other_calls'])
    except (OSError, ValueError, KeyError, TypeError):
        raise _Refused('ORIGINAL_RUN_REQUIRED') from None
    if (ledger.stat().st_dev, ledger.stat().st_ino) != (identity['device'], identity['inode']):
        raise _Refused('ORIGINAL_LEDGER_IDENTITY_MISMATCH')
    scope.check()
    # Closure needs no authorization grant; every authorized operation is refused here.
    storage = PrivateRunStorage(run_root / 'accounting', authorize=lambda *arguments: False)
    closure = _close_accounting(storage, bounds)
    previous = {}
    try:
        recorded = json.loads((run_root / 'closure.json').read_text()).get('phases')
        previous = recorded if isinstance(recorded, dict) else {}
    except (OSError, ValueError):
        pass
    # A missing phase record is UNKNOWN, never inferred closed; only accounting is retried here.
    phases = {name: previous.get(name, 'UNKNOWN') for name in ('host', 'transport', 'repository')}
    phases['accounting'] = closure
    settled = closure == 'CLOSED' and all(state in ('CLOSED', 'NOT_ALLOCATED') for state in phases.values())
    disposition = 'CLOSED' if settled else 'PENDING'
    _publish(scope, run_root / 'closure.json', {'disposition': disposition, 'accounting_close': closure,
        'phases': {**phases, 'receipt': 'CLOSED'}})
    summary = {'status': disposition, 'run_id': str(bounds.run_id), 'phases': phases}
    if closure == 'CLOSED':
        summary['accounting'] = storage.counts(bounds)
    return summary


def main(argv=None, *, transport=None, resolve_credential=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--caller-root', required=True)
    parser.add_argument('--mission-id', required=True)
    parser.add_argument('--packet')
    parser.add_argument('--confirmation')
    parser.add_argument('--close-only', action='store_true',
                        help='Close the original run ledger only; no source call, key use or new run.')
    args = parser.parse_args(argv)
    if args.close_only:
        try:
            summary = _close_only(args)
        except _Refused as refusal:
            print(json.dumps({'status': 'REFUSED', 'reason_code': refusal.reason}))
            return 2
        except Exception as error:
            print(json.dumps({'status': 'FAILED', 'error_type': type(error).__name__}))
            return 1
        print(json.dumps(summary))
        return 0 if summary['status'] == 'CLOSED' else 1
    if not args.packet or not args.confirmation:
        print(json.dumps({'status': 'REFUSED', 'reason_code': 'EXACT_CONFIRMED_PACKET_REQUIRED'}))
        return 2
    if resolve_credential is None:
        from ignis.infrastructure.follow_up_root_composition import deferred_injected_key
        resolve_credential = deferred_injected_key
    try:
        summary = asyncio.run(_run(args, transport=transport, resolve_credential=resolve_credential))
        summary.update(accounting=_LAST.get('accounting'), **_LAST.get('closure', {}))
        if summary.get('disposition') != 'CLOSED':
            print(json.dumps(summary, ensure_ascii=False, default=str))
            return 1
    except _Refused as refusal:
        print(json.dumps({'status': 'REFUSED', 'reason_code': refusal.reason}))
        return 2
    except Exception as error:
        # Provider and storage errors may carry secret-bearing URLs; emit only the safe type.
        print(json.dumps({'status': 'FAILED', 'error_type': type(error).__name__}))
        return 1
    print(json.dumps(summary, ensure_ascii=False, default=str))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
