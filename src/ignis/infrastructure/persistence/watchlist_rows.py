"""Rows of the sql/032 watchlist tables as domain records, shared by both backends (Spec 016)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Iterable, Optional, Sequence

from ignis.domain.watchlist import (
    Watchlist,
    WatchlistDefinition,
    WatchlistRun,
    WatchlistVersion,
    parse_watchlist_definition,
)


def _time(value: Any) -> datetime:
    moment = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def definition_json(definition: WatchlistDefinition) -> str:
    return json.dumps(definition.to_payload(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def watchlist_from_rows(
    head: Optional[Sequence[Any]], versions: Iterable[Sequence[Any]], runs: Iterable[Sequence[Any]]
) -> Optional[Watchlist]:
    """head: (id, workspace_id, name, created_at); versions: (version, definition, created_at);
    runs: (mission_id, version, started_at, mission status)."""
    if head is None:
        return None
    parsed = tuple(
        WatchlistVersion(
            int(version),
            parse_watchlist_definition(definition if isinstance(definition, dict) else json.loads(definition)),
            _time(created_at),
        )
        for version, definition, created_at in versions
    )
    return Watchlist(
        id=str(head[0]),
        workspace_id=str(head[1]),
        name=head[2],
        created_at=_time(head[3]),
        versions=parsed,
        runs=tuple(
            WatchlistRun(str(mission_id), int(version), _time(started_at), status)
            for mission_id, version, started_at, status in runs
        ),
    )


WATCHLIST_HEAD_SQL = "SELECT id, workspace_id, name, created_at FROM watchlists WHERE id = {p}"
WATCHLIST_VERSIONS_SQL = (
    "SELECT version, definition, created_at FROM watchlist_versions WHERE watchlist_id = {p} ORDER BY version"
)
WATCHLIST_RUNS_SQL = (
    "SELECT r.mission_id, r.version, r.started_at, m.status FROM watchlist_runs r"
    " JOIN research_missions m ON m.id = r.mission_id"
    " WHERE r.watchlist_id = {p} ORDER BY r.started_at, r.mission_id"
)
