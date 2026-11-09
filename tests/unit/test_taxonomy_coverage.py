"""Former category keywords no longer infer labels; historical SQL remains immutable."""
import re
from pathlib import Path

import pytest

from ignis.domain.entities import TrendSignal
from ignis.domain.value_objects import PlatformType
from ignis.infrastructure.migration.taxonomy_retirement import FORMER_CODES
from test_bug09_category_classification import synchronized_clusterer


@pytest.mark.asyncio
@pytest.mark.parametrize('title', ['Synthetic topic sample pattern', 'synthetic topic',
    'Giá vàng hôm nay', 'Khóa học AI', 'Unrelated observation', ''])
async def test_no_title_supplies_a_category_without_source_metadata(title):
    clusterer = await synchronized_clusterer()
    assert clusterer._classify_category([TrendSignal(platform=PlatformType.THREADS, raw_title=title)]) == 'unclassified'


def test_retirement_identifiers_match_both_immutable_historical_seeds():
    root = Path(__file__).resolve().parents[2]
    for name in ('003_market_lexicons.sql', '010_taxonomy_coverage.sql'):
        codes = re.findall(r"\('([^']+)',\s*'[^']+',\s*ARRAY\[", (root / 'sql' / name).read_text())
        assert sorted(codes) == list(FORMER_CODES)
