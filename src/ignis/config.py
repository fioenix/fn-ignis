from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuration settings for fn-ignis loaded from environment variables."""
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # Database TimescaleDB / PostgreSQL or SQLite
    DATABASE_URL: str = Field(
        default="sqlite:///ignis.db",
        description="Database connection URI (SQLite default for zero-config local mode, or PostgreSQL / TimescaleDB)"
    )
    DB_MIN_POOL_SIZE: int = Field(default=2, description="Minimum database connection pool size")
    DB_MAX_POOL_SIZE: int = Field(default=10, description="Maximum database connection pool size")

    # Ingress Connectors & API Keys
    YOUTUBE_API_KEY: str = Field(default="", description="YouTube Data API v3 Key")

    # Meta Threads Graph API (Official OAuth 2.0)
    THREADS_APP_ID: str = Field(default="", description="Meta Threads App ID (client_id) for Graph API OAuth 2.0")
    THREADS_APP_SECRET: str = Field(default="", description="Meta Threads App Secret (client_secret) used for long-lived token exchange")
    THREADS_REDIRECT_URI: str = Field(default="", description="Registered OAuth redirect URI for the Threads app")
    THREADS_API_VERSION: str = Field(default="v1.0", description="Threads Graph API version prefix")

    # Instagram Graph API (Official, for Reels ingress)
    INSTAGRAM_USER_ID: str = Field(default="", description="Instagram Business/Creator account ID used for Reels Graph API ingress")
    INSTAGRAM_APP_ID: str = Field(default="", description="Instagram App ID (client_id) for Graph API OAuth 2.0")
    INSTAGRAM_APP_SECRET: str = Field(default="", description="Instagram App Secret (client_secret) used for long-lived token exchange")
    INSTAGRAM_REDIRECT_URI: str = Field(default="", description="Registered OAuth redirect URI for the Instagram app")
    INSTAGRAM_API_VERSION: str = Field(default="v23.0", description="Instagram Graph API version prefix")

    # Security & Encryption
    IGNIS_ENCRYPTION_KEY: str = Field(
        default="",
        description="Fernet AES-256 secret key for encrypting stored credentials in DB"
    )

    # Scheduler Configuration
    SCHEDULER_INTERVAL_SECONDS: int = Field(default=900, description="Daemon scheduler tick interval in seconds")
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
    PLAYWRIGHT_PROXY_SERVER: str = Field(
        default="",
        description="Optional HTTP/SOCKS proxy server URI (e.g. http://user:pass@proxy.example.com:8080) for Playwright ingress"
    )



settings = Settings()
