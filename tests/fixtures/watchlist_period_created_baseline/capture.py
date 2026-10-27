"""Capture Spec 018 T002 using the Spec 016 unit fixtures, before production changes.

Run from the checkout with PYTHONPATH=src. Storage doubles expose the unit fixture's exact
observations and coverage; the period use case and comparison remain real. IDs and clock are
fixed so the JSON is reproducible. This is test data, never a caller-store capture.
"""
import asyncio
import json
import runpy
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

from ignis.application.use_cases.watchlist_period import GetWatchlistPeriodSnapshotUseCase
from ignis.domain.entities import ResearchMission
from ignis.domain.research_workspace import compute_frame_fingerprint
from ignis.domain.watchlist import Watchlist, WatchlistRun, WatchlistVersion, parse_watchlist_definition

FIXTURE = runpy.run_path('tests/unit/test_watchlist_period.py')
WATCHLIST_ID = UUID('00000000-0000-0000-0000-000000000018')
MISSION = ResearchMission(id=UUID('00000000-0000-0000-0000-000000000016'), title='Baseline', keywords=['matcha latte'])
FRAME = compute_frame_fingerprint(MISSION, None)
SIGNALS = []
JUDGMENTS = []
for index, item in enumerate(FIXTURE['items']()):
    for number, (observed, metric, metadata) in enumerate(item.observations):
        observation_id = f'{index}:{number}'
        SIGNALS.append(SimpleNamespace(
            source_id=item.source_id, observation_id=observation_id, captured_at=observed,
            metric_value=metric, metadata={**metadata, 'matched_keywords': list(item.query_keywords)},
            platform=item.channel, published_at=item.published_at, raw_title=item.title,
            source_url=item.link,
        ))
        JUDGMENTS.append(SimpleNamespace(
            frame_fingerprint=FRAME, observation_id=observation_id,
            relation='CONTEXT_ONLY' if item.relevant else 'EXCLUDED_IRRELEVANT',
        ))


class FixtureStore:
    async def get_watchlist(self, target):
        assert str(target) == str(WATCHLIST_ID)
        return Watchlist(str(WATCHLIST_ID), str(WATCHLIST_ID), 'Baseline', FIXTURE['NOW'],
                         (WatchlistVersion(1, parse_watchlist_definition({'topics': [FIXTURE['TOPIC']]}), FIXTURE['NOW']),),
                         (WatchlistRun(str(MISSION.id), 1, FIXTURE['NOW']),))

    async def get_latest_completed_probe_outcomes(self, target):
        return [SimpleNamespace(platform=c.channel, status=c.status, queried_keywords=c.queried_keywords,
                                completed_at=c.completed_at) for c in FIXTURE['COVERAGE']]

    async def get_mission(self, target):
        return MISSION

    async def list_evidence_qualifications(self, target):
        return JUDGMENTS

    async def list_mission_declared_accounts(self, target):
        return []

    async def get_mission_signals(self, target):
        return SIGNALS

    async def get_runtime_config(self, key):
        return None

    async def get_domain_lexicons(self, domain):
        return [{'term': 'xuhuong'}] if domain == 'noise_blacklist' else []


async def capture():
    store = FixtureStore()
    use_case = GetWatchlistPeriodSnapshotUseCase(store, store, lambda: FIXTURE['NOW'])
    for kind, start in [('day', '2026-10-19'), ('week', '2026-10-19'), ('month', '2026-09-01')]:
        result = await use_case.execute(str(WATCHLIST_ID), kind, start)
        Path(__file__).with_name(f'{kind}.json').write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n')


if __name__ == '__main__':
    asyncio.run(capture())
