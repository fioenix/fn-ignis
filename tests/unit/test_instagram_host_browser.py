"""Spec 025 Story 2: Instagram keyword-grid captions through the host browser, without author identity."""

import json
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from importlib.resources import files

import pytest

from ignis.domain.host_browser_search import HostSearchQuery, HostSearchRequest
from ignis.domain.research_workspace import RetiredSurfaceError, require_active_resources
from ignis.infrastructure.connectors.host_browser.validator import validate_answer

SEARCH = "https://www.instagram.com/explore/search/keyword/?q=%C3%A1o%20kho%C3%A1c"
TEMPLATES = ("Photo by {author} on",)


def _later():
    """The validator runs after capture; give the clock a second so capture is inside the lifetime."""
    return datetime.now(timezone.utc) + timedelta(seconds=1)


def _request(limit=5):
    now = datetime.now(timezone.utc)
    return HostSearchRequest(request_id="fixture", host_task_ref="task-1", session_ref="chrome-1", source="instagram",
        issued_at=now - timedelta(seconds=1), expires_at=now + timedelta(seconds=60),
        queries=(HostSearchQuery(query_id="q", query="áo khoác", search_url=SEARCH, result_limit=limit),))


def _answer(records, *, status="HEALTHY", locale="en", page=SEARCH, verified=True):
    return dict(source="instagram", request_id="fixture", host_task_ref="task-1", session_ref="chrome-1",
                extractor_version="instagram-keyword-grid-v1", answers=[dict(
                    query_id="q", query="áo khoác", page_url=page, captured_at=datetime.now(timezone.utc).isoformat(),
                    search_verified=verified, empty_state_visible=False, status=status, locale=locale, records=records)])


def test_caption_is_kept_and_identity_is_removed_before_the_receipt():
    records = [
        dict(source_url="https://www.instagram.com/p/DQx_1-a/", excerpt="Áo khoác gió @fixture.handle #aokhoac Photo by Fixture Seller on May 3, 2026."),
        dict(source_url="https://www.instagram.com/reel/DQx_2-b/", excerpt="Áo chống nắng giao nhanh"),
    ]
    sidecar = []
    receipt = validate_answer(_request(), _answer(records), _later(), TEMPLATES, author_records=sidecar)
    assert receipt["source"] == "instagram"
    first, second = receipt["observations"]
    assert first["source_url"] == "https://www.instagram.com/p/DQx_1-a"
    assert second["source_url"] == "https://www.instagram.com/p/DQx_2-b"
    assert "Fixture Seller" not in first["excerpt"] and "fixture.handle" not in first["excerpt"]
    assert "Áo khoác gió" in first["excerpt"] and "#aokhoac" in first["excerpt"]
    assert first["published_at"] is None and first["metric_known"] is False and "counters" not in first
    assert first["collection_path"] == "host_browser:instagram-keyword-grid-v1"
    assert first["sampling"] == {"limit": 5, "ordering": "visible_grid"}
    [outcome] = receipt["outcomes"]
    assert outcome["status"] == "HEALTHY" and outcome["signals_collected"] == 2
    assert outcome["note"] == "Bounded visible keyword grid captions; window, dates and counters unmeasured"


@pytest.mark.parametrize("url", [
    "https://www.instagram.com/fixture.account/p/DQx_1-a/",
    "https://www.instagram.com/fixture.account/",
    "https://www.threads.com/t/DQx_1-a",
    "https://www.tiktok.com/share/video/7417820067028536584",
])
def test_account_and_cross_source_urls_are_rejected(url):
    with pytest.raises(ValueError):
        validate_answer(_request(), _answer([dict(source_url=url, excerpt="Caption")]), _later(), TEMPLATES)


def test_a_page_other_than_the_keyword_grid_is_rejected():
    page = "https://www.instagram.com/explore/tags/aokhoac/?q=%C3%A1o%20kho%C3%A1c"
    with pytest.raises(ValueError, match="Search page"):
        validate_answer(_request(), _answer([], status="DEGRADED", page=page), _later(), TEMPLATES)


def test_an_empty_or_unproved_grid_is_degraded_never_empty_no_data():
    receipt = validate_answer(_request(), _answer([], status="DEGRADED", locale="unsupported", verified=False), _later(), TEMPLATES)
    [outcome] = receipt["outcomes"]
    assert outcome["status"] == "DEGRADED" and receipt["observations"] == []
    assert outcome["note"] == "Instagram page locale is unsupported; no observations collected"
    with pytest.raises(ValueError):
        validate_answer(_request(), _answer([], status="EMPTY_NO_DATA"), _later(), TEMPLATES)


def test_counters_cannot_be_reported_for_instagram():
    counter = dict(kind="likes", unit="count", raw_display="12", value=12, precision="exact")
    record = dict(source_url="https://www.instagram.com/p/DQx_1-a/", excerpt="Caption", counters=[counter])
    with pytest.raises(ValueError, match="counters"):
        validate_answer(_request(), _answer([record]), _later(), TEMPLATES)


def test_the_retired_reels_surface_stays_refused():
    with pytest.raises(RetiredSurfaceError) as refused:
        require_active_resources(["reels"])
    assert refused.value.to_payload()["reason_code"] == "SURFACE_RETIRED"


def _node(code, *args):
    node = shutil.which("node")
    assert node, "Node is required for the extractor contract"
    result = subprocess.run([node, "-e", code, *args], capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


EXTRACT = r'''
const vm=require('vm');
const [extractor, href, lang, tilesJSON, login]=process.argv.slice(1);
const tiles=JSON.parse(tilesJSON);
const anchor=t=>({getAttribute:()=>t.href, getClientRects:()=>[1], closest:()=>t.nav?{}:null,
  querySelector:()=>t.alt===null?null:{getAttribute:()=>t.alt}});
const document={documentElement:{lang}, querySelector:()=>login==='yes'?{}:null, querySelectorAll:()=>tiles.map(anchor)};
const result=vm.runInNewContext('('+extractor+')({query_id:"q",query:"áo khoác",result_limit:3})',
  {document, location:{href}, URL, Date, Map, Number});
console.log(JSON.stringify(result));
'''


def _extract(tiles, *, href=SEARCH, lang="en", login="no"):
    extractor = files("ignis.infrastructure.connectors.host_browser").joinpath("instagram_search.js").read_text()
    return _node(EXTRACT, extractor, href, lang, json.dumps(tiles), login)


def test_extractor_keeps_tile_captions_and_skips_tiles_without_one():
    result = _extract([
        dict(href="/p/AAA/", alt="Áo khoác​ gió\nmàu xanh"),
        dict(href="/p/BBB/", alt=""),
        dict(href="/reel/CCC/", alt=None),
        dict(href="/fixture.account/", alt="Profile"),
        dict(href="/p/DDD/", alt="Nav caption", nav=True),
        dict(href="/p/AAA/", alt="Duplicate"),
        dict(href="/reel/EEE/", alt="Áo chống nắng"),
    ])
    assert result["status"] == "HEALTHY" and result["search_verified"] is True and result["locale"] == "en"
    assert result["records"] == [
        dict(source_url="https://www.instagram.com/p/AAA/", excerpt="Áo khoác gió\nmàu xanh", published_at=None),
        dict(source_url="https://www.instagram.com/reel/EEE/", excerpt="Áo chống nắng", published_at=None),
    ]


@pytest.mark.parametrize("kwargs", [
    dict(login="yes"),
    dict(lang=""),
    dict(href="https://www.instagram.com/explore/search/keyword/?q=other"),
    dict(href="https://www.instagram.com/explore/tags/aokhoac/"),
])
def test_extractor_reports_degraded_without_records_off_the_signed_in_grid(kwargs):
    result = _extract([dict(href="/p/AAA/", alt="Caption")], **kwargs)
    assert result["status"] == "DEGRADED" and result["records"] == []


def test_extractor_without_captions_is_degraded():
    result = _extract([dict(href="/p/AAA/", alt="")])
    assert result["status"] == "DEGRADED" and result["records"] == [] and result["search_verified"] is True
