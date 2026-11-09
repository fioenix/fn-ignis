"""Only usable source metadata may supply a cluster category."""
from unittest.mock import AsyncMock

import pytest

from ignis.domain.entities import TrendSignal
from ignis.domain.value_objects import PlatformType
from ignis.infrastructure.clustering.semantic_clusterer import SemanticClusterer
from ignis.infrastructure.config.vocabulary_loader import VocabularySynchronizer


async def synchronized_clusterer():
    repository = AsyncMock()
    repository.get_domain_lexicons.return_value = []
    # Synthetic legacy rows expose the old fallback without shipping a keyword corpus.
    repository.get_industry_taxonomies.return_value = [
        {'industry_code': 'tech', 'keywords': ['synthetic topic', 'sample pattern']},
    ]
    clusterer = SemanticClusterer()
    await VocabularySynchronizer(repository, clusterer=clusterer).synchronize_vocabulary()
    return clusterer


@pytest.mark.asyncio
@pytest.mark.parametrize('category', [None, '', 'a', '12', '27.6k', '  ', '1,000'])
async def test_unusable_source_never_falls_back_to_keywords(category):
    clusterer = await synchronized_clusterer()
    signal = TrendSignal(platform=PlatformType.YOUTUBE, raw_title='Synthetic topic sample pattern',
                         metadata={} if category is None else {'category': category})
    clusters = await clusterer.cluster_signals([signal])
    assert len(clusters) == 1
    assert clusters[0].category == 'unclassified'
    assert clusters[0].signals == [signal]


@pytest.mark.asyncio
@pytest.mark.parametrize('source,expected', [(' Beauty ', 'beauty'),
    ('Beauty & Personal Care', 'beauty & personal care'), ('SOURCE LABEL', 'source label')])
async def test_usable_source_category_survives_normalized(source, expected):
    clusterer = await synchronized_clusterer()
    signal = TrendSignal(platform=PlatformType.YOUTUBE, raw_title='Synthetic topic sample pattern',
                         metadata={'category': source})
    assert (await clusterer.cluster_signals([signal]))[0].category == expected


@pytest.mark.asyncio
async def test_existing_source_majority_and_membership_are_preserved():
    clusterer = await synchronized_clusterer()
    signals = [TrendSignal(platform=PlatformType.YOUTUBE, raw_title='Synthetic topic sample pattern',
                           source_url=f'https://example.test/{index}', metadata={'category': category})
               for index, category in enumerate([' beauty ', 'BEAUTY', 'custom source'])]
    clusters = await clusterer.cluster_signals(signals)
    assert len(clusters) == 1
    assert clusters[0].category == 'beauty'
    assert {s.source_url for s in clusters[0].signals} == {s.source_url for s in signals}
