import os
from pathlib import Path
from typing import Union
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# The project's own .env, resolved absolutely so it is found no matter what directory the
# process was started from. An MCP host launches the server with a cwd of its own choosing.
_PROJECT_ENV = Path(__file__).resolve().parents[2] / ".env"

# An explicit path to the env file, for an installation where the package does not sit inside
# the project tree -- a wheel in site-packages, for instance. It is a path, not a secret, so it
# is the one thing an MCP config needs to carry.
_ENV_FILE_OVERRIDE = os.environ.get("IGNIS_ENV_FILE", "").strip()

# pydantic-settings gives the LAST file the highest priority, so the order is
# least to most specific. The bare ".env" comes first: a stray file in whatever directory the
# host happened to start in must not outrank the project's own.
_ENV_FILES = tuple(
    source for source in (".env", _PROJECT_ENV, _ENV_FILE_OVERRIDE or None) if source
)


def reveal_secret(value: Union[SecretStr, str, None]) -> str:
    """Unwrap a secret setting at the point of use.

    Secrets are typed SecretStr so that neither repr(settings) nor a pydantic validation error
    prints them. A failing test dumps the whole Settings repr into the CI log, which on a public
    repository is world-readable, and that log used to carry the database password verbatim.

    Plain strings pass through, so a test that monkeypatches a setting and a caller that already
    holds an unwrapped value both stay valid.
    """
    if value is None:
        return ""
    if isinstance(value, SecretStr):
        return value.get_secret_value()
    return str(value)


class Settings(BaseSettings):
    """Configuration settings for fn-ignis loaded from environment variables."""
    model_config = SettingsConfigDict(
        env_file=_ENV_FILES,
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # Database TimescaleDB / PostgreSQL or SQLite
    # Carries a password whenever it points at anything but local SQLite. Unwrap with
    # reveal_secret() at the point of use.
    DATABASE_URL: SecretStr = Field(
        default=SecretStr("sqlite:///ignis.db"),
        description="Database connection URI (SQLite default for zero-config local mode, or PostgreSQL / TimescaleDB)"
    )
    DB_MIN_POOL_SIZE: int = Field(default=1, description="Minimum database connection pool size")
    DB_MAX_POOL_SIZE: int = Field(default=3, description="Maximum database connection pool size")

    # Ingress Connectors & API Keys
    YOUTUBE_API_KEY: SecretStr = Field(default=SecretStr(""), description="YouTube Data API v3 Key")

    # Meta Threads Graph API (Official OAuth 2.0)
    THREADS_APP_ID: str = Field(default="", description="Meta Threads App ID (client_id) for Graph API OAuth 2.0")
    THREADS_APP_SECRET: SecretStr = Field(default=SecretStr(""), description="Meta Threads App Secret (client_secret) used for long-lived token exchange")
    THREADS_REDIRECT_URI: str = Field(default="", description="Registered OAuth redirect URI for the Threads app")
    THREADS_API_VERSION: str = Field(default="v1.0", description="Threads Graph API version prefix")

    # Instagram Graph API (Official, for Reels ingress)
    INSTAGRAM_USER_ID: str = Field(default="", description="Instagram Business/Creator account ID used for Reels Graph API ingress")
    INSTAGRAM_APP_ID: str = Field(default="", description="Instagram App ID (client_id) for Graph API OAuth 2.0")
    INSTAGRAM_APP_SECRET: SecretStr = Field(default=SecretStr(""), description="Instagram App Secret (client_secret) used for long-lived token exchange")
    INSTAGRAM_REDIRECT_URI: str = Field(default="", description="Registered OAuth redirect URI for the Instagram app")
    INSTAGRAM_API_VERSION: str = Field(default="v23.0", description="Instagram Graph API version prefix")

    # Security & Encryption
    IGNIS_ENCRYPTION_KEY: SecretStr = Field(
        default=SecretStr(""),
        description="Fernet (256-bit key: AES-128-CBC + HMAC-SHA256) secret key for encrypting stored credentials in DB"
    )

    # Scheduler Configuration
    SCHEDULER_INTERVAL_SECONDS: int = Field(default=8640, description="Daemon scheduler tick interval in seconds; the default keeps one day of topic-coupled keyword probes inside YouTube's default quota")
    DISCOVERY_INTERVAL_HOURS: int = Field(default=24, description="Interval in hours between autonomous discovery runs")
    SYNC_INTERVAL_MINUTES: int = Field(default=0, description="Optional override for ingress sync interval in minutes; 0 = fallback to SCHEDULER_INTERVAL_SECONDS")

    # Ingress Defaults

    DEFAULT_GEO: str = Field(default="VN", description="Default ISO geographic region code")

    INGRESS_BATCH_LIMIT: int = Field(default=50, description="Maximum items fetched per connector batch")
    MIN_VALID_SAMPLE_SIZE: int = Field(default=15, description="Minimum sample size threshold for confidence calculation")

    # Scorecard Evaluation Weights (Must sum to 1.0)
    SCORECARD_WEIGHT_COVERAGE: float = Field(default=0.25, description="Weight for multi-platform coverage")
    SCORECARD_WEIGHT_LANGUAGE: float = Field(default=0.25, description="Weight for verified language localization")
    SCORECARD_WEIGHT_FRESHNESS: float = Field(default=0.30, description="Weight for timeframe freshness alignment")
    SCORECARD_WEIGHT_DIVERSITY: float = Field(default=0.20, description="Weight for independent creator diversity")

    # Confidence Thresholds
    CONFIDENCE_HIGH_THRESHOLD: float = Field(default=80.0, description="Score threshold for HIGH confidence")
    CONFIDENCE_MEDIUM_THRESHOLD: float = Field(default=60.0, description="Score threshold for MEDIUM confidence")
    CONFIDENCE_LOW_THRESHOLD: float = Field(default=40.0, description="Score threshold for LOW confidence")

    # Supply Scoring Parameters
    SUPPLY_VIDEO_WEIGHT: float = Field(default=7.5, description="Linear supply points per verified localized video")
    SUPPLY_BASE_MAX: float = Field(default=80.0, description="Maximum base supply contribution from video count")
    SUPPLY_VIEW_LOG_WEIGHT: float = Field(default=3.5, description="Logarithmic view factor weight")
    SUPPLY_VIEW_MAX: float = Field(default=20.0, description="Maximum view-based supply contribution")

    # Market Opportunity Thresholds
    WHITE_SPACE_HIGH_DEMAND_INDEX_THRESHOLD: float = Field(
        default=50.0,
        description="Opportunity index threshold for HIGH_DEMAND_LOW_SUPPLY classification"
    )
    ENTERPRISE_GAP_SUPPLY_THRESHOLD: float = Field(
        default=70.0,
        description="Supply score ceiling for enterprise gap classification"
    )
    SATURATION_SUPPLY_THRESHOLD: float = Field(
        default=70.0,
        description="Supply score floor for saturated segment classification"
    )

    # Resilience, Caching & Proxy
    YOUTUBE_CACHE_TTL_SECONDS: int = Field(
        default=86400,
        description="TTL in seconds for YouTube search queries cache (default 24h to preserve API quota)"
    )
    META_INSIGHTS_CACHE_TTL_SECONDS: int = Field(
        default=7200,
        description="TTL in seconds for Threads/Reels post insights cache (default 2h to stay under Meta's 200 calls/user/hour limit)"
    )
    # The documented form embeds credentials in the URI, so this is a secret too.
    PLAYWRIGHT_PROXY_SERVER: SecretStr = Field(
        default=SecretStr(""),
        description="Optional HTTP/SOCKS proxy server URI (e.g. http://user:pass@proxy.example.com:8080) for Playwright ingress"
    )



settings = Settings()
