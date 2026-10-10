"""Host-owned private call accounting and disposable provider payload retention.

This store owns no canonical evidence, grants, source identities or scheduled work.
"""

from collections.abc import MutableMapping
from contextlib import contextmanager
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from uuid import uuid4

from ignis.application.ports.follow_up_execution_port import FollowUpExecutionBoundaryError
from ignis.domain.entities import TrendSignal
from ignis.domain.follow_up_admission import digest
from ignis.domain.value_objects import GeoCode, PlatformType


class PrivateRunStorage:
    """Explicit create/reopen; authorization callbacks are supplied by the trusted host."""

    def __init__(self, root, *, authorize, create=False):
        self.root = Path(root)
        self.authorize = authorize
        if not callable(authorize) or self.root.is_symlink():
            raise FollowUpExecutionBoundaryError()
        if create:
            if authorize("create", None, None) is not True:
                raise FollowUpExecutionBoundaryError()
            self.root.mkdir(parents=True, exist_ok=True)
            if any(self.root.iterdir()):
                raise FollowUpExecutionBoundaryError()
        self.path = self.root / "private-run.sqlite3"
        self._creating = create
        if not create and (not self.path.is_file() or self.path.is_symlink()):
            raise FollowUpExecutionBoundaryError()
        if create:
            with self._connection() as connection:
                connection.executescript("""
                    CREATE TABLE runs (id TEXT PRIMARY KEY, bounds TEXT NOT NULL,
                        expiry TEXT NOT NULL, searches INTEGER NOT NULL DEFAULT 0,
                        others INTEGER NOT NULL DEFAULT 0, closed INTEGER NOT NULL DEFAULT 0,
                        purged INTEGER NOT NULL DEFAULT 0);
                    CREATE TABLE registrations (id TEXT PRIMARY KEY, bounds TEXT NOT NULL);
                    CREATE TABLE cache (run TEXT NOT NULL, binding TEXT NOT NULL,
                        key TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(run,binding,key));
                    CREATE TABLE artifacts (run TEXT NOT NULL, name TEXT PRIMARY KEY,
                        hash TEXT NOT NULL);
                    CREATE TABLE audit (run TEXT PRIMARY KEY, bounds TEXT NOT NULL,
                        purged_at TEXT NOT NULL, caches INTEGER NOT NULL, artifacts INTEGER NOT NULL);
                """)
        self._creating = False
        # A missing or altered schema is not initial registration.
        with self._connection() as connection:
            connection.execute("SELECT id,bounds,expiry,searches,others,closed,purged FROM runs LIMIT 0")
            connection.execute("SELECT id,bounds FROM registrations LIMIT 0")
            connection.execute("SELECT run,binding,key,payload FROM cache LIMIT 0")
            connection.execute("SELECT run,name,hash FROM artifacts LIMIT 0")
            connection.execute("SELECT run,bounds,purged_at,caches,artifacts FROM audit LIMIT 0")

    @contextmanager
    def _connection(self):
        connection = None
        try:
            if self.path.is_symlink() or self.root.is_symlink() or (not self._creating and not self.path.is_file()):
                raise FollowUpExecutionBoundaryError()
            connection = sqlite3.connect(self.path, timeout=2)
            connection.execute("PRAGMA secure_delete=ON")
            connection.execute("PRAGMA journal_mode=DELETE")
            connection.execute("PRAGMA synchronous=FULL")
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            if connection is not None:
                connection.rollback()
            raise FollowUpExecutionBoundaryError() from None
        finally:
            if connection is not None:
                connection.close()

    def _row(self, connection, bounds, *, active=True):
        row = connection.execute("SELECT bounds,expiry,searches,others,closed,purged FROM runs WHERE id=?",
                                 (str(bounds.run_id),)).fetchone()
        if row is None or row[0] != digest(bounds) or row[1] != bounds.retention_until.isoformat():
            raise FollowUpExecutionBoundaryError()
        registration = connection.execute("SELECT bounds FROM registrations WHERE id=?", (str(bounds.run_id),)).fetchone()
        if registration != (digest(bounds),):
            raise FollowUpExecutionBoundaryError()
        if any(type(value) is not int or value < 0 for value in row[2:]):
            raise FollowUpExecutionBoundaryError()
        if row[2] > bounds.search_calls or row[3] > bounds.other_calls or (active and (row[4] or row[5])):
            raise FollowUpExecutionBoundaryError()
        return row

    def register(self, bounds):
        """Host attests first registration; an existing row is never replaced/reset."""
        if self.authorize("register", bounds.run_id, digest(bounds)) is not True:
            raise FollowUpExecutionBoundaryError()
        with self._connection() as connection:
            connection.execute("INSERT INTO registrations VALUES(?,?)", (str(bounds.run_id), digest(bounds)))
            connection.execute("INSERT INTO runs(id,bounds,expiry) VALUES(?,?,?)",
                               (str(bounds.run_id), digest(bounds), bounds.retention_until.isoformat()))

    def reopen(self, bounds):
        if self.authorize("reopen", bounds.run_id, digest(bounds)) is not True:
            raise FollowUpExecutionBoundaryError()
        with self._connection() as connection:
            self._row(connection, bounds)

    def current(self, bounds):
        with self._connection() as connection:
            self._row(connection, bounds)
        return True

    def counts(self, bounds):
        with self._connection() as connection:
            row = self._row(connection, bounds, active=False)
        return {"search": row[2], "other": row[3]}

    def charge(self, bounds, bucket, now):
        if bucket not in ("search", "other") or not bounds.started_at <= now < bounds.deadline:
            raise FollowUpExecutionBoundaryError()
        with self._connection() as connection:
            row = self._row(connection, bounds)
            index, limit, column = (2, bounds.search_calls, "searches") if bucket == "search" else (3, bounds.other_calls, "others")
            if row[index] >= limit:
                raise FollowUpExecutionBoundaryError()
            connection.execute(f"UPDATE runs SET {column}={column}+1 WHERE id=?", (str(bounds.run_id),))

    def close(self, bounds):
        with self._connection() as connection:
            self._row(connection, bounds, active=False)
            connection.execute("UPDATE runs SET closed=1 WHERE id=?", (str(bounds.run_id),))

    def cache(self, bounds, binding):
        return _ProviderCache(self, bounds, binding)

    def write_artifact(self, bounds, content):
        """Register only generated private filenames; never enroll arbitrary reports."""
        if type(content) is not bytes or self.authorize("write", bounds.run_id, digest(bounds)) is not True:
            raise FollowUpExecutionBoundaryError()
        name = uuid4().hex + ".payload"
        path = self.root / name
        expected = sha256(content).hexdigest()
        # Enrollment commits before file creation. Interruption of the subsequent writing
        # transaction cannot roll back ownership and strand a payload outside purge scope.
        with self._connection() as connection:
            self._row(connection, bounds)
            connection.execute("INSERT INTO artifacts VALUES(?,?,?)", (str(bounds.run_id), name, expected))
        with self._connection() as connection:
            self._row(connection, bounds)
            enrollment = connection.execute("SELECT run,hash FROM artifacts WHERE name=?", (name,)).fetchone()
            if enrollment != (str(bounds.run_id), expected):
                raise FollowUpExecutionBoundaryError()
            with path.open("xb") as stream:
                stream.write(content)
        return path

    def purge(self, bounds, *, now):
        """Explicit host lifecycle for authorized disposable data; no background deletion."""
        if now < bounds.retention_until or self.authorize("purge", bounds.run_id, digest(bounds)) is not True:
            raise FollowUpExecutionBoundaryError()
        # Persist closure first: failure/crash cannot reopen authority or reset attempts.
        self.close(bounds)
        with self._connection() as connection:
            row = self._row(connection, bounds, active=False)
            if row[5]:
                return self._audit(connection, bounds)
            artifacts = connection.execute("SELECT name,hash FROM artifacts WHERE run=?", (str(bounds.run_id),)).fetchall()
            for name, expected in artifacts:
                if Path(name).name != name or not name.endswith(".payload"):
                    raise FollowUpExecutionBoundaryError()
                path = self.root / name
                if path.is_symlink() or (path.exists() and sha256(path.read_bytes()).hexdigest() != expected):
                    raise FollowUpExecutionBoundaryError()
            for name, _ in artifacts:
                (self.root / name).unlink(missing_ok=True)
            count = connection.execute("SELECT COUNT(*) FROM cache WHERE run=?", (str(bounds.run_id),)).fetchone()[0]
            connection.execute("DELETE FROM cache WHERE run=?", (str(bounds.run_id),))
            connection.execute("DELETE FROM artifacts WHERE run=?", (str(bounds.run_id),))
            connection.execute("UPDATE runs SET purged=1 WHERE id=?", (str(bounds.run_id),))
            connection.execute("INSERT INTO audit VALUES(?,?,?,?,?)", (str(bounds.run_id), digest(bounds), now.isoformat(), count, len(artifacts)))
            return self._audit(connection, bounds)

    def _audit(self, connection, bounds):
        return connection.execute("SELECT bounds,purged_at,caches,artifacts FROM audit WHERE run=?", (str(bounds.run_id),)).fetchone()


class DurableRunCallBudget:
    """Callable bridge budget backed by original immutable persistent accounting."""

    def __init__(self, bounds, *, storage, register=False, clock=None):
        from ignis.infrastructure.follow_up_provider_bridge import RunBounds
        if type(bounds) is not RunBounds or type(storage) is not PrivateRunStorage:
            raise FollowUpExecutionBoundaryError()
        self.bounds, self.storage = bounds, storage
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        if register:
            storage.register(bounds)
        else:
            storage.reopen(bounds)

    @property
    def _used(self):
        return self.storage.counts(self.bounds)

    def current(self):
        now = self.clock()
        return self.bounds.started_at <= now < self.bounds.deadline and self.storage.current(self.bounds)

    def charge(self, bucket):
        self.storage.charge(self.bounds, bucket, self.clock())

    def close(self):
        self.storage.close(self.bounds)


class _ProviderCache(MutableMapping):
    """Unrecorded provider signals only, never canonical observations or identities."""

    def __init__(self, storage, bounds, binding):
        self.storage, self.bounds, self.binding = storage, bounds, binding

    def _key(self, key):
        return str(self.bounds.run_id), self.binding, sha256(key.encode()).hexdigest()

    def __getitem__(self, key):
        with self.storage._connection() as connection:
            self.storage._row(connection, self.bounds)
            row = connection.execute("SELECT payload FROM cache WHERE run=? AND binding=? AND key=?", self._key(key)).fetchone()
        if row is None:
            raise KeyError(key)
        try:
            items = json.loads(row[0])
            return [TrendSignal(platform=PlatformType(item["platform"]), geo_code=GeoCode(item["geo_code"]),
                captured_at=datetime.fromisoformat(item["captured_at"]) if item["captured_at"] else None,
                published_at=datetime.fromisoformat(item["published_at"]) if item["published_at"] else None,
                **{k: item[k] for k in ("raw_title", "metric_value", "growth_velocity", "source_url", "metadata")}) for item in items]
        except Exception:
            raise FollowUpExecutionBoundaryError() from None

    def __setitem__(self, key, signals):
        items = []
        for signal in signals:
            if type(signal) is not TrendSignal or any(getattr(signal, field) is not None for field in
                ("cluster_id", "mission_id", "observation_id", "source_id", "identity_source", "time_provenance")):
                raise FollowUpExecutionBoundaryError()
            items.append(dict(platform=PlatformType(signal.platform).value, geo_code=GeoCode(signal.geo_code).value,
                raw_title=signal.raw_title, metric_value=signal.metric_value, growth_velocity=signal.growth_velocity,
                source_url=signal.source_url, metadata=signal.metadata,
                captured_at=signal.captured_at.isoformat() if signal.captured_at else None,
                published_at=signal.published_at.isoformat() if signal.published_at else None))
        payload = json.dumps(items, ensure_ascii=False)
        with self.storage._connection() as connection:
            self.storage._row(connection, self.bounds)
            connection.execute("INSERT OR REPLACE INTO cache VALUES(?,?,?,?)", (*self._key(key), payload))

    def __delitem__(self, key):
        raise FollowUpExecutionBoundaryError()

    def __iter__(self):
        raise FollowUpExecutionBoundaryError()

    def __len__(self):
        raise FollowUpExecutionBoundaryError()
