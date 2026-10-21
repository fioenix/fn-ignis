"""T029: handles written inside the content become tokens (Spec 015, US3, research R7).

An undeclared `@mention` is stored as `@[user]`. A mention of a declared account is stored as a
token naming the declaration, renders as the declared name, and renders as `@[user]` once the
declaration is withdrawn, without rewriting the stored text. Email and phone redaction is
untouched.
"""

from datetime import datetime, timezone

import pytest

from ignis.application.author_policy import apply_author_policy
from ignis.domain.author_identity import DeclaredAccount
from ignis.domain.entities import ResearchMission, TrendSignal
from ignis.domain.value_objects import GeoCode, PlatformType
from ignis.infrastructure.security.pii_sanitizer import (
    render_mention_tokens,
    sanitize_pii_text,
    tokenise_mentions,
)
from ignis.infrastructure.templates.html_builder import HtmlArtifactBuilder

from tests.fixtures.author_identity_sentinels import (
    DECLARED_BRAND_HANDLE,
    DECLARED_BRAND_NAME,
    DECLARED_MENTION_TEXT,
    MENTION_TEXT,
    SENTINEL_MENTIONED_HANDLE,
)

DECLARED_ID = "6f1c2c47-8a43-4c1e-9b1e-3d7a2b9c0001"


def test_an_undeclared_mention_is_stored_as_a_user_token():
    assert tokenise_mentions("@linh.nguyen mua ở đâu vậy", {}) == "@[user] mua ở đâu vậy"
    assert tokenise_mentions("Hỏi @linh.nguyen.", {}) == "Hỏi @[user]."
    assert tokenise_mentions(MENTION_TEXT, {}).startswith("@[user] mua ở đâu vậy")


def test_a_declared_mention_is_kept_as_a_token_and_renders_by_name():
    stored = tokenise_mentions(f"Áo của @{DECLARED_BRAND_HANDLE.upper()} mặc mát không?", {DECLARED_BRAND_HANDLE: DECLARED_ID})

    assert stored == f"Áo của @[declared:{DECLARED_ID}] mặc mát không?"
    assert render_mention_tokens(stored, {DECLARED_ID: DECLARED_BRAND_NAME}) == f"Áo của @{DECLARED_BRAND_NAME} mặc mát không?"


def test_after_withdrawal_the_token_renders_as_a_user():
    stored = tokenise_mentions(DECLARED_MENTION_TEXT, {DECLARED_BRAND_HANDLE: DECLARED_ID})

    assert render_mention_tokens(stored, {}) == "Áo của @[user] mặc mát không mọi người?"


def test_email_and_phone_redaction_is_unchanged():
    text = "Liên hệ seller@example.test hoặc 0931.405.002, hỏi @shop.a nhé"

    tokenised = tokenise_mentions(text, {})

    assert tokenised == "Liên hệ seller@example.test hoặc 0931.405.002, hỏi @[user] nhé"
    assert sanitize_pii_text(tokenised) == "Liên hệ [REDACTED_EMAIL] hoặc [REDACTED_PHONE], hỏi @[user] nhé"


def test_the_policy_tokenises_titles_captions_and_comments_but_not_queries():
    now = datetime.now(timezone.utc)
    signal = TrendSignal(
        platform=PlatformType.TIKTOK,
        raw_title=MENTION_TEXT,
        source_url="https://www.tiktok.com/share/video/1",
        captured_at=now,
        metadata={
            "item_id": "1",
            "keyword": "@query.term",
            "excerpt": DECLARED_MENTION_TEXT,
            "comments": [{"text": f"@{SENTINEL_MENTIONED_HANDLE} đẹp"}],
        },
    )
    declared = [
        DeclaredAccount(DECLARED_ID, "m", "tiktok", DECLARED_BRAND_HANDLE, DECLARED_BRAND_NAME, datetime(2026, 1, 1, tzinfo=timezone.utc))
    ]

    apply_author_policy([signal], None, declared_accounts=declared)

    assert SENTINEL_MENTIONED_HANDLE not in str(signal)
    assert signal.raw_title.startswith("@[user]")
    assert signal.metadata["excerpt"] == f"Áo của @[declared:{DECLARED_ID}] mặc mát không mọi người?"
    assert signal.metadata["comments"] == [{"text": "@[user] đẹp"}]
    # A query is the requester's own words, and part of a Google source's identity.
    assert signal.metadata["keyword"] == "@query.term"


def test_a_report_renders_declared_tokens_by_name_and_others_as_users():
    signal = TrendSignal(
        platform=PlatformType.TIKTOK, raw_title=f"Áo của @[declared:{DECLARED_ID}] và @[user]",
        source_url="https://www.tiktok.com/share/video/1", geo_code=GeoCode.VN,
        metadata={"item_id": "1"},
    )
    mission = ResearchMission(title="Áo khoác", keywords=["áo khoác"], shortcode="IGN-M", geo_code=GeoCode.VN)

    named = HtmlArtifactBuilder().build_mission_report_artifact(
        mission=mission, signals=[signal], platform_breakdown={"tiktok": 1},
        declared_names={DECLARED_ID: DECLARED_BRAND_NAME},
    )
    withdrawn = HtmlArtifactBuilder().build_mission_report_artifact(
        mission=mission, signals=[signal], platform_breakdown={"tiktok": 1},
    )

    assert f"Áo của @{DECLARED_BRAND_NAME} và @[user]" in named
    assert DECLARED_ID not in withdrawn and "Áo của @[user] và @[user]" in withdrawn


@pytest.mark.asyncio
async def test_mcp_answers_render_declared_tokens_by_name():
    from unittest.mock import AsyncMock

    from ignis.application.use_cases.get_evidence_qualification_batch import GetEvidenceQualificationBatchUseCase
    from ignis.application.use_cases.get_mission_analysis import GetMissionAnalysisUseCase

    mission = ResearchMission(title="Áo khoác", keywords=["áo khoác"])
    signal = TrendSignal(
        platform=PlatformType.TIKTOK, raw_title=f"Áo của @[declared:{DECLARED_ID}] và @[user]",
        source_url="https://www.tiktok.com/share/video/1", metadata={"excerpt": f"@[declared:{DECLARED_ID}] đẹp"},
    )
    repository = AsyncMock()
    repository.get_mission.return_value = mission
    repository.get_mission_signals.return_value = [signal]
    repository.list_mission_declared_accounts.return_value = [
        DeclaredAccount(DECLARED_ID, str(mission.id), "tiktok", DECLARED_BRAND_HANDLE, DECLARED_BRAND_NAME, datetime(2026, 1, 1, tzinfo=timezone.utc))
    ]

    analysis = await GetMissionAnalysisUseCase(repository).execute(mission.id)
    row = GetEvidenceQualificationBatchUseCase._evidence(signal, {DECLARED_ID: DECLARED_BRAND_NAME})

    assert analysis["top_signals"][0]["title"] == f"Áo của @{DECLARED_BRAND_NAME} và @[user]"
    assert (row["title"], row["excerpt"]) == (f"Áo của @{DECLARED_BRAND_NAME} và @[user]", f"@{DECLARED_BRAND_NAME} đẹp")


# --- T038 review findings 2, 3, 6 and 13 -----------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "stored"),
    [
        ("＠Đạt quá đẹp", "@[user] quá đẹp"),
        ("hỏi @nguyen-van nhé", "hỏi @[user] nhé"),
        ("cảm ơn＠abc", "cảm ơn@[user]"),
        ("cảm ơn@abc nha", "cảm ơn@[user] nha"),
        ("fullwidth ＠bob", "fullwidth @[user]"),
        ("@Ngọc.Ánh_99.", "@[user]."),
        ("liên hệ seller@example.test", "liên hệ seller@example.test"),
    ],
)
def test_every_mention_shape_becomes_a_token_and_emails_do_not(text, stored):
    assert tokenise_mentions(text, {}) == stored


def test_a_collected_literal_token_cannot_pose_as_a_declaration():
    forged = f"mua ở @[declared:{DECLARED_ID}] đi"

    assert tokenise_mentions(forged, {DECLARED_BRAND_HANDLE: DECLARED_ID}) == "mua ở @[user] đi"


def test_a_profile_link_written_inside_text_is_removed():
    signal = TrendSignal(
        platform=PlatformType.TIKTOK,
        raw_title="follow https://www.instagram.com/nguyenvana nhé",
        source_url="https://www.tiktok.com/share/video/1",
        captured_at=datetime.now(timezone.utc),
        metadata={"item_id": "1", "excerpt": "kênh www.youtube.com/@Đạt, video https://www.youtube.com/watch?v=abc123"},
    )

    apply_author_policy([signal], None)

    assert signal.raw_title == "follow [link] nhé"
    assert signal.metadata["excerpt"] == "kênh [link], video https://www.youtube.com/watch?v=abc123"


def test_the_guard_refuses_a_link_that_names_an_account_inside_text():
    from ignis.domain.author_identity import author_identity_violation

    assert author_identity_violation({}, None, title="follow https://www.instagram.com/nguyenvana") is not None
    assert author_identity_violation({"excerpt": "xem tiktok.com/@abc/video/1"}, None) is not None
    assert author_identity_violation({"excerpt": "xem https://www.tiktok.com/share/video/1"}, None, title="ok") is None


def test_rows_stored_before_the_policy_are_masked_on_read():
    legacy_title = "@legacy.user hỏi giá, xem https://www.tiktok.com/@legacy.user"

    assert render_mention_tokens(legacy_title, {}) == "@[user] hỏi giá, xem [link]"
    # A token the policy wrote still renders by name.
    assert render_mention_tokens(f"@[declared:{DECLARED_ID}] và @legacy", {DECLARED_ID: "Brand"}) == "@Brand và @[user]"


def test_a_citation_over_a_legacy_row_shows_no_raw_mention():
    from ignis.infrastructure.harness.strategic_reasoner import StrategicMarketReasoner

    legacy = TrendSignal(
        platform=PlatformType.TIKTOK, raw_title=f"{MENTION_TEXT}", source_url="https://www.tiktok.com/share/video/1",
        metadata={"excerpt": MENTION_TEXT},
    )

    citation = StrategicMarketReasoner()._build_citation(legacy, 1)

    assert SENTINEL_MENTIONED_HANDLE not in f"{citation.title_or_query} {citation.excerpt}"


def test_a_report_over_a_legacy_row_shows_no_raw_mention():
    legacy = TrendSignal(
        platform=PlatformType.TIKTOK, raw_title=MENTION_TEXT, source_url="https://www.tiktok.com/share/video/1",
        geo_code=GeoCode.VN, metadata={"item_id": "1"},
    )
    mission = ResearchMission(title="Áo khoác", keywords=["áo khoác"], shortcode="IGN-L", geo_code=GeoCode.VN)

    html = HtmlArtifactBuilder().build_mission_report_artifact(mission=mission, signals=[legacy], platform_breakdown={"tiktok": 1})

    assert SENTINEL_MENTIONED_HANDLE not in html
