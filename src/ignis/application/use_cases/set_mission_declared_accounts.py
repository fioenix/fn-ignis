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
from ignis.domain.author_identity import DeclaredAccount, account_in_link, normalise_account_key
from ignis.domain.value_objects import PlatformType

APPLIES_FROM = "Content collected after declared_at; earlier observations are not re-attributed."
# The platforms whose content has an account behind it; a Google Trends keyword has none.
ACCOUNT_PLATFORMS = frozenset(platform.value for platform in PlatformType if platform is not PlatformType.GOOGLE_TRENDS)
MAX_DECLARED_ACCOUNTS = 50
MAX_ACCOUNT_LENGTH = 100
MAX_DECLARED_NAME_LENGTH = 120


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
    def _account_key(value: Any) -> str:
        """A handle or account id as stored; a profile link becomes the handle it names."""
        if not isinstance(value, str):
            raise ValueError("Every account must be a handle, an account id or a profile link.")
        key = account_in_link(value) if ("/" in value or "://" in value) else normalise_account_key(value)
        if not key:
            raise ValueError("A link that names no account cannot be declared.")
        if len(key) > MAX_ACCOUNT_LENGTH or any(character.isspace() for character in key):
            raise ValueError("An account is a handle or an account id, without spaces.")
        return key

    @classmethod
    def _entries(cls, accounts: Sequence[Mapping[str, Any]]) -> List[tuple]:
        if not isinstance(accounts, (list, tuple)):
            raise ValueError("accounts must be a list; an empty list withdraws every declaration.")
        if len(accounts) > MAX_DECLARED_ACCOUNTS:
            raise ValueError(f"A mission declares at most {MAX_DECLARED_ACCOUNTS} accounts.")
        entries, seen = [], set()
        for item in accounts:
            if not isinstance(item, Mapping):
                raise ValueError("Every declared account must be an object.")
            platform = str(item.get("platform") or "").strip().lower()
            if platform not in ACCOUNT_PLATFORMS:
                raise ValueError(f"Accounts can be declared only on: {', '.join(sorted(ACCOUNT_PLATFORMS))}.")
            key = cls._account_key(item.get("account"))
            name = str(item.get("declared_name") or "").strip()
            if not name or len(name) > MAX_DECLARED_NAME_LENGTH:
                raise ValueError(f"Every declared account needs a declared_name of at most {MAX_DECLARED_NAME_LENGTH} characters.")
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
