import pytest

from ignis.domain.entities import TrendSignal
from ignis.domain.value_objects import PlatformType, GeoCode
from ignis.infrastructure.clustering.semantic_clusterer import SemanticClusterer
from ignis.infrastructure.harness.strategic_reasoner import StrategicMarketReasoner
from ignis.infrastructure.persistence.sqlite_repository import SqliteTrendRepository


@pytest.mark.asyncio
async def test_semantic_clusterer_dynamic_stopwords_no_hardcode():
    """Verify SemanticClusterer has no hardcoded stopwords and registers dynamic stopwords properly."""
    clusterer = SemanticClusterer(similarity_threshold=0.25)
    
    # By default, without registered stopwords, words like 'va', 'la' are tokens
    tokens = clusterer._tokenize("AI va Machine Learning")
    assert "va" in tokens
    assert "ai" in tokens
    
    # Register dynamic stopwords
    clusterer.register_stopwords(["va", "la"])
    tokens_after = clusterer._tokenize("AI va Machine Learning")
    assert "va" not in tokens_after
    assert "ai" in tokens_after


def test_strategic_reasoner_no_magic_50_demand_score():
    """Defect #5: Ensure that when no demand signals exist, demand_score is 0.0, NOT 50.0."""
    reasoner = StrategicMarketReasoner()
    signals = [
        TrendSignal(
            platform=PlatformType.YOUTUBE,
            raw_title="Khoa hoc AI Agent thuc chien",
            metric_value=5000.0,
            geo_code=GeoCode.VN,
        )
    ]
    
    # Query keyword that has NO Google Trends signal
    opps = reasoner._discover_market_opportunities(
        signals=signals,
        target_keywords=["non_existent_search_term"],
        geo=GeoCode.VN,
    )
    
    assert len(opps) == 1
    opp = opps[0]
    assert opp.search_interest_score == 0.0
    assert opp.opportunity_type == "NO_DATA_RECORDED"
    assert "Insufficient data to verify market opportunity" in opp.strategic_recommendation
    assert "50" not in opp.strategic_recommendation


@pytest.mark.asyncio
async def test_sqlite_seeds_from_sql_files_no_hardcoded_python_data():
    """Ensure SqliteTrendRepository reads seeds from external SQL files without hardcoded python tuples."""
    repo = SqliteTrendRepository(":memory:")
    await repo._ensure_schema()
    
    lexicons = await repo.get_domain_lexicons()
    assert len(lexicons) >= 50
    domains = {item["domain"] for item in lexicons}
    assert "common_vi" in domains or "global_saas_ai" in domains
    
    # Verify runtime_configs seeded from 007_runtime_configs.sql
    threads_client_id = await repo.get_runtime_config("threads_web_client_id")
    assert threads_client_id == "238260118693652"


@pytest.mark.asyncio
async def test_dual_tier_auth_status_and_resolution():
    """IGN-12: Test resolve_auth_tier and active_tier reported in auth status."""
    from ignis.infrastructure.connectors.threads.threads_plugin import ThreadsPlugin
    from ignis.infrastructure.connectors.reels.reels_plugin import ReelsPlugin
    from ignis.interfaces.mcp.server import _meta_auth_status
    from unittest.mock import AsyncMock

    mock_oauth = AsyncMock()
    mock_oauth.get_auth_status.return_value = {"authenticated": False, "status": "NOT_CONNECTED"}
    mock_browser = AsyncMock()
    mock_browser.get_auth_status.return_value = {"authenticated": True, "status": "ACTIVE"}

    # active_tier should report TIER_1_BROWSER_SESSION when browser session exists
    status = await _meta_auth_status(mock_oauth, mock_browser)
    assert status["active_tier"] == "TIER_1_BROWSER_SESSION"
    assert status["browser_session"]["status"] == "ACTIVE"

    # ThreadsPlugin resolve_auth_tier
    mock_browser.get_storage_state.return_value = {"cookies": []}
    mock_oauth.get_access_token.return_value = None
    threads_plugin = ThreadsPlugin(auth_manager=mock_oauth, browser_auth_manager=mock_browser)
    tier, cred = await threads_plugin.resolve_auth_tier()
    assert tier == "session_cookies"
    assert cred == {"cookies": []}

    # ReelsPlugin resolve_auth_tier
    reels_plugin = ReelsPlugin(auth_manager=mock_oauth, browser_auth_manager=mock_browser)
    tier_r, cred_r = await reels_plugin.resolve_auth_tier()
    assert tier_r == "session_cookies"


@pytest.mark.asyncio
async def test_runtime_config_store_empty_warning():
    """IGN-13: Test handle_get_runtime_config returns WARNING when store is empty or key not found."""
    import json
    from ignis.interfaces.mcp.server import handle_get_runtime_config
    from unittest.mock import AsyncMock, patch

    mock_mgr = AsyncMock()
    mock_mgr.get.return_value = None
    mock_mgr.get_all.return_value = {}

    with patch("ignis.interfaces.mcp.server.get_components", return_value={"runtime_config_manager": mock_mgr}):
        # Query specific missing key
        res_key = await handle_get_runtime_config(key="missing_key")
        payload_key = json.loads(res_key)
        assert payload_key["status"] == "NOT_FOUND"

        # Query all when empty
        res_all = await handle_get_runtime_config()
        payload_all = json.loads(res_all)
        assert payload_all["status"] == "WARNING"
        assert payload_all["warning_type"] == "STORE_EMPTY"


@pytest.mark.asyncio
async def test_verify_connectors_health_remediation_labels():
    """IGN-14: Test handle_verify_connectors_health distinguishes NOT_CONFIGURED from UNHEALTHY with remediation."""
    import json
    from ignis.interfaces.mcp.server import handle_verify_connectors_health
    from ignis.domain.value_objects import PlatformType
    from unittest.mock import AsyncMock, patch

    mock_repo = AsyncMock()
    mock_repo.get_domain_lexicons.return_value = [{"term": "test"}]

    mock_plugin = AsyncMock()
    mock_plugin.platform = PlatformType.THREADS
    mock_plugin.name = "Meta Threads Ingress"
    mock_plugin.is_healthy.return_value = False
    mock_plugin.resolve_auth_tier.return_value = ("none", None)

    mock_registry = AsyncMock()
    mock_registry._plugins = {"threads": mock_plugin}

    with patch(
        "ignis.interfaces.mcp.server.get_components",
        return_value={"repository": mock_repo, "registry": mock_registry},
    ):
        res = await handle_verify_connectors_health()
        payload = json.loads(res)
        connector_diag = payload["connectors"]["Meta Threads Ingress"]
        assert connector_diag["status"] == "NOT_CONFIGURED"
        assert "authenticate_threads" in connector_diag["remediation"]


@pytest.mark.asyncio
async def test_save_clusters_canonical_name_conflict_resolution():
    """Verify that PostgresTimescaleRepository resolves canonical_name conflicts and updates cluster_id on signals."""
    from uuid import uuid4
    from unittest.mock import AsyncMock, MagicMock
    from ignis.domain.entities import TopicCluster, TrendSignal
    from ignis.infrastructure.persistence.postgres_repository import PostgresTimescaleRepository

    mock_cursor = AsyncMock()
    existing_id = uuid4()
    mock_cursor.fetchone.return_value = (existing_id,)

    mock_cursor_cm = MagicMock()
    mock_cursor_cm.__aenter__ = AsyncMock(return_value=mock_cursor)
    mock_cursor_cm.__aexit__ = AsyncMock(return_value=None)

    mock_conn = MagicMock()
    mock_conn.cursor = MagicMock(return_value=mock_cursor_cm)

    mock_conn_cm = MagicMock()
    mock_conn_cm.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_conn_cm.__aexit__ = AsyncMock(return_value=None)

    mock_pool = MagicMock()
    mock_pool.connection = MagicMock(return_value=mock_conn_cm)

    repo = PostgresTimescaleRepository(dsn="postgresql://mock", pool=mock_pool)

    new_id = uuid4()
    sig = TrendSignal(
        platform=PlatformType.THREADS,
        raw_title="ừ cơm gà thì cơm gà",
        metric_value=10.0,
        geo_code=GeoCode.VN,
        cluster_id=new_id,
    )
    cluster = TopicCluster(
        id=new_id,
        canonical_name="ừ cơm gà thì cơm gà",
        cross_platform_score=50.0,
        signals=[sig],
    )

    await repo.save_clusters([cluster])

    # Ensure actual cluster ID and signal cluster ID were mapped to the existing ID
    assert cluster.id == existing_id
    assert sig.cluster_id == existing_id
    # Assert that existing cluster was updated
    second_call_query = mock_cursor.execute.call_args_list[1][0][0]
    assert "UPDATE topic_clusters SET" in second_call_query
