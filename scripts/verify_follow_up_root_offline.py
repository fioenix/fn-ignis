"""Explicit offline verification of the private host composition; no live mode or installation.

Run with isolated config and explicit root-supplied packet/confirmation paths. All provider
responses and deferred credential values are synthetic. Receipt matching is not new consent.
"""
import argparse
import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from pathlib import Path
import tempfile

import ignis.config as config


def require_isolated_config():
    if not config._ENV_ISOLATED or config.reveal_secret(config.settings.DATABASE_URL) != 'sqlite:///:memory:':
        raise ValueError('ISOLATED_IN_MEMORY_SQLITE_REQUIRED')
    if any(config.reveal_secret(getattr(config.settings, name)) for name in (
        'YOUTUBE_API_KEY', 'THREADS_APP_SECRET', 'INSTAGRAM_APP_SECRET',
        'IGNIS_ENCRYPTION_KEY', 'PLAYWRIGHT_PROXY_SERVER')):
        raise ValueError('OFFLINE_EMPTY_CREDENTIAL_CONFIG_REQUIRED')


async def verify(packet_path, confirmation_path):
    require_isolated_config()
    import httpx
    from ignis.application.youtube_quota import YouTubeQuotaManager
    from ignis.application.ports.follow_up_execution_port import FollowUpExecutionBoundaryError
    from ignis.domain.follow_up_admission import digest
    from ignis.domain.research_workspace import (EvidenceDirection, EvidencePurpose,
        EvidenceQualification, QualificationReason, QualificationRelation,
        StaleEvidenceQualificationError, compute_frame_fingerprint)
    from ignis.domain.youtube_quota import YouTubeQuotaPolicy
    from ignis.infrastructure.follow_up_root_composition import (
        bootstrap_confirmed_parent, finish_canonical_parent_analysis, run_canonical_parent)
    from ignis.infrastructure.persistence.sqlite_repository import SqliteTrendRepository

    confirmation = json.loads(confirmation_path.read_text())
    packet_hash = sha256(packet_path.read_bytes()).hexdigest()
    if packet_hash != confirmation['packet_sha256']:
        raise ValueError('EXACT_CONFIRMED_PACKET_REQUIRED')
    packet = json.loads(packet_path.read_text())
    brief, instruction, receipt = packet['payload'], packet['collection_instruction'], confirmation['receipt']
    calls, resolutions = [], []
    now = datetime.now(timezone.utc)
    result = None

    async def response(request):
        calls.append((request.url.path.rsplit('/', 1)[-1], dict(request.url.params)))
        if request.url.path.endswith('/search'):
            return httpx.Response(200, json={'items': [{'id': {'videoId': 'offline-tutorial'}}]})
        return httpx.Response(200, json={'items': [{'id': 'offline-tutorial', 'snippet': {
            'title': 'Synthetic tutorial material', 'description': 'Synthetic public workflow explanation.',
            'publishedAt': now.isoformat()}, 'statistics': {'viewCount': '10'}}]})

    def resolve():
        resolutions.append('DEFERRED_SYNTHETIC_RESOLUTION')
        return 'offline-dummy-only'

    class OfflineClusterer:
        async def cluster_signals(self, signals):
            return []

    quota_repository = SqliteTrendRepository('sqlite:///:memory:')
    root = Path(tempfile.mkdtemp(prefix='ignis-offline-root-')) / 'owned'
    foreign = root / 'unregistered-foreign.txt'
    try:
        quota = YouTubeQuotaManager(quota_repository, YouTubeQuotaPolicy())
        assert not resolutions and not calls
        result = await bootstrap_confirmed_parent(root=root, brief=brief, receipt=receipt,
            instruction=instruction, resolve_credential=resolve, transport=httpx.MockTransport(response),
            quota_manager=quota, clusterer=OfflineClusterer())
        foreign.write_text('Synthetic foreign file must survive owned retention checks.')
        host = result['host']
        bounds = host.confirmation.bounds
        store = result['executor']._workspace_store
        snapshot = await store.load_mission_evidence_snapshot(host.confirmation.selected_parent_id)
        assert len(snapshot.signals) == 1 and not snapshot.qualifications and not snapshot.claims
        signal = snapshot.signals[0]
        assert signal.raw_title == 'Synthetic tutorial material'
        assert signal.metadata['description'] == 'Synthetic public workflow explanation.'
        assert signal.source_url == 'https://www.youtube.com/watch?v=offline-tutorial'
        assert signal.observation_id and signal.source_id
        assert len(calls) == len(resolutions) == 2
        assert [endpoint for endpoint, _ in calls] == ['search', 'videos']
        query = calls[0][1]
        assert query['q'] == instruction['queries'][0] and query['maxResults'] == '5'
        assert query['regionCode'] == 'VN' and query['relevanceLanguage'] == 'vi' and 'pageToken' not in query
        assert query['publishedAfter'] == (bounds.started_at - timedelta(days=30)).strftime('%Y-%m-%dT%H:%M:%SZ')
        assert bounds.deadline - bounds.started_at == timedelta(minutes=15)
        assert bounds.retention_until is None
        assert (bounds.search_calls, bounds.other_calls) == (2, 4)
        assert result['bridge'].budget._used == {'search': 1, 'other': 1}
        repository = result['repository']
        readback = await repository.get_mission_signals(snapshot.mission.id)
        assert [(s.source_id, s.observation_id, s.metadata) for s in readback] == [
            (signal.source_id, signal.observation_id, signal.metadata)]
        terminal_refusal = await run_canonical_parent(host=host, bridge=result['bridge'],
            executor=result['executor'], parent_work_id=result['work_id'])
        assert terminal_refusal == {'status': 'REFUSED', 'reason_code': 'PARENT_ALREADY_TERMINAL'}
        qualification = EvidenceQualification(mission_id=snapshot.mission.id,
            observation_id=signal.observation_id, brief_revision_id=snapshot.brief.brief_revision_id,
            frame_fingerprint=compute_frame_fingerprint(snapshot.mission, snapshot.brief),
            relation=QualificationRelation.CONTEXT_ONLY, purpose=EvidencePurpose.CONTEXT,
            confidence=1.0, reason_code=QualificationReason.ADJACENT_ONLY,
            judged_by='offline-invocation-control', evidence_role=EvidenceDirection.CONTEXT)
        try:
            await repository.commit_evidence_qualifications(snapshot.mission.id,
                [replace(qualification, frame_fingerprint='f' * 64)])
        except StaleEvidenceQualificationError:
            pass
        else:
            raise AssertionError('Stale qualification was not refused.')
        journal = await store.latest_run_journal(snapshot.mission.id)
        canonical = result['canonical']
        original_identity = (canonical.path.stat().st_dev, canonical.path.stat().st_ino)
        finished = await finish_canonical_parent_analysis(result, assessments=[{
            'observation_id': str(signal.observation_id), 'relation': 'CONTEXT_ONLY',
            'purpose': 'CONTEXT', 'confidence': 1.0, 'reason_code': 'ADJACENT_ONLY',
            'judged_by': 'offline-invocation-control', 'evidence_role': 'CONTEXT'}],
            candidates=[], judged_by='offline-invocation-control')
        assert finished['qualification']['status'] == 'RECORDED'
        assert finished['analysis']['analysis_status'] == 'INSUFFICIENT_EVIDENCE'
        assert finished['claim_ledger']['counts']['permitted'] == 0
        recovery = finished['recovery']
        retained = [(path.stat().st_ino, path.read_bytes()) for path in (canonical.path, journal.journal_path)]
        try:
            await recovery.purge(now=bounds.deadline + timedelta(days=8))
        except FollowUpExecutionBoundaryError:
            pass
        else:
            raise AssertionError('Persistent pilot data was purged without explicit user deletion.')
        assert (canonical.path.stat().st_dev, canonical.path.stat().st_ino) == original_identity
        assert [(path.stat().st_ino, path.read_bytes()) for path in (canonical.path, journal.journal_path)] == retained
        assert canonical.closed and host._revoked
        assert foreign.read_text() == 'Synthetic foreign file must survive owned retention checks.'
        assert len(calls) == len(resolutions) == 2
        return {'status': 'OFFLINE_PRODUCTION_COMPOSITION_VERIFIED', 'packet_sha256': packet_hash,
            'consumer_sha256': sha256(Path(__file__).read_bytes()).hexdigest(),
            'confirmation_sha256': sha256(confirmation_path.read_bytes()).hexdigest(),
            'brief_digest': digest(brief), 'scope_digest': digest(instruction),
            'authority_kind': confirmation['authority_kind'], 'provider_mode': 'MOCK_TRANSPORT_ONLY',
            'description_state': 'RETAINED', 'source_bound_readback': True,
            'qualification': 'EXPLICIT_CURRENT_FRAME_CONTEXT_ONLY', 'permitted_claims': 0,
            'analysis_status': finished['analysis']['analysis_status'],
            'claim_render_status': finished['claim_ledger']['render_status'],
            'source_revoked_before_analysis': host._revoked,
            'stale_qualification': 'REFUSED', 'credential_mode': 'DEFERRED_DUMMY_ONLY',
            'search_calls': 1, 'other_calls': 1, 'child_status': result['child_status'],
            'shutdown': ('REVOKED_CLOSED' if finished['accounting_close'] == 'CLOSED'
                else 'REVOKED_ACCOUNTING_CLOSE_PENDING'),
            'accounting_close': finished['accounting_close'], 'retention': instruction['retention'],
            'expiry_purge': 'REFUSED_WITH_ORIGINAL_DATA_RETAINED',
            'foreign_preserved': True, 'native_installation': 'NOT_ESTABLISHED',
            'live_provider_execution': 'NOT_EXECUTED', 'temporary_root': str(root)}
    finally:
        if result is not None:
            await result['host'].revoke()
            await result['repository'].close()
        await quota_repository.close()


def main():
    require_isolated_config()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--packet', type=Path, required=True)
    parser.add_argument('--confirmation', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    summary = asyncio.run(verify(args.packet, args.confirmation))
    with args.output.open('x') as output:
        output.write(json.dumps(summary, indent=2) + '\n')
    print(summary['status'])


if __name__ == '__main__':
    main()
