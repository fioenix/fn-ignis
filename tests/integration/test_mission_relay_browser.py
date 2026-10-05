"""T018 RED contracts for the real maintained relay template, not mission UAT.

The future builder and DOM seam is recorded in Spec014 Session 2026-10-05.
Only loopback routes with existing typed inert records are intercepted. Missing
builder/template failures are prerequisites, not executed browser negatives.
T033 stale reads, T059 lifecycle and T060 accessibility remain separate gates.
"""

import json
import re
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID

import pytest
from jinja2 import TemplateNotFound

from ignis.domain.mission_relay import (
    MissionProgressEvent,
    MissionProgressKind,
    MissionRelayCursor,
    MissionRelayEventPage,
    MissionRelayInspection,
    MissionRelaySnapshot,
    RelayEvidenceReference,
    RelayFramePendingReason,
    RelayObservation,
    RelayProvenance,
)
from ignis.domain.research_workspace import (
    EvidenceDirection,
    EvidenceRole,
    QualificationRelation,
    ResearchSurface,
)
from ignis.infrastructure.templates.html_builder import HtmlArtifactBuilder


ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = ROOT / "src/ignis/infrastructure/templates/html/mission_relay.html"
THEME = ROOT / "src/ignis/infrastructure/templates/html/_fino_theme.html"
MISSION = UUID("11111111-2222-4333-8444-555555555555")
RUN = UUID("22222222-3333-4444-8555-666666666666")
SOURCE = UUID("44444444-5555-4666-8777-888888888888")
NOW = datetime(2026, 10, 5, tzinfo=timezone.utc)
ORIGIN = "http://127.0.0.1:43118"
DOCUMENT_URL = ORIGIN + "/view/inert-fixture/"
SNAPSHOT_URL = DOCUMENT_URL + "snapshot"
RESPONSIBILITIES = ("Mission authority", "Sources", "Cleaning", "Research", "Cross-check", "Synthesis")


def _cursor(revision=0, ordinal=None):
    return MissionRelayCursor(mission_id=MISSION, revision=revision, ordinal=revision if ordinal is None else ordinal)


def _observation(number=1, **changes):
    values = dict(
        mission_id=MISSION, observation_id=UUID(int=1000 + number), source_id=SOURCE,
        title=f"Recorded public observation {number}", excerpt="A fixture receipt, not a market conclusion.",
        source_url="https://example.invalid/public", metric_value=900000,
        growth_velocity=None, published_at=None, captured_at=NOW,
        evidence_role=EvidenceRole.ATTENTION_CONTEXT, direction=EvidenceDirection.CONTEXT,
    )
    values.update(changes)
    return RelayObservation(**values)


def _reference(observation):
    return RelayEvidenceReference(
        mission_id=observation.mission_id, observation_id=observation.observation_id,
        source_id=observation.source_id, evidence_role=observation.evidence_role,
        direction=observation.direction, qualification_relation=observation.qualification_relation,
        qualification_frame_fingerprint=observation.qualification_frame_fingerprint,
    )


def _event(revision=1, observations=(), **changes):
    values = dict(
        event_id=UUID(int=2000 + revision), cursor=_cursor(revision),
        kind=MissionProgressKind.OBSERVATIONS_COMMITTED,
        provenance=RelayProvenance.HARNESS_OBSERVED, recorded_at=NOW,
        occurred_at=None, causation_key=f"inert-command-{revision}", run_id=RUN,
        evidence_references=tuple(_reference(row) for row in observations),
    )
    values.update(changes)
    return MissionProgressEvent(**values)


def _snapshot(observations=(), events=(), *, revision=None, resync=False, **changes):
    high_water = _cursor(revision if revision is not None else len(events))
    values = dict(
        mission_id=MISSION, run_id=RUN, high_water=high_water, read_at=NOW,
        page_size=200, evidence=tuple(observations), total_observations=len(observations),
        source_count=len({row.source_id for row in observations}), surface=ResearchSurface.ATTENTION,
        manifest_digest="a" * 64, frame_pending_reason=RelayFramePendingReason.UNKNOWN,
        event_page=MissionRelayEventPage(
            high_water=high_water, page_size=200, events=() if resync else tuple(events),
            resync_required=resync,
        ),
    )
    values.update(changes)
    return MissionRelaySnapshot(**values)


def _render(snapshot, builder=None, *, expires_at=None):
    """Discover missing real seams in each call phase, never manufacture HTML."""
    builder = builder or HtmlArtifactBuilder()
    build = getattr(builder, "build_mission_relay_artifact", None)
    assert callable(build), "T018 API RED: the typed maintained relay builder is absent"
    try:
        template = builder._env.get_template("mission_relay.html")
    except TemplateNotFound:
        pytest.fail("T018 TEMPLATE RED: maintained mission_relay.html is absent", pytrace=False)
    assert Path(template.filename).resolve() == TEMPLATE
    html = build(snapshot, snapshot_url=SNAPSHOT_URL, expires_at=expires_at or NOW + timedelta(minutes=15))
    assert isinstance(html, str) and html.strip(), "The typed builder must render maintained HTML"
    return html


@pytest.fixture(scope="module")
def installed_browser():
    """Use only an installed isolated browser; absence is an explicit runtime skip."""
    playwright = pytest.importorskip("playwright.sync_api", reason="Installed Playwright is unavailable")
    with playwright.sync_playwright() as runtime:
        try:
            browser = runtime.chromium.launch(headless=True)
        except playwright.Error:
            pytest.skip("Installed isolated Chromium cannot launch; no browser was installed")
        try:
            yield browser
        finally:
            browser.close()


def _install_packet_observer(context, packets, packet_peaks):
    """Count insertion occurrences, including reuse; avoid nested-addition double counting."""
    context.expose_binding("t018_record_packet", lambda source, value: packets.append(value))
    context.expose_binding("t018_record_peak", lambda source, value: packet_peaks.append(value))
    # This observer records real DOM additions, not animation completion or product hooks.
    context.add_init_script("""(() => {
            const record = (node, addedElements) => {
                if (!(node instanceof Element)) return;
                const items = node.matches('[data-testid="relay-packet"]')
                    ? [node] : [...node.querySelectorAll('[data-testid="relay-packet"]')];
                for (const item of items) {
                    if (addedElements.some(other => other !== node &&
                        node.contains(other) && other.contains(item))) continue;
                    window.t018_record_packet({
                        event: item.getAttribute('data-event-id'),
                        observations: item.getAttribute('data-observation-ids'),
                        sources: item.getAttribute('data-source-ids'),
                        role: item.getAttribute('data-evidence-role'),
                        direction: item.getAttribute('data-direction'),
                        provenance: item.getAttribute('data-provenance'),
                        count: item.querySelector('[data-testid="packet-observation-count"]')?.textContent
                    });
                }
            };
            new MutationObserver(records => {
                const addedElements = records.flatMap(recorded =>
                    [...recorded.addedNodes].filter(node => node instanceof Element));
                records.forEach(recorded => recorded.addedNodes.forEach(node =>
                    record(node, addedElements)));
                window.t018_record_peak(document.querySelectorAll('[data-testid="relay-packet"]').length);
            }).observe(document, {childList: true, subtree: true});
        })();""")


class FixtureViewer:
    """Keep real maintained DOM/JS while replacing only local read transport."""

    def __init__(self, browser, initial):
        self.current = initial
        self.responses = []
        self.requests = []
        self.unexpected = []
        self.blocked_fonts = []
        self.packets = []
        self.packet_peaks = []
        html = _render(initial)
        self.context = browser.new_context(service_workers="block")
        self.context.route("**/*", self._route)
        _install_packet_observer(self.context, self.packets, self.packet_peaks)
        self.page = self.context.new_page()
        self.page.set_default_timeout(1500)
        self.page.clock.install(time=NOW)
        self.document = html

    def open(self):
        self.page.goto(DOCUMENT_URL)
        self.page.get_by_test_id("snapshot-state").wait_for(state="visible")

    def _route(self, route):
        request = route.request
        parsed = urlsplit(request.url)
        self.requests.append((request.method, parsed.path))
        if request.method == "GET" and parsed.scheme == "https" and parsed.netloc in ("fonts.googleapis.com", "fonts.gstatic.com"):
            self.blocked_fonts.append(request.url)
            route.abort()
        elif request.method != "GET" or parsed.scheme != "http" or parsed.netloc != "127.0.0.1:43118":
            self.unexpected.append((request.method, parsed.scheme, parsed.netloc, parsed.path))
            route.abort()
        elif parsed.path == "/view/inert-fixture/":
            route.fulfill(status=200, content_type="text/html", body=self.document)
        elif parsed.path == "/view/inert-fixture/snapshot":
            if self.responses:
                self.current = self.responses.pop(0)
            payload = self.current.to_payload()
            # Model the real reader's exclusive cursor page, rather than replaying
            # the full fixture history for every incremental request.
            from urllib.parse import parse_qs
            query = parse_qs(parsed.query)
            page = payload.get('event_page')
            if page is not None and not page['resync_required'] and 'after_revision' in query:
                after = _cursor(int(query['after_revision'][0]), int(query['after_ordinal'][0]))
                if after.position <= self.current.high_water.position:
                    page['after_cursor'] = after.to_payload()
                    page['events'] = [event for event in page['events'] if (event['revision'], event['ordinal']) > after.position]
            route.fulfill(status=200, content_type="application/json", body=json.dumps(payload))
        elif parsed.path.startswith("/view/inert-fixture/inspect/"):
            identifier = parsed.path.rsplit("/", 1)[-1]
            observation = next((row for row in self.current.evidence if str(row.observation_id) == identifier), None)
            if observation is None:
                self.unexpected.append((request.method, parsed.scheme, parsed.netloc, parsed.path))
                route.abort()
                return
            inspection = MissionRelayInspection(
                mission_id=MISSION, run_id=self.current.run_id, high_water=self.current.high_water,
                read_at=self.current.read_at, observation=observation,
            )
            route.fulfill(status=200, content_type="application/json", body=json.dumps(inspection.to_payload()))
        else:
            self.unexpected.append((request.method, parsed.scheme, parsed.netloc, parsed.path))
            route.abort()

    def refresh(self, snapshot):
        self.responses.append(snapshot)
        with self.page.expect_response(lambda response: urlsplit(response.url).path == "/view/inert-fixture/snapshot"):
            self.page.clock.run_for(2100)
        assert not self.responses, "The real settled refresh must consume the queued typed snapshot"
        self.page.evaluate("async () => { await Promise.resolve(); await Promise.resolve(); }")

    def reconnect(self):
        self.document = _render(self.current)
        self.page.reload()
        self.page.get_by_test_id("snapshot-state").wait_for(state="visible")
        self.page.evaluate("async () => { await Promise.resolve(); await Promise.resolve(); }")

    def counts(self, observations, sources):
        from playwright.sync_api import expect

        expect(self.page.get_by_test_id("observation-count")).to_have_text(str(observations))
        expect(self.page.get_by_test_id("source-count")).to_have_text(str(sources))

    def close(self):
        self.context.close()


@contextmanager
def _viewer(browser, snapshot):
    viewer = FixtureViewer(browser, snapshot)
    try:
        viewer.open()
        yield viewer
        assert not viewer.unexpected, "The viewer attempted a route outside inert scoped reads"
    finally:
        viewer.close()


def _event_row(page, event):
    return page.get_by_test_id("event-timeline").locator(f'[data-event-id="{event.event_id}"]')


def test_default_builder_resolves_the_actual_maintained_template():
    """Catch a parallel fixture HTML surface being substituted for maintained source."""
    try:
        template = HtmlArtifactBuilder()._env.get_template("mission_relay.html")
    except TemplateNotFound:
        pytest.fail("T018 TEMPLATE RED: maintained mission_relay.html is absent", pytrace=False)
    assert Path(template.filename).resolve() == TEMPLATE


def test_builder_renders_existing_product_theme_from_default_loader(monkeypatch):
    """Catch bypassing the existing FINOLABS theme with a separate ad hoc palette."""
    builder = HtmlArtifactBuilder()
    loaded = []
    original = builder._env.loader.get_source

    def recording_source(environment, name):
        result = original(environment, name)
        loaded.append(Path(result[1]).resolve())
        return result

    monkeypatch.setattr(builder._env.loader, "get_source", recording_source)
    _render(_snapshot(), builder)
    assert THEME in loaded


@pytest.mark.parametrize("responsibility", RESPONSIBILITIES)
def test_direct_six_responsibility_selection_exposes_recorded_or_missing_inputs(installed_browser, responsibility):
    """Catch an inaccessible stage, motion-gated inspector or invented stage facts."""
    from playwright.sync_api import expect

    with _viewer(installed_browser, _snapshot()) as viewer:
        page = viewer.page
        for name in RESPONSIBILITIES:
            expect(page.get_by_role("button", name=name, exact=True)).to_be_visible()
        page.get_by_role("button", name=responsibility, exact=True).click()
        inspector = page.get_by_test_id("stage-inspector")
        expect(inspector).to_be_visible()
        expect(inspector.get_by_role("heading", name=responsibility, exact=True)).to_be_visible()
        for name in ("Input", "Output", "Failure reason"):
            region = inspector.get_by_role("region", name=name, exact=True)
            expect(region).to_be_visible()
            expect(region).to_contain_text(re.compile(r"\S"))
        if responsibility in ("Cleaning", "Research", "Cross-check", "Synthesis"):
            expect(inspector.get_by_role("region", name="Output", exact=True)).to_contain_text(re.compile(r"unknown|unavailable|pending", re.I))
        expect(inspector.get_by_role("region", name="Why it matters", exact=True)).to_be_visible()
        assert viewer.packets == [], "Direct inspection must not require or manufacture arrivals"


def test_initial_snapshot_header_preserves_identity_read_receipt_and_unknown_frame(installed_browser):
    """Catch presenting an initial snapshot as live throughput or fabricating a frame."""
    from playwright.sync_api import expect

    row = _observation()
    receipt = _event(observations=(row,))
    with _viewer(installed_browser, _snapshot((row,), (receipt,))) as viewer:
        header = viewer.page.get_by_test_id("mission-authority")
        expect(header).to_be_visible()
        for value in (str(MISSION), str(RUN), NOW.isoformat(), "a" * 64):
            expect(header).to_contain_text(value)
        expect(header).to_contain_text(re.compile("unknown", re.I))
        expect(viewer.page.get_by_test_id("snapshot-state")).to_contain_text(re.compile("snapshot", re.I))
        expect(_event_row(viewer.page, receipt)).to_be_visible()
        viewer.counts(1, 1)
        assert viewer.packets == [], "An initial historical event is not a newly observed arrival"


def test_header_does_not_fill_missing_run_or_manifest_identity(installed_browser):
    """Catch inferring mission authority or a collection run from an empty view."""
    from playwright.sync_api import expect

    with _viewer(installed_browser, _snapshot(run_id=None, manifest_digest=None)) as viewer:
        header = viewer.page.get_by_test_id("mission-authority")
        expect(header).to_contain_text(str(MISSION))
        expect(header.get_by_test_id("run-identity")).to_contain_text(re.compile("unknown", re.I))
        expect(header.get_by_test_id("manifest-identity")).to_contain_text(re.compile("unknown|unavailable", re.I))
        viewer.counts(0, 0)


@pytest.mark.parametrize("pending", tuple(RelayFramePendingReason))
def test_missing_frame_reason_remains_explicit_in_synthesis(installed_browser, pending):
    """Catch treating missing frame facts as a completed permitted conclusion."""
    from playwright.sync_api import expect

    with _viewer(installed_browser, _snapshot(frame_pending_reason=pending)) as viewer:
        viewer.page.get_by_role("button", name="Synthesis", exact=True).click()
        inspector = viewer.page.get_by_test_id("stage-inspector")
        expect(inspector).to_contain_text(re.compile(pending.value, re.I))
        expect(inspector.get_by_role("region", name="Output", exact=True)).to_contain_text(re.compile("withheld|unavailable|pending", re.I))
        assert viewer.packets == []


def test_missing_events_do_not_invent_work_receipts_or_throughput(installed_browser):
    """Catch fabricating active work, confidence, timestamps or packets to fill lanes."""
    from playwright.sync_api import expect

    with _viewer(installed_browser, _snapshot((_observation(),), event_page=None)) as viewer:
        for stage in ("Cleaning", "Research", "Cross-check", "Synthesis"):
            viewer.page.get_by_role("button", name=stage, exact=True).click()
            expect(viewer.page.get_by_test_id("stage-inspector")).to_contain_text(re.compile("unknown|unavailable|pending", re.I))
        viewer.refresh(_snapshot((_observation(),), event_page=None))
        viewer.counts(1, 1)
        assert viewer.packets == []
        assert viewer.page.locator('[data-event-id]').count() == 0
        assert viewer.page.locator('[data-testid="active-work"]').count() == 0


@pytest.mark.parametrize("provenance", tuple(RelayProvenance))
def test_new_recorded_arrival_has_inspectable_packet_identity_and_exact_counts(installed_browser, provenance):
    """Catch packet source substitution, popularity promotion or lost receipt provenance."""
    from playwright.sync_api import expect

    observation = _observation()
    receipt = _event(observations=(observation,), provenance=provenance)
    with _viewer(installed_browser, _snapshot()) as viewer:
        viewer.refresh(_snapshot((observation,), (receipt,)))
        viewer.counts(1, 1)
        assert len(viewer.packets) == 1
        packet = viewer.packets[0]
        assert packet["event"] == str(receipt.event_id)
        assert json.loads(packet["observations"]) == [str(observation.observation_id)]
        assert json.loads(packet["sources"]) == [str(SOURCE)]
        assert (packet["role"], packet["direction"], packet["provenance"]) == ("ATTENTION_CONTEXT", "CONTEXT", provenance.value)
        history = _event_row(viewer.page, receipt)
        expect(history).to_contain_text(provenance.value)
        expect(history).to_contain_text("OBSERVATIONS_COMMITTED")
        history.get_by_role("button", name=observation.title, exact=True).click()
        inspector = viewer.page.get_by_test_id("stage-inspector")
        for value in (str(observation.observation_id), str(SOURCE), "ATTENTION_CONTEXT", "CONTEXT", "900000"):
            expect(inspector).to_contain_text(value)
        expect(inspector).to_contain_text(re.compile("unknown", re.I))
        assert any(path.endswith("/inspect/" + str(observation.observation_id)) for method, path in viewer.requests)


def test_repeated_snapshot_responses_and_reload_do_not_repeat_arrivals_or_counts(installed_browser):
    """Catch deduplication by request time rather than immutable event/observation IDs."""
    from playwright.sync_api import expect

    observation = _observation()
    receipt = _event(observations=(observation,))
    recorded = _snapshot((observation,), (receipt,))
    with _viewer(installed_browser, _snapshot()) as viewer:
        viewer.refresh(recorded)
        assert len(viewer.packets) == 1
        viewer.refresh(replace(recorded, read_at=NOW + timedelta(seconds=3)))
        viewer.refresh(replace(recorded, read_at=NOW + timedelta(seconds=6)))
        viewer.counts(1, 1)
        assert len(viewer.packets) == 1
        expect(_event_row(viewer.page, receipt)).to_have_count(1)
        viewer.reconnect()
        viewer.counts(1, 1)
        expect(viewer.page.get_by_test_id("snapshot-state")).to_contain_text(re.compile("snapshot", re.I))
        expect(_event_row(viewer.page, receipt)).to_have_count(1)
        viewer.refresh(viewer.current)
        assert len(viewer.packets) == 1, "Reload history and refresh are not fresh collection"


def test_new_observation_of_same_source_counts_once_without_extra_independent_source(installed_browser):
    """Catch source-count inflation or observation deduplication by source URL alone."""
    first, second = _observation(1), _observation(2)
    first_event = _event(1, (first,))
    second_event = _event(2, (second,))
    with _viewer(installed_browser, _snapshot((first,), (first_event,))) as viewer:
        viewer.refresh(_snapshot((first, second), (first_event, second_event)))
        viewer.counts(2, 1)
        assert len(viewer.packets) == 1
        assert viewer.packets[0]["event"] == str(second_event.event_id)
        assert json.loads(viewer.packets[0]["observations"]) == [str(second.observation_id)]
        viewer.refresh(viewer.current)
        viewer.counts(2, 1)
        assert len(viewer.packets) == 1


def test_arrival_packets_do_not_merge_support_counterevidence_context_and_excluded_roles(installed_browser):
    """Catch assigning one flattering role to a heterogeneous recorded arrival batch."""
    from playwright.sync_api import expect

    definitions = (
        (1, EvidenceRole.MARKET_EVIDENCE, EvidenceDirection.SUPPORT, QualificationRelation.QUALIFIED_SUPPORT),
        (2, EvidenceRole.MARKET_EVIDENCE, EvidenceDirection.CONTRADICTION, QualificationRelation.QUALIFIED_CONTRADICTION),
        (3, EvidenceRole.ATTENTION_CONTEXT, EvidenceDirection.CONTEXT, QualificationRelation.CONTEXT_ONLY),
        (4, EvidenceRole.MARKET_EVIDENCE, None, QualificationRelation.EXCLUDED_IRRELEVANT),
    )
    rows = tuple(_observation(number, evidence_role=role, direction=direction,
        qualification_relation=relation, qualification_frame_fingerprint="b" * 64)
        for number, role, direction, relation in definitions)
    receipt = _event(observations=rows)
    expected = {
        str(UUID(int=1001)): ("MARKET_EVIDENCE", "SUPPORT"),
        str(UUID(int=1002)): ("MARKET_EVIDENCE", "CONTRADICTION"),
        str(UUID(int=1003)): ("ATTENTION_CONTEXT", "CONTEXT"),
        str(UUID(int=1004)): ("MARKET_EVIDENCE", None),
    }
    with _viewer(installed_browser, _snapshot(surface=ResearchSurface.MARKET)) as viewer:
        viewer.refresh(_snapshot(rows, (receipt,), surface=ResearchSurface.MARKET))
        viewer.counts(4, 1)
        represented = []
        for packet in viewer.packets:
            assert packet["event"] == str(receipt.event_id)
            for identifier in json.loads(packet["observations"]):
                assert (packet["role"], packet["direction"]) == expected[identifier]
                represented.append(identifier)
        assert sorted(represented) == sorted(expected)
        history = _event_row(viewer.page, receipt)
        for row in rows:
            reference = history.locator(f'[data-observation-id="{row.observation_id}"]')
            expect(reference).to_contain_text(row.qualification_relation.value)


def test_membership_reattachment_is_inspectable_but_not_fresh_social_collection(installed_browser):
    """Catch animating/counting a preserved observation as freshly collected evidence."""
    from playwright.sync_api import expect

    observation = _observation()
    receipt = _event(observations=(observation,), reason="MEMBERSHIP_REATTACHED")
    with _viewer(installed_browser, _snapshot()) as viewer:
        viewer.refresh(_snapshot((observation,), (receipt,)))
        viewer.counts(1, 1)
        expect(_event_row(viewer.page, receipt)).to_contain_text("MEMBERSHIP_REATTACHED")
        assert viewer.packets == [], "Membership delta is not a new social observation"
        viewer.refresh(viewer.current)
        viewer.reconnect()
        viewer.counts(1, 1)
        assert viewer.packets == []


@pytest.mark.parametrize("kind", (
    MissionProgressKind.COLLECTION_STARTED, MissionProgressKind.PROBE_OUTCOMES_RECORDED,
    MissionProgressKind.WORK_STARTED, MissionProgressKind.WORK_WAITING,
    MissionProgressKind.CANCELLATION_REQUESTED, MissionProgressKind.CANCELLATION_ACKNOWLEDGED,
))
def test_state_and_probe_receipts_never_become_observation_arrivals(installed_browser, kind):
    """Catch treating a recorded start, empty probe or interruption as durable evidence."""
    from playwright.sync_api import expect

    receipt = _event(kind=kind, reason="No observation committed")
    with _viewer(installed_browser, _snapshot()) as viewer:
        viewer.refresh(_snapshot(events=(receipt,)))
        expect(_event_row(viewer.page, receipt)).to_contain_text(kind.value)
        expect(_event_row(viewer.page, receipt)).to_contain_text("No observation committed")
        viewer.counts(0, 0)
        assert viewer.packets == []


@pytest.mark.parametrize("direction,relation", (
    (EvidenceDirection.SUPPORT, QualificationRelation.QUALIFIED_SUPPORT),
    (EvidenceDirection.CONTRADICTION, QualificationRelation.QUALIFIED_CONTRADICTION),
    (EvidenceDirection.CONTEXT, QualificationRelation.CONTEXT_ONLY),
    (None, QualificationRelation.EXCLUDED_IRRELEVANT),
))
def test_qualification_role_is_inspectable_without_a_second_observation_arrival(installed_browser, direction, relation):
    """Catch changing context/excluded/counterevidence into support or duplicating intake."""
    from playwright.sync_api import expect

    observation = _observation(evidence_role=EvidenceRole.MARKET_EVIDENCE, direction=direction)
    qualified = replace(observation, qualification_relation=relation, qualification_frame_fingerprint="b" * 64)
    arrival = _event(1, (observation,))
    qualification = _event(2, (qualified,), kind=MissionProgressKind.QUALIFICATION_RECORDED, provenance=RelayProvenance.HOST_REPORTED)
    with _viewer(installed_browser, _snapshot((observation,), (arrival,), surface=ResearchSurface.MARKET)) as viewer:
        viewer.refresh(_snapshot((qualified,), (arrival, qualification), surface=ResearchSurface.MARKET))
        viewer.counts(1, 1)
        history = _event_row(viewer.page, qualification)
        expect(history).to_contain_text("HOST_REPORTED")
        expect(history).to_contain_text(relation.value)
        history.get_by_role("button", name=observation.title, exact=True).click()
        inspector = viewer.page.get_by_test_id("stage-inspector")
        expect(inspector).to_contain_text(relation.value)
        expect(inspector).to_contain_text("b" * 64)
        if direction is not None:
            expect(inspector).to_contain_text(direction.value)
        # A qualification may move a role packet, but cannot add a collection arrival.
        expect(viewer.page.get_by_test_id("arrivals").locator('[data-event-id]')).to_have_count(0)
        for packet in viewer.packets:
            assert packet["event"] == str(qualification.event_id)
            assert packet["role"] == "MARKET_EVIDENCE"
            assert packet["direction"] == (direction.value if direction else None)
            assert json.loads(packet["observations"]) == [str(observation.observation_id)]
        viewer.refresh(viewer.current)
        assert len(viewer.packets) <= 1


def test_burst_packets_disclose_exact_role_totals_and_observation_drilldown(installed_browser):
    """Catch lossy packet caps, implicit source inflation or unverifiable aggregation."""
    from playwright.sync_api import expect

    rows = tuple(_observation(number) for number in range(1, 126))
    receipt = _event(observations=rows)
    with _viewer(installed_browser, _snapshot()) as viewer:
        viewer.refresh(_snapshot(rows, (receipt,)))
        viewer.counts(125, 1)
        assert viewer.packets
        assert max(viewer.packet_peaks) <= 120, "The cap bounds simultaneously rendered packets, not historical totals"
        represented = [identifier for packet in viewer.packets for identifier in json.loads(packet["observations"])]
        assert sorted(represented) == sorted(str(row.observation_id) for row in rows)
        assert len(set(represented)) == 125
        for packet in viewer.packets:
            assert packet["event"] == str(receipt.event_id)
            assert packet["role"] == "ATTENTION_CONTEXT"
            assert packet["direction"] == "CONTEXT"
            assert packet["provenance"] == "HARNESS_OBSERVED"
            assert set(json.loads(packet["sources"])) == {str(SOURCE)}
            assert packet["count"] == str(len(json.loads(packet["observations"])))
        history = _event_row(viewer.page, receipt)
        expect(history.get_by_test_id("event-observation-count")).to_have_text("125")
        expect(history.locator('[data-observation-id]')).to_have_count(125)
        history.get_by_role("button", name=rows[-1].title, exact=True).click()
        expect(viewer.page.get_by_test_id("stage-inspector")).to_contain_text(str(rows[-1].observation_id))


def test_resync_snapshot_does_not_replay_unseen_history_as_fresh_packets(installed_browser):
    """Catch treating a resync high-water jump as invented recorded arrivals."""
    from playwright.sync_api import expect

    with _viewer(installed_browser, _snapshot()) as viewer:
        viewer.refresh(_snapshot((_observation(),), revision=7, resync=True))
        viewer.counts(1, 1)
        expect(viewer.page.get_by_test_id("snapshot-state")).to_contain_text(re.compile("snapshot|resync", re.I))
        assert viewer.packets == []


def test_product_tokens_and_read_only_stage_inspection_work_without_remote_resources(installed_browser):
    """Catch remote-dependent inspectors or abandoning the maintained product theme."""
    from playwright.sync_api import expect

    with _viewer(installed_browser, _snapshot()) as viewer:
        page = viewer.page
        expect(page.locator("body")).to_have_class(re.compile(r"\bproduct-mode\b"))
        tokens = page.locator("body").evaluate("""body => {
            const style = getComputedStyle(body);
            return ['--color-foreground', '--color-border', '--color-chart-1'].map(name => style.getPropertyValue(name).trim());
        }""")
        assert all(tokens), "Maintained product role/chart tokens must resolve in the real browser"
        page.get_by_role("button", name="Sources", exact=True).click()
        expect(page.get_by_test_id("stage-inspector")).to_be_visible()
        # External fonts may be requested but are blocked; no remote data/site is admitted.
        assert all(method == "GET" for method, path in viewer.requests)


def test_packet_observer_catches_reinserted_nodes_without_counting_nested_additions_twice(installed_browser):
    """Verify the test instrument cannot conceal duplicate arrivals; this is not product UAT."""
    packets, peaks = [], []
    context = installed_browser.new_context(service_workers="block")
    context.route("**/*", lambda route: route.fulfill(status=200, content_type="text/html",
        body="<!doctype html><html><body></body></html>"))
    _install_packet_observer(context, packets, peaks)
    try:
        page = context.new_page()
        page.goto(DOCUMENT_URL)
        page.evaluate("""() => {
            const parent = document.createElement('section');
            document.body.append(parent);
            const packet = document.createElement('span');
            packet.dataset.testid = 'relay-packet';
            packet.dataset.eventId = 'instrument-control';
            packet.innerHTML = '<span data-testid="packet-observation-count">1</span>';
            parent.append(packet);
            window.controlPacket = packet;
        }""")
        page.wait_for_function("document.querySelector('[data-testid=relay-packet]') !== null")
        # Binding delivery is asynchronous; wait on an actual browser receipt, not elapsed time.
        page.evaluate("async () => { await window.t018_record_peak(1); }")
        assert len(packets) == 1
        page.evaluate("""() => {
            const packet = window.controlPacket;
            packet.remove();
            document.body.append(packet);
        }""")
        page.evaluate("async () => { await window.t018_record_peak(1); }")
        assert len(packets) == 2
        assert [packet['event'] for packet in packets] == ['instrument-control', 'instrument-control']
        assert [packet['count'] for packet in packets] == ['1', '1']
        page.evaluate("""() => {
            const parent = document.createElement('section');
            const subtree = document.createElement('div');
            subtree.innerHTML = '<span data-testid="relay-packet" data-event-id="subtree-control">'
                + '<span data-testid="packet-observation-count">1</span></span>';
            document.body.append(parent);
            parent.append(subtree);
        }""")
        page.evaluate("async () => { await window.t018_record_peak(2); }")
        assert len(packets) == 3, "One subtree insertion must not be counted through two ancestors"
        assert packets[-1]['event'] == 'subtree-control'
    finally:
        context.close()


@pytest.mark.parametrize("width", (390, 768, 1440))
def test_offline_no_script_snapshot_remains_readable_and_responsive(installed_browser, width):
    """T027 static fallback only; interactive accessibility and real-mission UAT stay separate."""
    from playwright.sync_api import expect
    context = installed_browser.new_context(java_script_enabled=False, viewport={"width": width, "height": 900})
    snapshot = _snapshot((_observation(),))
    document = _render(snapshot)
    context.route("**/*", lambda route: route.fulfill(status=200, content_type="text/html", body=document)
                  if route.request.url == DOCUMENT_URL else route.abort())
    try:
        page = context.new_page()
        page.goto(DOCUMENT_URL)
        expect(page.get_by_test_id("mission-authority")).to_contain_text(str(MISSION))
        expect(page.get_by_test_id("observation-count")).to_have_text("1")
        expect(page.get_by_test_id("source-count")).to_have_text("1")
        # Chromium's execution-disable switch does not change the HTML parser's
        # scripting flag. Check the noscript source separately; visible facts above
        # and below prove the fallback without depending on that browser mechanism.
        assert "JavaScript is unavailable" in page.locator("noscript").text_content()
        expect(page.get_by_test_id("stage-inspector")).to_contain_text(snapshot.evidence[0].title)
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), "Offline snapshot overflows the page horizontally"
        output = Path(__file__).resolve().parents[2] / ".handoff/spec014/t027" / f"offline-{width}.png"
        page.screenshot(path=str(output), full_page=True)
    finally:
        context.close()


def test_sources_measured_empty_and_unmeasured_channels_remain_distinct(installed_browser):
    """A missing channel count must remain Unknown rather than become measured zero."""
    from playwright.sync_api import expect
    from ignis.domain.harness_models import ChannelHealthStatus
    from ignis.domain.mission_relay import RelayChannelOutcome
    channels = (
        RelayChannelOutcome(platform="YOUTUBE", connector_surface="HTTP", status=ChannelHealthStatus.EMPTY_NO_DATA,
            signals_collected=0, completed_at=NOW, note="Measured fixture empty"),
        RelayChannelOutcome(platform="THREADS", connector_surface=None, status=None,
            signals_collected=None, completed_at=None, note=None),
    )
    with _viewer(installed_browser, _snapshot(channels=channels)) as viewer:
        viewer.page.get_by_role("button", name="Sources", exact=True).click()
        output = viewer.page.get_by_test_id("stage-inspector").get_by_role("region", name="Output", exact=True)
        measured = output.locator('[data-channel-platform="YOUTUBE"]')
        unknown = output.locator('[data-channel-platform="THREADS"]')
        expect(measured).to_contain_text("EMPTY_NO_DATA")
        expect(measured.get_by_test_id("channel-count")).to_have_text("0")
        expect(unknown.get_by_test_id("channel-count")).to_have_text("Unknown")
        expect(unknown).to_contain_text("Unknown")


def test_source_evidence_roles_are_selectable_without_motion(installed_browser):
    """Direct inspector selection preserves stored associations and judgments."""
    from playwright.sync_api import expect
    rows = (
        _observation(1, evidence_role=EvidenceRole.MARKET_EVIDENCE, direction=EvidenceDirection.SUPPORT,
            qualification_relation=QualificationRelation.QUALIFIED_SUPPORT, qualification_frame_fingerprint="b" * 64),
        _observation(2, evidence_role=EvidenceRole.MARKET_EVIDENCE, direction=EvidenceDirection.CONTRADICTION,
            qualification_relation=QualificationRelation.QUALIFIED_CONTRADICTION, qualification_frame_fingerprint="b" * 64),
        _observation(3, evidence_role=EvidenceRole.ATTENTION_CONTEXT, direction=EvidenceDirection.CONTEXT,
            qualification_relation=QualificationRelation.CONTEXT_ONLY, qualification_frame_fingerprint="b" * 64),
        _observation(4, evidence_role=EvidenceRole.MARKET_EVIDENCE, direction=None,
            qualification_relation=QualificationRelation.EXCLUDED_IRRELEVANT, qualification_frame_fingerprint="b" * 64),
    )
    with _viewer(installed_browser, _snapshot(rows, surface=ResearchSurface.MARKET)) as viewer:
        for row in rows:
            viewer.page.get_by_role("button", name="Sources", exact=True).click()
            viewer.page.get_by_test_id("stage-inspector").get_by_role("button", name=row.title, exact=True).click()
            inspector = viewer.page.get_by_test_id("stage-inspector")
            for value in (str(row.observation_id), str(row.source_id), row.evidence_role.value,
                          row.qualification_relation.value, "b" * 64):
                expect(inspector).to_contain_text(value)
            expect(inspector).to_contain_text(row.direction.value if row.direction is not None else "Unknown")
        assert viewer.packets == [], "Direct inspection must not manufacture arrivals"


def _set_visible(page, visible):
    page.evaluate("""visible => {
        Object.defineProperty(document, 'visibilityState', {configurable: true, value: visible ? 'visible' : 'hidden'});
        document.dispatchEvent(new Event('visibilitychange'));
    }""", visible)


def test_refresh_hidden_and_paused_boundaries_admit_no_automatic_reads(installed_browser):
    """Fixture visibility signal only; actual host/browser visibility UAT stays separate."""
    from playwright.sync_api import expect
    with _viewer(installed_browser, _snapshot()) as viewer:
        _set_visible(viewer.page, False)
        viewer.page.clock.run_for(6000)
        assert not [path for method, path in viewer.requests if path.endswith('/snapshot')]
        _set_visible(viewer.page, True)
        viewer.refresh(_snapshot())
        before = len([path for method, path in viewer.requests if path.endswith('/snapshot')])
        viewer.page.get_by_role('button', name='Pause refresh', exact=True).click()
        viewer.page.clock.run_for(6000)
        assert len([path for method, path in viewer.requests if path.endswith('/snapshot')]) == before
        expect(viewer.page.get_by_test_id('snapshot-state')).to_contain_text(re.compile('paused', re.I))
        viewer.page.get_by_role('button', name='Resume refresh', exact=True).click()
        viewer.refresh(_snapshot((_observation(),), (_event(observations=(_observation(),)),)))
        viewer.counts(1, 1)
        assert viewer.packets == [], 'Resuming refresh establishes a baseline, rather than replaying history'


def test_expired_view_admits_no_new_automatic_reads(installed_browser):
    from playwright.sync_api import expect
    viewer = FixtureViewer(installed_browser, _snapshot())
    viewer.document = _render(_snapshot(), expires_at=NOW + timedelta(seconds=1))
    try:
        viewer.open()
        viewer.page.clock.run_for(6000)
        assert not [path for method, path in viewer.requests if path.endswith('/snapshot')]
        expect(viewer.page.get_by_test_id('snapshot-state')).to_contain_text(re.compile('expired', re.I))
        assert viewer.packets == []
    finally:
        viewer.close()


def test_motion_pause_and_reduced_motion_preserve_static_evidence(installed_browser):
    from playwright.sync_api import expect
    observation = _observation()
    event = _event(observations=(observation,))
    with _viewer(installed_browser, _snapshot()) as viewer:
        viewer.page.get_by_role('button', name='Pause motion', exact=True).click()
        viewer.refresh(_snapshot((observation,), (event,)))
        viewer.counts(1, 1)
        assert viewer.packets == []
        expect(_event_row(viewer.page, event)).to_be_visible()
    viewer = FixtureViewer(installed_browser, _snapshot())
    viewer.page.emulate_media(reduced_motion='reduce')
    try:
        viewer.open()
        viewer.refresh(_snapshot((observation,), (event,)))
        viewer.counts(1, 1)
        assert viewer.packets == []
        expect(_event_row(viewer.page, event)).to_be_visible()
    finally:
        viewer.close()


def test_older_or_foreign_refresh_never_replaces_selected_snapshot(installed_browser):
    from playwright.sync_api import expect
    row = _observation()
    recorded = _snapshot((row,), (_event(observations=(row,)),))
    foreign = replace(_snapshot(), mission_id=UUID(int=9001),
        high_water=MissionRelayCursor(mission_id=UUID(int=9001), revision=0, ordinal=0), event_page=None)
    with _viewer(installed_browser, recorded) as viewer:
        for bad in (_snapshot(), foreign):
            viewer.refresh(bad)
            viewer.counts(1, 1)
            expect(viewer.page.get_by_test_id('mission-authority')).to_contain_text(str(MISSION))
            expect(viewer.page.get_by_test_id('snapshot-state')).to_contain_text(re.compile('stale|discarded|incompatible', re.I))
        assert viewer.packets == []


def test_unavailable_refresh_keeps_last_counts_and_marks_them_stale(installed_browser):
    from playwright.sync_api import expect
    from ignis.domain.mission_relay import MissionRelayReadFailure, RelayReadReason, RelayReadStatus
    with _viewer(installed_browser, _snapshot((_observation(),))) as viewer:
        viewer.refresh(MissionRelayReadFailure(status=RelayReadStatus.UNAVAILABLE, reason_code=RelayReadReason.READ_UNAVAILABLE))
        viewer.counts(1, 1)
        expect(viewer.page.get_by_test_id('snapshot-state')).to_contain_text(re.compile('stale', re.I))
        viewer.page.get_by_role('button', name='Synthesis', exact=True).click()
        expect(viewer.page.get_by_test_id('stage-inspector')).to_contain_text(re.compile('withheld|unavailable', re.I))


def test_refresh_schedules_only_after_previous_request_settles(installed_browser):
    from playwright.sync_api import expect
    viewer = FixtureViewer(installed_browser, _snapshot())
    held = []
    original = viewer._route
    def hold_snapshot(route):
        if urlsplit(route.request.url).path.endswith('/snapshot'):
            viewer.requests.append(('GET', '/view/inert-fixture/snapshot'))
            held.append(route)
        else:
            original(route)
    viewer.context.unroute('**/*')
    viewer.context.route('**/*', hold_snapshot)
    try:
        viewer.open()
        with viewer.page.expect_request(lambda request: urlsplit(request.url).path.endswith('/snapshot')):
            viewer.page.clock.run_for(5000)
        viewer.page.evaluate('async () => { await Promise.resolve(); await Promise.resolve(); }')
        assert len(held) == 1, 'Automatic refresh overlapped an unresolved read'
        settled = _snapshot(event_page=MissionRelayEventPage(high_water=_cursor(),
            page_size=200, events=(), after_cursor=_cursor())).to_payload()
        with viewer.page.expect_response(lambda response: urlsplit(response.url).path.endswith('/snapshot')):
            held[0].fulfill(status=200, content_type='application/json', body=json.dumps(settled))
        expect(viewer.page.get_by_test_id('snapshot-state')).to_contain_text('particle motion encodes receipts')
        viewer.page.clock.run_for(1900)
        assert len(held) == 1, 'Refresh scheduled before two seconds after settlement'
        with viewer.page.expect_request(lambda request: urlsplit(request.url).path.endswith('/snapshot')):
            viewer.page.clock.run_for(201)
        viewer.page.evaluate('async () => { await Promise.resolve(); await Promise.resolve(); }')
        assert len(held) == 2
        held[1].fulfill(status=200, content_type='application/json', body=json.dumps(settled))
    finally:
        viewer.close()


def test_incomplete_event_page_cannot_advance_refresh_cursor(installed_browser):
    from playwright.sync_api import expect
    row, new = _observation(), _observation(2)
    initial = _snapshot((row,), (_event(observations=(row,)),))
    bad = _snapshot((row, new), (_event(observations=(row,)), _event(2, (new,)))).to_payload()
    bad['event_page'].update(events=[], after_cursor=initial.high_water.to_payload(), has_more=False, next_cursor=None)
    with _viewer(installed_browser, initial) as viewer:
        viewer.page.evaluate('''data => {
            window.calls = [];
            window.fetch = async url => { calls.push(url); return {ok: true, json: async () => data}; };
        }''', bad)
        viewer.page.clock.run_for(2001)
        expect(viewer.page.get_by_test_id('snapshot-state')).to_contain_text('Stale')
        viewer.counts(1, 1)
        viewer.page.clock.run_for(2001)
        assert 'after_revision=1' in viewer.page.evaluate('calls')[1]
        assert viewer.packets == []


def test_inspection_waits_for_refresh_and_retains_selected_observation(installed_browser):
    from playwright.sync_api import expect
    row = _observation()
    initial = _snapshot((row,), (_event(observations=(row,)),))
    inspection = MissionRelayInspection(mission_id=MISSION, run_id=RUN,
        high_water=initial.high_water, read_at=NOW, observation=row)
    with _viewer(installed_browser, initial) as viewer:
        viewer.page.evaluate('''() => {
            window.calls = []; window.replies = [];
            window.fetch = url => new Promise(resolve => {
                calls.push(url); replies.push(data => resolve({ok: true, json: async () => data}));
            });
        }''')
        viewer.page.clock.run_for(2001)
        viewer.page.get_by_test_id('stage-inspector').get_by_role('button', name=row.title, exact=True).click()
        assert len(viewer.page.evaluate('calls')) == 1, 'Inspection overlapped the pending refresh'
        settled = replace(initial, event_page=MissionRelayEventPage(high_water=initial.high_water,
            page_size=200, events=(), after_cursor=initial.high_water)).to_payload()
        viewer.page.evaluate('data => replies[0](data)', settled)
        expect(viewer.page.get_by_test_id('stage-inspector')).to_contain_text('Inspection pending')
        assert len(viewer.page.evaluate('calls')) == 2
        assert viewer.page.evaluate('calls')[1].startswith('inspect/')
        viewer.page.evaluate('data => replies[1](data)', inspection.to_payload())
        expect(viewer.page.get_by_test_id('stage-inspector').get_by_role('heading', name='Evidence inspection', exact=True)).to_be_visible()
        expect(viewer.page.get_by_test_id('stage-inspector')).to_contain_text(row.title)
