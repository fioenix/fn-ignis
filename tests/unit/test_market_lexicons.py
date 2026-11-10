import pytest
import json
from unittest.mock import AsyncMock, patch
from ignis.infrastructure.harness.quality_evaluator import QualityEvaluator
from ignis.interfaces.mcp.server import handle_register_domain_lexicon, handle_list_domain_lexicons


@pytest.mark.asyncio
async def test_handle_register_domain_lexicon():
    mock_repo = AsyncMock()
    mock_repo.register_lexicon_terms.return_value = 3
    mock_qe = QualityEvaluator()

    mock_comp = {
        "repository": mock_repo,
        "quality_evaluator": mock_qe,
    }

    with patch("ignis.interfaces.mcp.server.get_components", return_value=mock_comp):
        resp_str = await handle_register_domain_lexicon(
            domain="fashion",
            terms=["linen", "oversize", "local brand"],
            category="style",
        )
        resp = json.loads(resp_str)
        assert resp["status"] == "SUCCESS"
        assert resp["domain"] == "fashion"
        assert resp["terms_registered"] == 3
        assert mock_repo.register_lexicon_terms.called
        assert mock_qe.is_vietnamese("linen oversize local brand") is False


@pytest.mark.asyncio
async def test_handle_list_domain_lexicons():
    mock_repo = AsyncMock()
    mock_repo.get_domain_lexicons.return_value = [
        {"domain": "tech", "term": "ai agent", "category": "topic"}
    ]
    mock_repo.get_industry_taxonomies.return_value = [
        {"industry_code": "tech", "industry_name": "Tech & Electronics", "keywords": ["ai", "software"]}
    ]

    mock_comp = {"repository": mock_repo}

    with patch("ignis.interfaces.mcp.server.get_components", return_value=mock_comp):
        resp_str = await handle_list_domain_lexicons(domain="tech")
        resp = json.loads(resp_str)
        assert resp["status"] == "SUCCESS"
        assert resp["total_lexicon_terms"] == 1
        assert resp == {
            "status": "SUCCESS", "total_lexicon_terms": 1, "domain_filter": "tech",
            "lexicons": mock_repo.get_domain_lexicons.return_value,
        }
        mock_repo.get_domain_lexicons.assert_awaited_once_with(domain="tech")
        mock_repo.get_industry_taxonomies.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("domain", [
    "threads_action_labels_es", "threads_attribution", "tiktok_attribution",
    "probe_templates_es", "tiktok_suggest_templates_es", "search_intent",
])
async def test_register_machinery_never_teaches_evaluators_market_terms(tmp_path, monkeypatch, domain):
    from ignis.interfaces.mcp import server
    from ignis.infrastructure.persistence.sqlite_repository import SqliteTrendRepository
    from ignis.infrastructure.config.vocabulary_loader import load_market_vocabulary
    from ignis.infrastructure.harness.strategic_reasoner import StrategicMarketReasoner

    repo = SqliteTrendRepository(str(tmp_path / "lexicons.db"))
    quality = QualityEvaluator()
    reasoner = StrategicMarketReasoner()
    monkeypatch.setattr(server, "get_components", lambda: {
        "repository": repo, "quality_evaluator": quality, "strategic_reasoner": reasoner})
    title = "Synthetic Machinery"
    before = (quality.is_localized(title), reasoner._is_vietnamese(title))
    try:
        response = json.loads(await server.handle_register_domain_lexicon(domain, ["Synthetic Machinery"], "likes"))
        assert response["status"] == "SUCCESS"
        assert await repo.get_domain_lexicons(domain)
        assert (quality.is_localized(title), reasoner._is_vietnamese(title)) == before
        await load_market_vocabulary(repo)
    finally:
        await repo.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('domain', [None, 'tech', ''])
async def test_list_lexicons_never_reads_taxonomy_and_keeps_filter(domain):
    repository = AsyncMock()
    repository.get_domain_lexicons.return_value = []
    repository.get_industry_taxonomies.side_effect = AssertionError('forbidden taxonomy read')
    with patch('ignis.interfaces.mcp.server.get_components', return_value={'repository': repository}):
        assert json.loads(await handle_list_domain_lexicons(domain)) == {
            'status': 'SUCCESS', 'total_lexicon_terms': 0, 'domain_filter': domain, 'lexicons': [],
        }
    repository.get_domain_lexicons.assert_awaited_once_with(domain=domain)
    repository.get_industry_taxonomies.assert_not_awaited()


@pytest.mark.asyncio
async def test_list_lexicons_preserves_error_shape():
    repository = AsyncMock()
    repository.get_domain_lexicons.side_effect = RuntimeError('synthetic unavailable')
    with patch('ignis.interfaces.mcp.server.get_components', return_value={'repository': repository}):
        assert json.loads(await handle_list_domain_lexicons()) == {
            'status': 'ERROR', 'message': 'synthetic unavailable',
        }


@pytest.mark.asyncio
async def test_taxonomy_removal_keeps_real_mcp_inventory_and_request_schema():
    from test_public_mcp_contract import EXPECTED_TOOLS
    from ignis.interfaces.mcp.server import mcp
    tools = {tool.name: tool for tool in await mcp.list_tools()}
    assert len(tools) == 41
    assert set(tools) == EXPECTED_TOOLS
    schema = tools['list_domain_lexicons'].parameters
    assert set(schema['properties']) == {'domain'}
    assert schema.get('required', []) == []
    assert schema['properties']['domain']['anyOf'] == [{'type': 'string'}, {'type': 'null'}]
    assert schema['properties']['domain']['default'] is None
