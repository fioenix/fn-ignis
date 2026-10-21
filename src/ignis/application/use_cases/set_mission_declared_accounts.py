"""Declare the accounts one mission may name: the only author identity Ignis keeps (Spec 015, R8).

A requester names a brand's or a competitor's own account for one mission. Content from it that
is collected after the declaration is attributed to it by the declared name; every other author
stays a per-mission marker. The call replaces the mission's whole set, and an empty list withdraws
every declaration.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence

from ignis.application.ports.repository_port import ITrendRepository
from ignis.application.ports.research_workspace_port import IResearchWorkspaceStore
from ignis.domain.author_identity import DeclaredAccount, normalise_account_key
from ignis.domain.value_objects import resolve_platform

APPLIES_FROM = "Content collected after declared_at; earlier observations are not re-attributed."


class SetMissionDeclaredAccountsUseCase:
    def __init__(self, repository: ITrendRepository, store: Optional[IResearchWorkspaceStore] = None):
        self._repo = repository
        self._store = store

    async def execute(self, mission_id: str, accounts: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
        mission = await self._repo.get_mission(mission_id)
        if mission is None:
            return {
                "status": "NOT_FOUND",
                "mission_id": str(mission_id),
                "error": f"No research mission found with ID or shortcode '{mission_id}'.",
            }
        base = {"mission_id": str(mission.id), "shortcode": mission.shortcode}
        if (
            self._store is not None
            and mission.workspace_id is not None
            and await self._store.get_research_workspace(mission.workspace_id) is None
        ):
            return self._refused(
                base, "BLOCKED", "WORKSPACE_SCOPE",
                "The mission names a research workspace the configured database does not hold.",
            )
        try:
            entries = self._entries(accounts)
        except ValueError as exc:
            return self._refused(base, "INVALID", "INVALID_REQUEST", str(exc))

        stored, withdrawn = await self._repo.replace_mission_declared_accounts(mission.id, entries)
        return {
            **base,
            "status": "RECORDED",
            "accounts": [self._payload(account) for account in stored],
            "withdrawn": withdrawn,
            "applies_from": APPLIES_FROM,
        }

    @staticmethod
    def _entries(accounts: Sequence[Mapping[str, Any]]) -> List[tuple]:
        if not isinstance(accounts, (list, tuple)):
            raise ValueError("accounts must be a list; an empty list withdraws every declaration.")
        entries, seen = [], set()
        for item in accounts:
            if not isinstance(item, Mapping):
                raise ValueError("Every declared account must be an object.")
            try:
                platform = resolve_platform(item.get("platform")).value
            except ValueError as exc:
                raise ValueError(f"Unknown platform: {item.get('platform')!r}.") from exc
            key = normalise_account_key(item.get("account"))
            name = str(item.get("declared_name") or "").strip()
            if key is None or not name:
                raise ValueError("Every declared account needs an account and a declared_name.")
            if (platform, key) in seen:
                raise ValueError(f"{platform} account '{key}' is declared more than once.")
            seen.add((platform, key))
            entries.append((platform, key, name))
        return entries

    @staticmethod
    def _payload(account: DeclaredAccount) -> Dict[str, Any]:
        return {
            "id": account.id,
            "platform": account.platform,
            "account": account.account_key,
            "declared_name": account.declared_name,
            "declared_at": account.declared_at.isoformat(),
        }

    @staticmethod
    def _refused(base: Dict[str, Any], status: str, reason_code: str, error: str) -> Dict[str, Any]:
        return {**base, "status": status, "reason_code": reason_code, "error": error}
