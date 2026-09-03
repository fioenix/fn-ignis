from __future__ import annotations

import logging
import urllib.parse
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx

from ignis.application.ports.repository_port import ITrendRepository
from ignis.config import settings
from ignis.domain.exceptions import ConnectorAuthenticationException
from ignis.infrastructure.auth.crypto import CryptoService

logger = logging.getLogger(__name__)


DEFAULT_THREADS_SCOPES = [
    "threads_basic",
    "threads_manage_insights",
    "threads_keyword_search",
]


DEFAULT_INSTAGRAM_SCOPES = [
    "instagram_business_basic",
    "instagram_business_manage_insights",
]


class ThreadsAuthManager:
    """
    Official Meta Threads Graph API OAuth 2.0 credential lifecycle manager.

    Flow: authorization code -> short-lived token -> long-lived user token (60 days)
    -> proactive refresh once the remaining lifetime drops below the threshold.

    Tokens and the client secret are persisted through the repository, which
    encrypts the payload with AES via CryptoService. A persistent
    IGNIS_ENCRYPTION_KEY is mandatory: storing a 60-day token under an ephemeral
    process key would make it undecryptable after a restart.
    """

    PLATFORM_NAME = "threads"
    AUTH_TYPE = "oauth2"

    AUTHORIZE_URL = "https://threads.net/oauth/authorize"
    TOKEN_EXCHANGE_URL = "https://graph.threads.net/oauth/access_token"
    LONG_LIVED_TOKEN_URL = "https://graph.threads.net/access_token"
    REFRESH_TOKEN_URL = "https://graph.threads.net/refresh_access_token"

    EXCHANGE_GRANT_TYPE = "th_exchange_token"
    REFRESH_GRANT_TYPE = "th_refresh_token"
    DEFAULT_SCOPES = DEFAULT_THREADS_SCOPES
    APP_ID_SETTING = "THREADS_APP_ID"
    APP_SECRET_SETTING = "THREADS_APP_SECRET"
    REDIRECT_URI_SETTING = "THREADS_REDIRECT_URI"

    LONG_LIVED_TTL_DAYS = 60
    REFRESH_THRESHOLD_DAYS = 10
    REQUEST_TIMEOUT_SECONDS = 20.0

    def __init__(
        self,
        repository: Optional[ITrendRepository] = None,
        crypto_service: Optional[CryptoService] = None,
    ):
        self._repository = repository
        self._crypto = crypto_service or CryptoService()

    def set_repository(self, repository: ITrendRepository) -> None:
        self._repository = repository

    # --- Configuration resolution ---

    def _resolve_app_credentials(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        redirect_uri: Optional[str] = None,
    ) -> Dict[str, str]:
        resolved = {
            "client_id": client_id or getattr(settings, self.APP_ID_SETTING, ""),
            "client_secret": client_secret or getattr(settings, self.APP_SECRET_SETTING, ""),
            "redirect_uri": redirect_uri or getattr(settings, self.REDIRECT_URI_SETTING, ""),
        }
        missing = [k for k in ("client_id", "client_secret") if not resolved[k]]
        if missing:
            raise ConnectorAuthenticationException(
                f"Missing {self.PLATFORM_NAME} app credentials: {', '.join(missing)}. "
                f"Set {self.APP_ID_SETTING} / {self.APP_SECRET_SETTING} in .env or pass them explicitly."
            )
        return resolved

    def build_authorization_url(
        self,
        client_id: Optional[str] = None,
        redirect_uri: Optional[str] = None,
        scopes: Optional[List[str]] = None,
        state: Optional[str] = None,
    ) -> str:
        """Build the consent URL the operator opens once to obtain an authorization code."""
        resolved_client_id = client_id or getattr(settings, self.APP_ID_SETTING, "")
        resolved_redirect = redirect_uri or getattr(settings, self.REDIRECT_URI_SETTING, "")
        if not resolved_client_id or not resolved_redirect:
            raise ConnectorAuthenticationException(
                f"{self.APP_ID_SETTING} and {self.REDIRECT_URI_SETTING} are required to build the authorization URL."
            )
        params = {
            "client_id": resolved_client_id,
            "redirect_uri": resolved_redirect,
            "scope": ",".join(scopes or self.DEFAULT_SCOPES),
            "response_type": "code",
        }
        if state:
            params["state"] = state
        return f"{self.AUTHORIZE_URL}?{urllib.parse.urlencode(params)}"

    # --- HTTP plumbing ---

    async def _request_token(self, method: str, url: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=self.REQUEST_TIMEOUT_SECONDS) as client:
                if method == "POST":
                    resp = await client.post(url, data=payload)
                else:
                    resp = await client.get(url, params=payload)
        except httpx.HTTPError as e:
            raise ConnectorAuthenticationException(f"{self.PLATFORM_NAME} OAuth transport error calling {url}: {e}") from e

        if resp.status_code != 200:
            detail = self._extract_error_detail(resp)
            await self.record_api_failure(resp.status_code, detail, endpoint=url)
            raise ConnectorAuthenticationException(
                f"{self.PLATFORM_NAME} OAuth request to {url} failed with HTTP {resp.status_code}: {detail}"
            )

        try:
            data = resp.json()
        except Exception as e:
            raise ConnectorAuthenticationException(f"{self.PLATFORM_NAME} OAuth response from {url} is not valid JSON: {e}") from e

        if not isinstance(data, dict) or not data.get("access_token"):
            raise ConnectorAuthenticationException(
                f"{self.PLATFORM_NAME} OAuth response from {url} did not contain an access_token: {data}"
            )
        return data

    @staticmethod
    def _extract_error_detail(resp: httpx.Response) -> str:
        try:
            body = resp.json()
        except Exception:
            return (resp.text or "")[:300]
        if isinstance(body, dict):
            err = body.get("error")
            if isinstance(err, dict):
                return str(err.get("message") or err)
            if err:
                return str(err)
        return str(body)[:300]

    # --- OAuth 2.0 flow ---

    async def exchange_code_for_token(
        self,
        auth_code: str,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        redirect_uri: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Exchange an authorization code for a short-lived token, immediately upgrade it
        to a 60-day long-lived user token, and persist the result encrypted.
        """
        app = self._resolve_app_credentials(client_id, client_secret, redirect_uri)
        # Fail fast before any secret material is obtained and written.
        self._crypto.assert_persistent_key(f"{self.PLATFORM_NAME} OAuth 2.0 credential storage")

        if not auth_code or not auth_code.strip():
            raise ConnectorAuthenticationException("auth_code is required to exchange for a Threads access token.")

        # Meta appends '#_' to the redirected authorization code.
        code = auth_code.strip().split("#")[0]

        short_lived = await self._request_token(
            "POST",
            self.TOKEN_EXCHANGE_URL,
            {
                "client_id": app["client_id"],
                "client_secret": app["client_secret"],
                "grant_type": "authorization_code",
                "redirect_uri": app["redirect_uri"],
                "code": code,
            },
        )

        long_lived = await self._exchange_for_long_lived(
            short_lived_token=short_lived["access_token"],
            client_secret=app["client_secret"],
        )

        record = self._build_record(
            access_token=long_lived["access_token"],
            expires_in=int(long_lived.get("expires_in") or self.LONG_LIVED_TTL_DAYS * 86400),
            app=app,
            user_id=str(short_lived.get("user_id") or long_lived.get("user_id") or "") or None,
            token_type=long_lived.get("token_type", "bearer"),
        )
        await self._persist(record, event_type="OAUTH_TOKEN_ISSUED",
                            message="Threads long-lived user token issued and stored encrypted.")

        return self._public_view(record, message="Threads OAuth 2.0 authentication successful.")

    async def _exchange_for_long_lived(self, short_lived_token: str, client_secret: str) -> Dict[str, Any]:
        return await self._request_token(
            "GET",
            self.LONG_LIVED_TOKEN_URL,
            {
                "grant_type": self.EXCHANGE_GRANT_TYPE,
                "client_secret": client_secret,
                "access_token": short_lived_token,
            },
        )

    async def setup_credentials(
        self,
        access_token: str,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        redirect_uri: Optional[str] = None,
        upgrade_to_long_lived: bool = True,
    ) -> Dict[str, Any]:
        """Register an already-obtained token, optionally upgrading it to a long-lived one first."""
        app = self._resolve_app_credentials(client_id, client_secret, redirect_uri)
        self._crypto.assert_persistent_key(f"{self.PLATFORM_NAME} OAuth 2.0 credential storage")

        if not access_token or not access_token.strip():
            raise ConnectorAuthenticationException("access_token is required.")

        token = access_token.strip()
        expires_in = self.LONG_LIVED_TTL_DAYS * 86400

        if upgrade_to_long_lived:
            upgraded = await self._exchange_for_long_lived(token, app["client_secret"])
            token = upgraded["access_token"]
            expires_in = int(upgraded.get("expires_in") or expires_in)

        record = self._build_record(access_token=token, expires_in=expires_in, app=app)
        await self._persist(record, event_type="OAUTH_TOKEN_REGISTERED",
                            message="Threads access token registered and stored encrypted.")
        return self._public_view(record, message="Threads credentials registered.")

    async def refresh_token_if_needed(self, force: bool = False) -> Dict[str, Any]:
        """
        Refresh the long-lived token when fewer than REFRESH_THRESHOLD_DAYS remain.

        Returns a status dict describing whether a refresh was performed.
        """
        record = await self._load_record()
        if not record:
            return {"refreshed": False, "reason": "NOT_AUTHENTICATED"}

        remaining = self._days_remaining(record)
        if not force and remaining is not None and remaining > self.REFRESH_THRESHOLD_DAYS:
            return {
                "refreshed": False,
                "reason": "TOKEN_STILL_FRESH",
                "days_remaining": remaining,
                "threshold_days": self.REFRESH_THRESHOLD_DAYS,
            }

        self._crypto.assert_persistent_key(f"{self.PLATFORM_NAME} OAuth 2.0 token refresh")

        refreshed = await self._request_token(
            "GET",
            self.REFRESH_TOKEN_URL,
            {"grant_type": self.REFRESH_GRANT_TYPE, "access_token": record["access_token"]},
        )

        new_record = self._build_record(
            access_token=refreshed["access_token"],
            expires_in=int(refreshed.get("expires_in") or self.LONG_LIVED_TTL_DAYS * 86400),
            app={
                "client_id": record.get("client_id", ""),
                "client_secret": record.get("client_secret", ""),
                "redirect_uri": record.get("redirect_uri", ""),
            },
            user_id=record.get("user_id"),
            token_type=refreshed.get("token_type", record.get("token_type", "bearer")),
            refresh_count=int(record.get("refresh_count", 0)) + 1,
        )
        await self._persist(new_record, event_type="OAUTH_TOKEN_REFRESHED",
                            message="Threads long-lived token refreshed before expiry.")

        return {
            "refreshed": True,
            "reason": "FORCED" if force else "BELOW_THRESHOLD",
            "days_remaining": self._days_remaining(new_record),
            "refresh_count": new_record["refresh_count"],
        }

    async def get_access_token(self, auto_refresh: bool = True) -> Optional[str]:
        """Return a usable access token, refreshing it first when it is close to expiry."""
        record = await self._load_record()
        if not record:
            return None

        if auto_refresh:
            remaining = self._days_remaining(record)
            if remaining is not None and remaining <= self.REFRESH_THRESHOLD_DAYS:
                try:
                    await self.refresh_token_if_needed()
                    record = await self._load_record() or record
                except Exception as e:
                    logger.warning(f"Threads token refresh failed, falling back to current token: {e}")

        if self._is_expired(record):
            return None
        return record.get("access_token")

    async def is_authenticated(self) -> bool:
        record = await self._load_record()
        return bool(record and record.get("access_token") and not self._is_expired(record))

    async def get_auth_status(self) -> Dict[str, Any]:
        record = await self._load_record()
        if not record:
            return {
                "platform": self.PLATFORM_NAME,
                "authenticated": False,
                "auth_type": self.AUTH_TYPE,
                "status": "NOT_CONNECTED",
                "encryption_key_configured": self._crypto.has_persistent_key(),
                "message": "No Threads OAuth credentials stored. Run authenticate_threads(auth_code=...).",
            }

        remaining = self._days_remaining(record)
        expired = self._is_expired(record)
        return {
            "platform": self.PLATFORM_NAME,
            "authenticated": not expired,
            "auth_type": self.AUTH_TYPE,
            "status": "EXPIRED" if expired else ("NEEDS_REFRESH" if (remaining is not None and remaining <= self.REFRESH_THRESHOLD_DAYS) else "ACTIVE"),
            "user_id": record.get("user_id"),
            "scopes": record.get("scopes", []),
            "key_version": record.get("key_version"),
            "encryption_key_configured": self._crypto.has_persistent_key(),
            "obtained_at": record.get("obtained_at"),
            "expires_at": record.get("expires_at"),
            "days_remaining": remaining,
            "refresh_threshold_days": self.REFRESH_THRESHOLD_DAYS,
            "refresh_count": record.get("refresh_count", 0),
        }

    async def clear_auth(self) -> bool:
        if not self._repository:
            return False
        cleared = await self._repository.delete_platform_credentials(self.PLATFORM_NAME)
        await self._log_event(
            event_type="OAUTH_TOKEN_CLEARED",
            message="Threads OAuth credentials revoked from local storage."
            if cleared else "No Threads OAuth credentials to clear.",
            level="INFO",
        )
        return cleared

    async def record_api_failure(
        self,
        status_code: int,
        detail: str,
        endpoint: Optional[str] = None,
    ) -> None:
        """Write an explicit audit trail for Meta soft-blocks and token rejections."""
        if status_code in (401, 403):
            event_type, level = "AUTH_REJECTED", "ERROR"
        elif status_code == 429:
            event_type, level = "RATE_LIMITED", "WARNING"
        else:
            event_type, level = "API_FAILURE", "ERROR"

        await self._log_event(
            event_type=event_type,
            message=f"{self.PLATFORM_NAME} Graph API returned HTTP {status_code}: {detail}",
            level=level,
            details={"status_code": status_code, "endpoint": endpoint, "detail": detail},
        )

    def _public_view(self, record: Dict[str, Any], message: str) -> Dict[str, Any]:
        """Project a stored credential record into a secret-free response payload."""
        return {
            "success": True,
            "platform": self.PLATFORM_NAME,
            "auth_type": self.AUTH_TYPE,
            "message": message,
            "user_id": record.get("user_id"),
            "scopes": record.get("scopes", []),
            "token_type": record.get("token_type"),
            "long_lived": record.get("long_lived", True),
            "key_version": record.get("key_version"),
            "obtained_at": record.get("obtained_at"),
            "expires_at": record.get("expires_at"),
            "days_remaining": self._days_remaining(record),
            "refresh_threshold_days": self.REFRESH_THRESHOLD_DAYS,
            "encrypted_at_rest": True,
        }

    # --- Persistence helpers ---

    def _build_record(
        self,
        access_token: str,
        expires_in: int,
        app: Dict[str, str],
        user_id: Optional[str] = None,
        token_type: str = "bearer",
        refresh_count: int = 0,
        scopes: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(seconds=expires_in)
        return {
            "access_token": access_token,
            "token_type": token_type,
            "user_id": user_id,
            "client_id": app.get("client_id", ""),
            "client_secret": app.get("client_secret", ""),
            "redirect_uri": app.get("redirect_uri", ""),
            "scopes": scopes or self.DEFAULT_SCOPES,
            "key_version": self._crypto.key_version,
            "long_lived": True,
            "expires_in": expires_in,
            "obtained_at": now.isoformat(),
            "expires_at": expires_at.isoformat(),
            "refresh_count": refresh_count,
        }

    async def _persist(self, record: Dict[str, Any], event_type: str, message: str) -> None:
        if not self._repository:
            raise ConnectorAuthenticationException(
                f"No repository is bound to {self.__class__.__name__}; cannot persist OAuth credentials."
            )
        await self._repository.save_platform_credentials(
            platform=self.PLATFORM_NAME,
            auth_type=self.AUTH_TYPE,
            credentials_data=record,
            is_active=True,
            expires_at=datetime.fromisoformat(record["expires_at"]),
        )
        await self._log_event(
            event_type=event_type,
            message=message,
            level="INFO",
            details={
                "expires_at": record["expires_at"],
                "key_version": record["key_version"],
                "refresh_count": record["refresh_count"],
            },
        )

    async def _load_record(self) -> Optional[Dict[str, Any]]:
        if not self._repository:
            return None
        creds = await self._repository.get_platform_credentials(self.PLATFORM_NAME)
        if not creds or not creds.get("is_active"):
            return None
        data = creds.get("credentials_data") or creds.get("credentials")
        if not isinstance(data, dict) or not data.get("access_token"):
            return None
        return data

    async def _log_event(
        self,
        event_type: str,
        message: str,
        level: str = "INFO",
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        if not self._repository:
            return
        try:
            await self._repository.log_event(
                component=self.__class__.__name__,
                event_type=event_type,
                message=message,
                level=level,
                details=details,
            )
        except Exception as e:  # audit logging must never mask the original outcome
            logger.warning(f"Could not write Threads auth audit log: {e}")

    # --- Expiry math ---

    @staticmethod
    def _parse_expiry(record: Dict[str, Any]) -> Optional[datetime]:
        raw = record.get("expires_at")
        if not raw:
            return None
        try:
            parsed = datetime.fromisoformat(str(raw))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed

    @classmethod
    def _days_remaining(cls, record: Dict[str, Any]) -> Optional[float]:
        expires_at = cls._parse_expiry(record)
        if not expires_at:
            return None
        return round((expires_at - datetime.now(timezone.utc)).total_seconds() / 86400.0, 2)

    @classmethod
    def _is_expired(cls, record: Dict[str, Any]) -> bool:
        expires_at = cls._parse_expiry(record)
        if not expires_at:
            return False
        return expires_at <= datetime.now(timezone.utc)


class InstagramAuthManager(ThreadsAuthManager):
    """
    Instagram Graph API OAuth 2.0 manager for the Reels ingress connector.

    Identical lifecycle to Threads (code -> short-lived -> 60-day long-lived -> refresh),
    but against Instagram's own OAuth hosts and `ig_*` grant types.
    """

    PLATFORM_NAME = "instagram"

    AUTHORIZE_URL = "https://api.instagram.com/oauth/authorize"
    TOKEN_EXCHANGE_URL = "https://api.instagram.com/oauth/access_token"
    LONG_LIVED_TOKEN_URL = "https://graph.instagram.com/access_token"
    REFRESH_TOKEN_URL = "https://graph.instagram.com/refresh_access_token"

    EXCHANGE_GRANT_TYPE = "ig_exchange_token"
    REFRESH_GRANT_TYPE = "ig_refresh_token"
    DEFAULT_SCOPES = DEFAULT_INSTAGRAM_SCOPES
    APP_ID_SETTING = "INSTAGRAM_APP_ID"
    APP_SECRET_SETTING = "INSTAGRAM_APP_SECRET"
    REDIRECT_URI_SETTING = "INSTAGRAM_REDIRECT_URI"
