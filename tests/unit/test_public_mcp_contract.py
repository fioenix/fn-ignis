"""Breaking public MCP contract for the mission-bound product reset."""

import pytest

from ignis.interfaces.mcp.server import mcp


EXPECTED_TOOLS = {
    "authenticate_instagram",
    "authenticate_threads",
    "authenticate_tiktok",
    "clear_instagram_auth",
    "clear_platform_auth",
    "clear_threads_auth",
    "confirm_market_brief",
    "confirm_research_workspace",
    "create_attention_mission",
    "diagnose_system_health",
    "discover_market_opportunities",
    "evaluate_mission_quality",
    "execute_mission_ingress",
    "extract_customer_pain_points",
    "generate_mission_artifact",
    "get_current_session_mission",
    "get_instagram_auth_status",
    "get_mission_analysis",
    "get_mission_claims",
    "get_mission_evidence_qualification_batch",
    "get_platform_auth_status",
    "get_runtime_config",
    "get_system_logs",
    "get_threads_auth_status",
    "get_threads_search_suggestions",
    "get_threads_trending_topics",
    "get_tiktok_creative_center_trends",
    "get_tiktok_search_suggestions",
    "get_tiktok_video_comments",
    "list_domain_lexicons",
    "list_research_missions",
    "list_research_workspaces",
    "propose_research_workspace",
    "refresh_runtime_config_cache",
    "register_domain_lexicon",
    "register_noise_blacklist",
    "release_mission_writer",
    "submit_mission_claims",
    "submit_mission_evidence_qualifications",
    "update_runtime_config",
    "verify_connectors_health",
}

REMOVED_TOOLS = {
    "run_autonomous_research_mission",
    "create_research_mission",
    "get_trending_topics",
    "get_topic_detail",
    "generate_trend_artifact",
    "trigger_ingress_refresh",
    "trigger_autonomous_discovery",
    "get_latest_daily_discovery",
}


@pytest.mark.asyncio
async def test_public_mcp_inventory_is_the_mission_bound_contract():
    """Removing any retained tool or keeping any unscoped tool breaks the cutover contract."""
    actual = {tool.name for tool in await mcp.list_tools()}

    assert actual == EXPECTED_TOOLS
    assert actual.isdisjoint(REMOVED_TOOLS)
