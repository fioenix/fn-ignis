"""A Market reasoner cannot mint a verdict outside the persisted Claim Ledger."""

import pytest

from ignis.application.use_cases.get_mission_analysis import GetMissionAnalysisUseCase
from ignis.domain.entities import ResearchMission, TrendSignal
from ignis.domain.harness_models import QualityScorecard
from ignis.domain.value_objects import PlatformType
from ignis.infrastructure.harness.strategic_reasoner import StrategicMarketReasoner
from ignis.infrastructure.persistence.sqlite_repository import SqliteTrendRepository


def test_direct_market_reasoner_returns_observations_but_no_strategic_verdict():
    mission = ResearchMission(
        title="Customer service AI",
        keywords=["customer service AI"],
        surface="MARKET",
    )
    signal = TrendSignal(
        platform=PlatformType.GOOGLE_TRENDS,
        raw_title="customer service AI",
        metric_value=95,
        metadata={"keyword": "customer service AI"},
    )

    report = StrategicMarketReasoner().analyze_mission(
        mission, [signal], [], QualityScorecard()
    )

    assert report.surface == "MARKET"
    assert report.market_opportunities == []
    assert report.strategic_insights == []
    assert report.actionable_takeaways == []
    assert report.maturity_stage is None
    assert report.qualification.reason_code == "CLAIM_LEDGER_REQUIRED"
    assert report.channel_summaries


@pytest.mark.asyncio
async def test_market_analysis_without_workspace_store_is_a_gap_report():
    repository = SqliteTrendRepository(db_path="sqlite:///:memory:")
    try:
        mission = ResearchMission(
            title="Customer service AI",
            keywords=["customer service AI"],
            surface="MARKET",
        )
        await repository.save_mission(mission)

        analysis = await GetMissionAnalysisUseCase(repository).execute(mission.id)

        assert analysis["analysis_status"] == "INSUFFICIENT_EVIDENCE"
        assert "INCOMPLETE_MISSION_FRAME" in analysis["gap_report"]["failed_gates"]
        assert "claim_ledger" not in analysis
    finally:
        await repository.close()
