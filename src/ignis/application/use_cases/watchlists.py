"""Watchlists a user follows across runs, and the runs that collect them (Spec 016, US1).

A watchlist is saved as immutable versions. A run is an ordinary Attention mission bound to the
current version: its keywords are the version's keywords and brand names, and its brands become
the mission's declared accounts (Spec 015). Collection then goes through the existing ingress.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Mapping, Optional
from uuid import UUID

from ignis.application.ports.repository_port import ITrendRepository
from ignis.application.ports.research_workspace_port import IResearchWorkspaceStore
from ignis.application.use_cases.create_attention_mission import CreateAttentionMissionUseCase
from ignis.application.use_cases.set_mission_declared_accounts import SetMissionDeclaredAccountsUseCase
from ignis.domain.exceptions import IgnisDomainException
from ignis.domain.research_workspace import MissionManifest, MissionOutputType
from ignis.domain.watchlist import (
    Watchlist,
    ListeningPlan,
    plan_in_effect,
    WatchlistConflict,
    WatchlistDefinitionError,
    parse_watchlist_definition,
    watchlist_name,
    watchlist_name_key,
)

RUN_STOP_CONDITION = "Stop after one collection pass over the watchlist version's keywords and brands."
RUN_RETENTION = "Kept as watchlist history; removable after 13 months by an explicit retention action."


def _refused(status: str, reason_code: str, error: str, **extra: Any) -> Dict[str, Any]:
    return {**extra, "status": status, "reason_code": reason_code, "error": error}


def _uuid(value: Any) -> Optional[UUID]:
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None


def watchlist_payload(watchlist: Watchlist) -> Dict[str, Any]:
    return {
        "watchlist_id": watchlist.id,
        "workspace_id": watchlist.workspace_id,
        "name": watchlist.name,
        "created_at": watchlist.created_at.isoformat(),
        "current_version": watchlist.current.version,
        "versions": [
            {
                "version": v.version,
                "definition": v.definition.to_payload(),
                "definition_digest": v.definition.digest,
                "created_at": v.created_at.isoformat(),
            }
            for v in watchlist.versions
        ],
        "runs": [
            {
                "mission_id": r.mission_id,
                "version": r.version,
                "started_at": r.started_at.isoformat(),
                "mission_status": r.mission_status,
            }
            for r in watchlist.runs
        ],
    }


class SaveWatchlistUseCase:
    def __init__(self, repository: ITrendRepository, store: IResearchWorkspaceStore):
        self._repo = repository
        self._store = store

    async def execute(
        self, workspace_id: Any, name: Any, definition: Any, watchlist_id: Any = None
    ) -> Dict[str, Any]:
        workspace = _uuid(workspace_id)
        clean_name = watchlist_name(name)
        if workspace is None or clean_name is None:
            return _refused("INVALID", "INVALID_DEFINITION", "A watchlist needs a workspace_id UUID and a name.")
        try:
            parsed = parse_watchlist_definition(definition)
        except WatchlistDefinitionError as exc:
            return _refused("INVALID", exc.code, str(exc))
        if await self._store.get_research_workspace(workspace) is None:
            return _refused(
                "BLOCKED", "WORKSPACE_SCOPE",
                "The configured database holds no confirmed research workspace with this id.",
            )

        if watchlist_id is None:
            try:
                saved = await self._repo.create_watchlist(workspace, clean_name, parsed)
            except WatchlistConflict as exc:
                return _refused("CONFLICT", exc.code, str(exc))
            return self._result("CREATED", saved)

        target = _uuid(watchlist_id)
        existing = await self._repo.get_watchlist(target) if target else None
        if existing is None:
            return _refused("NOT_FOUND", "NOT_FOUND", "No watchlist has this id.", watchlist_id=str(watchlist_id))
        if existing.workspace_id != str(workspace):
            return _refused("BLOCKED", "WORKSPACE_SCOPE", "The watchlist belongs to another workspace.")
        if watchlist_name_key(existing.name) != watchlist_name_key(clean_name):
            return _refused("INVALID", "NAME_MISMATCH", "A revision keeps the watchlist's name; renaming is not supported.")
        try:
            saved, added = await self._repo.add_watchlist_version(target, parsed)
        except WatchlistConflict as exc:
            return _refused("NOT_FOUND", exc.code, str(exc), watchlist_id=str(watchlist_id))
        return self._result("VERSION_ADDED" if added else "UNCHANGED", saved)

    @staticmethod
    def _result(status: str, watchlist: Watchlist) -> Dict[str, Any]:
        return {
            "status": status,
            "watchlist_id": watchlist.id,
            "version": watchlist.current.version,
            "definition_digest": watchlist.current.definition.digest,
        }


class GetWatchlistUseCase:
    def __init__(self, repository: ITrendRepository):
        self._repo = repository

    async def execute(self, watchlist_id: Any) -> Dict[str, Any]:
        target = _uuid(watchlist_id)
        if target is None:
            return _refused("INVALID", "INVALID_REQUEST", "watchlist_id must be a UUID.")
        watchlist = await self._repo.get_watchlist(target)
        if watchlist is None:
            return _refused("NOT_FOUND", "NOT_FOUND", "No watchlist has this id.", watchlist_id=str(target))
        plans = await self._repo.list_listening_plans(target)
        return {"status": "FOUND", **watchlist_payload(watchlist), **listening_plan_payload(plans)}


def listening_plan_payload(plans) -> Dict[str, Any]:
    current = plan_in_effect(plans, datetime.now(timezone.utc))
    return {"listening_plans": [plan.to_payload() for plan in plans],
            "listening_plan": current.to_payload() if current else None}


class SetWatchlistListeningPlanUseCase:
    def __init__(self, repository: ITrendRepository):
        self._repo = repository

    async def execute(self, watchlist_id: Any, goal: Any, period_kind: Any,
                      snapshots_per_period: Any) -> Dict[str, Any]:
        target = _uuid(watchlist_id)
        if target is None:
            return _refused("INVALID", "INVALID_REQUEST", "watchlist_id must be a UUID.")
        try:
            # Validate before reaching the store; the store also guards direct callers.
            plan = ListeningPlan(datetime.now(timezone.utc), goal, period_kind, snapshots_per_period)
            plans, added = await self._repo.save_listening_plan(
                target, plan.goal, plan.period_kind, plan.snapshots_per_period)
        except WatchlistDefinitionError as exc:
            return _refused("INVALID", exc.code, str(exc), watchlist_id=str(target))
        except WatchlistConflict as exc:
            return _refused("NOT_FOUND", exc.code, str(exc), watchlist_id=str(target))
        return {"status": "SAVED" if added else "UNCHANGED", "watchlist_id": str(target),
                **listening_plan_payload(plans)}


class StartWatchlistRunUseCase:
    def __init__(self, repository: ITrendRepository, store: IResearchWorkspaceStore,
                 create_attention: CreateAttentionMissionUseCase):
        self._repo = repository
        self._store = store
        self._create_attention = create_attention

    async def execute(
        self,
        watchlist_id: Any,
        authority: Mapping[str, Any],
        build_manifest: Callable[[Dict[str, Any]], MissionManifest],
        **mission_options: Any,
    ) -> Dict[str, Any]:
        """authority: allowed_resources, authority_boundary and quota_budget, stated by the caller
        for every run; build_manifest turns the full request into the confirmed manifest."""
        target = _uuid(watchlist_id)
        watchlist = await self._repo.get_watchlist(target) if target else None
        if watchlist is None:
            return _refused("NOT_FOUND", "NOT_FOUND", "No watchlist has this id.", watchlist_id=str(watchlist_id))
        version = watchlist.current
        try:
            manifest = build_manifest({**run_manifest_payload(watchlist.name, version.version), **authority})
            mission = await self._create_attention.execute(
                workspace_id=UUID(watchlist.workspace_id),
                title=f"{watchlist.name} (watchlist version {version.version})",
                manifest=manifest,
                keywords=run_keywords(version.definition),
                **mission_options,
            )
        except (IgnisDomainException, ValueError) as exc:
            return _refused("INVALID", "INVALID_REQUEST", str(exc), watchlist_id=watchlist.id)
        try:
            await self._repo.record_watchlist_run(mission.id, UUID(watchlist.id), version.version)
            declared = await SetMissionDeclaredAccountsUseCase(self._repo, self._store).execute(
                str(mission.id), run_brands(version.definition)
            )
        except Exception as exc:
            # The mission exists but belongs to no watchlist, or declares no brand; report it rather
            # than hand back a run that would collect brand content without attribution.
            return _refused(
                "FAILED", "RUN_NOT_BOUND",
                f"Mission {mission.shortcode} was created but could not be bound to the watchlist"
                f" ({type(exc).__name__}); do not run ingress for it.",
                watchlist_id=watchlist.id, mission_id=str(mission.id),
            )
        return {
            "status": "CREATED",
            "watchlist_id": watchlist.id,
            "version": version.version,
            "mission_id": str(mission.id),
            "shortcode": mission.shortcode,
            "keywords": mission.keywords,
            # A refused declaration leaves every author anonymous, which fails safe but is reported.
            "declared_accounts_status": declared.get("status"),
            "declared_accounts": declared.get("accounts", []),
            "next_step": f"Call execute_mission_ingress(mission_id='{mission.shortcode}').",
        }


def run_keywords(definition) -> List[str]:
    """Every topic's keywords, then every brand's declared name, each once ignoring case, in first-seen order."""
    terms: Dict[str, str] = {}
    for topic in definition.topics:
        for keyword in topic.keywords:
            terms.setdefault(keyword.casefold(), keyword)
    for topic in definition.topics:
        for brand in topic.brands:
            terms.setdefault(brand.declared_name.casefold(), brand.declared_name)
    return list(terms.values())


def run_brands(definition) -> List[Mapping[str, str]]:
    """Each brand account once, under the first name the watchlist gives it."""
    accounts: Dict[tuple, Mapping[str, str]] = {}
    for topic in definition.topics:
        for brand in topic.brands:
            accounts.setdefault((brand.platform, brand.account), brand.to_payload())
    return list(accounts.values())


def run_manifest_payload(name: str, version: int) -> Dict[str, Any]:
    """The parts of a run's manifest that follow from the watchlist; authority stays the caller's."""
    return {
        "requested_outcome": f"Collect watchlist '{name}' version {version} once.",
        "output_type": MissionOutputType.COLLECTION_FRAME.value,
        "stop_conditions": [RUN_STOP_CONDITION],
        "retention_policy": RUN_RETENTION,
    }
