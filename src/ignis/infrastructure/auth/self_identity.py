"""Discovering which accounts belong to the operator.

The filter in `ignis.domain.self_content` is pure: it needs to be told which accounts are the
operator's own. That knowledge is assembled here from three sources, in order of reliability:

1. `runtime_configs["self_accounts"]` — an explicit map the operator (or an agent) sets, which is
   the only reliable source for browser sessions where no API reports the handle.
2. `platform_credentials.credentials_data` — the OAuth flow already records `user_id`, and some
   flows record `username`.
3. Meta session cookies — an Instagram or Threads browser session carries `ds_user_id`, which
   identifies the logged-in account even when no handle is stored.

Nothing here guesses: a platform with no discoverable identity yields no identity, and the
registry reports that gap instead of pretending the feed is clean.
"""

import json
import logging
from typing import Any, Dict, Iterable, List, Optional

from ignis.domain.self_content import SelfIdentity

logger = logging.getLogger(__name__)

# Runtime config key holding the operator's own accounts, as {"platform": ["handle", ...]}.
SELF_ACCOUNTS_CONFIG_KEY = "self_accounts"
# Cookie that identifies the logged-in account inside a Meta browser session.
META_ACCOUNT_COOKIE = "ds_user_id"
META_PLATFORMS = ("threads", "reels", "instagram")
# A credential is stored per auth flow ("threads_browser", "instagram_browser"), while signals
# carry the platform they came from. One Instagram login also owns the Reels surface.
PLATFORM_ALIASES = {
    "threads": ("threads",),
    "instagram": ("instagram", "reels"),
    "reels": ("reels", "instagram"),
    "tiktok": ("tiktok",),
    "youtube": ("youtube",),
    "google": ("google",),
}


def base_platform(platform: str) -> str:
    """Strip the auth-flow suffix a credential row uses ("threads_browser" -> "threads")."""
    text = str(platform or "").strip().lower()
    for suffix in ("_browser", "_oauth", "_graph", "_session", "_api"):
        if text.endswith(suffix):
            return text[: -len(suffix)]
    return text


def signal_platforms_for(platform: str) -> tuple:
    """Every signal platform a credential for this platform can author content on."""
    base = base_platform(platform)
    return PLATFORM_ALIASES.get(base, (base,))


class SelfIdentityRegistry:
    """Assembles the operator's own account identities from persisted credentials and config."""

    def __init__(self, repository: Any):
        self._repository = repository

    async def load(self, platforms: Optional[Iterable[str]] = None) -> List[SelfIdentity]:
        identities: List[SelfIdentity] = []
        identities.extend(await self._from_runtime_config())

        wanted = [p.strip().lower() for p in (platforms or [])] or None
        for platform in wanted or await self._known_platforms():
            identities.extend(await self._from_credentials(platform))

        unique: Dict[tuple, SelfIdentity] = {}
        for identity in identities:
            if not identity.is_usable:
                continue
            key = (identity.platform, identity.normalized_username, identity.normalized_account_id)
            unique.setdefault(key, identity)
        return list(unique.values())

    async def _known_platforms(self) -> List[str]:
        try:
            credentials = await self._repository.list_platform_credentials()
        except Exception as e:
            logger.warning(f"Could not list platform credentials for self-identity discovery: {e}")
            return []
        return [str(c.get("platform") or "").strip().lower() for c in credentials if c.get("platform")]

    async def _from_runtime_config(self) -> List[SelfIdentity]:
        try:
            raw = await self._repository.get_runtime_config(SELF_ACCOUNTS_CONFIG_KEY)
        except Exception as e:
            logger.warning(f"Could not read {SELF_ACCOUNTS_CONFIG_KEY} runtime config: {e}")
            return []
        if not raw:
            return []
        try:
            mapping = json.loads(raw)
        except (TypeError, ValueError):
            logger.warning(f"{SELF_ACCOUNTS_CONFIG_KEY} is not valid JSON; ignoring it.")
            return []
        if not isinstance(mapping, dict):
            return []

        identities: List[SelfIdentity] = []
        for platform, handles in mapping.items():
            values = handles if isinstance(handles, list) else [handles]
            for handle in values:
                text = str(handle or "").strip()
                if not text:
                    continue
                for target in signal_platforms_for(platform):
                    identities.append(SelfIdentity(
                        platform=target,
                        username=text if not text.isdigit() else None,
                        account_id=text if text.isdigit() else None,
                        source="runtime_config",
                    ))
        return identities

    async def _from_credentials(self, platform: str) -> List[SelfIdentity]:
        try:
            record = await self._repository.get_platform_credentials(platform)
        except Exception as e:
            logger.warning(f"Could not read credentials for {platform}: {e}")
            return []
        if not record:
            return []

        data = record.get("credentials_data") or record.get("credentials") or {}
        if not isinstance(data, dict):
            return []

        identities: List[SelfIdentity] = []
        targets = signal_platforms_for(platform)

        account_id = data.get("user_id") or data.get("account_id") or data.get("ig_user_id")
        username = data.get("username") or data.get("handle")
        if account_id or username:
            for target in targets:
                identities.append(SelfIdentity(
                    platform=target,
                    account_id=str(account_id) if account_id else None,
                    username=str(username) if username else None,
                    source="platform_credentials",
                ))

        if base_platform(platform) in META_PLATFORMS:
            cookie_id = self._meta_cookie_account_id(data)
            if cookie_id:
                for target in targets:
                    identities.append(SelfIdentity(
                        platform=target,
                        account_id=cookie_id,
                        source="session_cookie",
                    ))
        return identities

    @staticmethod
    def _meta_cookie_account_id(data: Dict[str, Any]) -> Optional[str]:
        # The browser flows persist the Playwright storage state directly, while the OAuth flow
        # nests it; accept either shape rather than assuming one.
        session = data.get("browser_session") if isinstance(data.get("browser_session"), dict) else data
        storage_state = session.get("storage_state") if isinstance(session.get("storage_state"), dict) else session
        if not isinstance(storage_state, dict):
            return None
        for cookie in storage_state.get("cookies") or []:
            if isinstance(cookie, dict) and cookie.get("name") == META_ACCOUNT_COOKIE:
                value = str(cookie.get("value") or "").strip()
                if value:
                    return value
        return None
