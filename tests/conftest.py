import os
from collections.abc import MutableMapping
from datetime import datetime, timezone
from uuid import uuid4

import pytest


# Pytest is an isolated verification process, never a production runtime. Quarantine credentials
# before importing ignis because its settings singleton is created during module import. This both
# prevents accidental real API/database calls and keeps assertion introspection from echoing an
# inherited shell credential into a local or public CI transcript.
PYTEST_CREDENTIAL_OVERRIDES = {
    "DATABASE_URL": "sqlite:///ignis.db",
    "YOUTUBE_API_KEY": "",
    "IGNIS_ENCRYPTION_KEY": "",
    "THREADS_APP_SECRET": "",
    "INSTAGRAM_APP_SECRET": "",
    "PLAYWRIGHT_PROXY_SERVER": "",
}
PYTEST_CREDENTIAL_REMOVALS = {
    "IGNIS_ENV_FILE",
    "GH_TOKEN",
    "GITHUB_TOKEN",
    "DOCKER_AUTH_CONFIG",
    "DOCKER_REGISTRY_PASSWORD",
    "PGPASSWORD",
}


def quarantine_ambient_credentials(environment: MutableMapping[str, str]) -> None:
    """Replace host credentials with inert test values without retaining plaintext copies."""
    environment.update(PYTEST_CREDENTIAL_OVERRIDES)
    for name in PYTEST_CREDENTIAL_REMOVALS:
        environment.pop(name, None)


quarantine_ambient_credentials(os.environ)

from ignis.domain.entities import TrendSignal, TopicCluster  # noqa: E402
from ignis.domain.value_objects import PlatformType, GeoCode  # noqa: E402


@pytest.fixture
def sample_trend_signal():
    return TrendSignal(
        platform=PlatformType.GOOGLE_TRENDS,
        raw_title="AI Agent Trends 2026",
        metric_value=50000.0,
        growth_velocity=12.5,
        source_url="https://trends.google.com/sample",
        geo_code=GeoCode.VN,
        metadata={"traffic": "50K+", "news": "AI agent adoption surges"},
        captured_at=datetime.now(timezone.utc)
    )


@pytest.fixture
def sample_youtube_signal():
    return TrendSignal(
        platform=PlatformType.YOUTUBE,
        raw_title="Top Emerging Tech in Vietnam 2026",
        metric_value=1200000.0,
        growth_velocity=25.0,
        source_url="https://youtube.com/watch?v=sample123",
        geo_code=GeoCode.VN,
        metadata={"channel_title": "TechVN", "likes": 45000, "comments": 3200},
        captured_at=datetime.now(timezone.utc)
    )


@pytest.fixture
def sample_topic_cluster():
    return TopicCluster(
        id=uuid4(),
        canonical_name="Generative AI & Autonomous Agents",
        summary_text="Sự bùng nổ của các giải pháp AI tự hành và FastMCP",
        category="technology",
        cross_platform_score=88.5,
        first_seen_at=datetime.now(timezone.utc),
        last_updated_at=datetime.now(timezone.utc)
    )
