import pytest
import json
from unittest.mock import AsyncMock, patch, MagicMock
from ignis.infrastructure.harness.quality_evaluator import QualityEvaluator
from ignis.interfaces.mcp.server import handle_register_domain_lexicon, handle_list_domain_lexicons


def test_quality_evaluator_dynamic_lexicon():
    evaluator = QualityEvaluator()
    # Initially without custom term
    assert evaluator.is_vietnamese("retinol bha obagi") is False

    # Dynamically register beauty terms
    evaluator.register_terms(["retinol", "bha", "obagi"])
    assert evaluator.is_vietnamese("retinol bha obagi") is True


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
        assert mock_qe.is_vietnamese("ao linen oversize") is True


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
        assert len(resp["industry_taxonomies"]) == 1
