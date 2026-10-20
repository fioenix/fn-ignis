"""Read-service outcomes pinned directly, without the MCP handler or a repository."""

import asyncio
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from ignis.application.ports.mission_relay_port import MissionRelayReadRequest
from ignis.domain.mission_relay import (
    MissionRelayCursor,
    MissionRelayReadFailure,
    MissionRelaySnapshot,
    RelayReadReason,
    RelayReadStatus,
)
from ignis.domain.research_workspace import ResearchSurface
from ignis.infrastructure import mission_relay
from ignis.infrastructure.mission_relay import MissionRelayReadService

UNAVAILABLE = {"schema_version": 1, "status": "UNAVAILABLE", "reason_code": "READ_UNAVAILABLE"}


def _request(run_id=None):
    return MissionRelayReadRequest(mission_id=uuid4(), run_id=run_id, page_size=1)


def _snapshot(mission_id, run_id):
    return MissionRelaySnapshot(
        mission_id=mission_id, run_id=run_id,
        high_water=MissionRelayCursor(mission_id=mission_id, revision=0, ordinal=0),
        read_at=datetime.now(timezone.utc), page_size=1, evidence=(), total_observations=0,
        source_count=0, surface=ResearchSurface.ATTENTION, evidence_offset=0,
    )


class _Provider:
    def __init__(self, answer):
        self.answer = answer
        self.calls = 0

    async def snapshot(self, request):
        self.calls += 1
        return self.answer(request)


@pytest.fixture
def service():
    def build(answer):
        provider = _Provider(answer)
        return MissionRelayReadService(provider=provider, owner_loop=asyncio.get_running_loop()), provider

    yield build
    assert mission_relay._process_reads == 0, "A read leaked a process slot"


@pytest.mark.asyncio
async def test_matching_snapshot_is_returned_as_the_result_itself(service):
    run_id = uuid4()
    reads, _ = service(lambda request: _snapshot(request.mission_id, request.run_id))
    request = _request(run_id)
    result = await reads.read_snapshot(request)
    assert type(result) is MissionRelaySnapshot
    assert result.mission_id == request.mission_id and result.run_id == run_id


@pytest.mark.asyncio
@pytest.mark.parametrize("foreign", ("mission", "run"))
async def test_snapshot_for_another_scope_is_unavailable(service, foreign):
    def answer(request):
        if foreign == "mission":
            return _snapshot(uuid4(), request.run_id)
        return _snapshot(request.mission_id, uuid4())

    reads, _ = service(answer)
    result = await reads.read_snapshot(_request())
    assert result.to_payload() == UNAVAILABLE


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", (
    MissionRelayReadFailure(status=RelayReadStatus.REFUSED, reason_code=RelayReadReason.SCOPE_MISMATCH),
    MissionRelayReadFailure(status=RelayReadStatus.UNAVAILABLE, reason_code=RelayReadReason.READ_UNAVAILABLE),
))
async def test_provider_failure_passes_through_unchanged(service, failure):
    reads, _ = service(lambda request: failure)
    assert await reads.read_snapshot(_request()) is failure


@pytest.mark.asyncio
async def test_provider_error_or_untyped_answer_is_unavailable(service):
    def explode(request):
        raise RuntimeError("repository failed")

    reads, _ = service(explode)
    assert (await reads.read_snapshot(_request())).to_payload() == UNAVAILABLE
    untyped, _ = service(lambda request: {"status": "OK"})
    assert (await untyped.read_snapshot(_request())).to_payload() == UNAVAILABLE


@pytest.mark.asyncio
async def test_settled_reads_release_capacity_for_later_reads(service):
    reads, provider = service(lambda request: _snapshot(request.mission_id, request.run_id))
    for _ in range(6):
        assert type(await reads.read_snapshot(_request())) is MissionRelaySnapshot
    assert provider.calls == 6


@pytest.mark.asyncio
async def test_concurrent_reads_of_one_request_each_take_a_slot(service):
    release = asyncio.Event()
    entered = 0

    class Blocking(_Provider):
        async def snapshot(self, request):
            nonlocal entered
            entered += 1
            await release.wait()
            return _snapshot(request.mission_id, request.run_id)

    reads, _ = service(None)
    reads.provider = Blocking(None)
    request = _request(uuid4())
    pending = [asyncio.create_task(reads.read_snapshot(request)) for _ in range(4)]
    try:
        for _ in range(100):
            if entered == 4:
                break
            await asyncio.sleep(0)
        assert entered == 4, "Concurrent reads of one request were not all admitted"
        busy = await reads.read_snapshot(request)
        assert busy.to_payload() == {"schema_version": 1, "status": "UNAVAILABLE", "reason_code": "READ_BUSY"}
    finally:
        release.set()
        results = await asyncio.gather(*pending)
    assert all(type(result) is MissionRelaySnapshot for result in results)


@pytest.mark.asyncio
async def test_closed_service_refuses_without_reading(service):
    reads, provider = service(lambda request: _snapshot(request.mission_id, request.run_id))
    reads.close()
    result = await reads.read_snapshot(_request())
    assert result.to_payload() == {"schema_version": 1, "status": "UNAVAILABLE", "reason_code": "READ_BUSY"}
    assert provider.calls == 0


def test_reason_vocabulary_is_only_what_a_snapshot_read_can_emit():
    # The retired viewer's HTTP and capability reasons have no emitter left.
    assert {reason.value for reason in RelayReadReason} == {
        "SCOPE_MISMATCH", "INVALID_PAGE_SIZE", "INVALID_REQUEST", "RESPONSE_TOO_LARGE",
        "READ_UNAVAILABLE", "READ_BUSY", "READ_TIMEOUT",
    }
