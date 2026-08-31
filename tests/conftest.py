import pytest
from datetime import datetime, timezone
from uuid import uuid4

from ignis.domain.entities import TrendSignal, TopicCluster
from ignis.domain.value_objects import PlatformType, GeoCode, Timeframe


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
