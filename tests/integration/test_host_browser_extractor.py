"""Run packaged JavaScript against controlled public-card DOM facts."""

import json
from pathlib import Path
import shutil
import subprocess

import pytest


EXTRACTOR = Path(__file__).resolve().parents[2] / "src/ignis/infrastructure/connectors/host_browser/tiktok_search.js"


def extract(query="túi đi làm", page_query="túi đi làm", card_text="Túi đi làm", image_alt="", image_visible=True):
    assert EXTRACTOR.exists(), "The packaged deterministic extractor is missing"
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required for deterministic JavaScript fixture execution")
    code = """
      const fs = require('fs'), vm = require('vm');
      const makeCard = (url, text, visible) => ({
        getClientRects: () => visible ? [1] : [],
        innerText: text,
        querySelector: selector => selector === 'a[href*="/video/"]' ? {
          href: url,
          querySelectorAll: selector => selector === 'img[alt]' ? [{
            getAttribute: name => name === 'alt' ? process.argv[5] : null,
            getClientRects: () => process.argv[6] === 'true' ? [1] : []
          }] : []
        } : null
      });
      const document = {
        querySelectorAll: selector => selector === 'div[data-e2e="search_top-item"], div[data-e2e="search_video-item"]' ? [
          makeCard('https://www.tiktok.com/@public/video/7417820067028536584?tracking=1', process.argv[4], true),
          makeCard('https://www.tiktok.com/messages', 'Private surface', true),
          makeCard('https://www.tiktok.com/@public/video/7417820067028536584', process.argv[4], true),
          makeCard('https://www.tiktok.com/@hidden/video/123', 'Hidden card', false),
          makeCard('https://www.tiktok.com/@photo/photo/123', 'Photo', true)
        ] : []
      };
      const fn = vm.runInNewContext('(' + fs.readFileSync(process.argv[1], 'utf8') + ')', {
        document, location: {href: 'https://www.tiktok.com/search?q=' + encodeURIComponent(process.argv[3])}, URL, Date
      });
      console.log(JSON.stringify(fn({query_id: 'query-1', query: process.argv[2], result_limit: 3})));
    """
    result = subprocess.run([node, "-e", code, str(EXTRACTOR), query, page_query, card_text,
                             image_alt, str(image_visible).lower()],
                            check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


def test_public_card_extractor_preserves_missingness_and_excludes_hidden_private_nonvideo():
    result = extract()
    assert result["status"] == "HEALTHY"
    assert result["records"] == [{
        "source_url": "https://www.tiktok.com/@public/video/7417820067028536584",
        "excerpt": "Túi đi làm", "published_at": None,
    }]
    assert result["empty_state_visible"] is False
    assert "metric_value" not in result["records"][0]


def test_wrong_query_grid_is_not_promoted_as_search_evidence():
    result = extract(page_query="wrong")
    assert result["status"] == "DEGRADED"
    assert result["search_verified"] is False
    assert result["records"] == []


@pytest.mark.parametrize("counter", ["290", "1,623", "5.2K", "2M", "522\n236"])
def test_counter_only_grid_is_degraded_not_content_evidence(counter):
    result = extract(card_text=counter)
    assert result["search_verified"] is True
    assert result["status"] == "DEGRADED"
    assert result["records"] == []


def test_counter_tile_uses_visible_video_image_label_as_content():
    label = "Túi đẹp nha anh em! #jivi #tuidilam do Trần Trọng Review tạo với bản nhạc Peace"
    result = extract(card_text="290", image_alt=label)
    assert result["status"] == "HEALTHY"
    assert result["records"] == [{
        "source_url": "https://www.tiktok.com/@public/video/7417820067028536584",
        "excerpt": label, "published_at": None,
    }]


@pytest.mark.parametrize("label,visible", [("Caption from hidden image", False), ("493", True), ("", True)])
def test_missing_hidden_or_counter_image_label_does_not_restore_content(label, visible):
    result = extract(card_text="290", image_alt=label, image_visible=visible)
    assert result["records"] == []
    assert result["status"] == "DEGRADED"
