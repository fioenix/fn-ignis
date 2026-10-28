"""Capability skills stay thin pointers to one persisted evidence contract."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
COLLECT = ROOT / ".agents/skills/ignis-collect/SKILL.md"
ANALYZE = ROOT / ".agents/skills/ignis-analyze/SKILL.md"
ROUTINE = ROOT / ".agents/skills/ignis-routine/SKILL.md"


def test_collection_and_analysis_skills_are_independently_discoverable():
    collection = COLLECT.read_text(encoding="utf-8")
    analysis = ANALYZE.read_text(encoding="utf-8")

    assert collection.startswith("---\nname: ignis-collect\n")
    assert analysis.startswith("---\nname: ignis-analyze\n")
    assert "description:" in collection.split("---", 2)[1]
    assert "description:" in analysis.split("---", 2)[1]
    assert "execute_mission_ingress" in collection
    assert "get_mission_analysis" in analysis
    assert "get_mission_claims" in analysis


def test_skills_share_the_repository_contract_without_forking_policy():
    collection = COLLECT.read_text(encoding="utf-8")
    analysis = ANALYZE.read_text(encoding="utf-8")
    shared_pointer = "specs/011-evidence-grounded-product-reset/contracts/"

    assert shared_pointer in collection and shared_pointer in analysis
    assert "Mission Manifest" in collection
    assert "Claim Ledger" in analysis
    assert "Gap Report" in analysis
    for content in (collection, analysis):
        assert "daily" not in content.casefold()
        assert "scheduler" not in content.casefold()
        assert "API_KEY" not in content
        assert "password" not in content.casefold()
        assert "70%" not in content
        assert "Opportunity Index" not in content
        assert "<html" not in content.casefold()
        assert len(content.splitlines()) < 100


def test_capability_examples_keep_external_data_as_context():
    collect_example = (
        COLLECT.parent / "examples/collection-frame.md"
    ).read_text(encoding="utf-8")
    analyze_example = (
        ANALYZE.parent / "examples/claim-ledger.md"
    ).read_text(encoding="utf-8")

    assert "AUTH_REQUIRED" in collect_example
    assert "EMPTY_NO_DATA" in collect_example
    assert "CONTRADICTION" in analyze_example
    assert "CONTEXT_ONLY" in analyze_example
    assert "frame_digest" in analyze_example


def test_analysis_reads_concentration_as_a_signal_without_identifying_authors():
    """Spec 015 T028: voices are counted, never named."""
    analysis = ANALYZE.read_text(encoding="utf-8")

    assert "author_concentration" in analysis
    assert "top_share" in analysis
    assert "seeding" in analysis
    assert "declared account" in analysis
    assert "unavailable" in analysis


def _host_browser_section():
    collection = COLLECT.read_text(encoding="utf-8")
    return " ".join(collection.split("## Opt-in host-browser search\n", 1)[1].split("\n## ", 1)[0].split())


def test_host_browser_search_covers_both_sources_in_one_mission_run():
    section = _host_browser_section()
    for rule in ('source="tiktok"', 'source="threads"', "sibling tickets", "one mission run",
                 "stage both", "IDs only", "read back", "not a default collector or an automatic fallback"):
        assert rule in section, rule


def test_host_transport_is_checked_before_preparing_search():
    section = _host_browser_section()
    for rule in ("Before prepare", "open a tab", "click in the relay", "evaluate read-only script",
                 "close tabs it opened", "unsupported transport", "stop before collection"):
        assert rule in section, rule


def test_host_browser_confirms_requester_browser_and_origin_permissions():
    section = _host_browser_section()
    for rule in ("Before opening the relay", "browser/profile the requester named",
                 "confirm the host tooling is connected to it", "several browsers", "ask the requester which",
                 "source site or loopback relay", "grant access in the host", "unavailable for this run"):
        assert rule in section, rule


def test_source_tabs_are_read_only_and_follow_the_fixed_query_sequence():
    section = _host_browser_section()
    for rule in ("read-only", "no typing, clicking, scrolling, signing in, consenting or challenge solving",
                 "cancellation/expiry and owner interruption", 'click "Open search"',
                 "wait for results to load", "evaluate `tab_script` once", "read its status and counts",
                 "Search answer JSON", "retained object", "Stage answer"):
        assert rule in section, rule
    assert section.index("cancellation/expiry and owner interruption") < section.index('click "Open search"')
    assert section.index("wait for results to load") < section.index("evaluate `tab_script` once")


def test_blocked_source_queries_stop_report_and_move_on_without_retry():
    section = _host_browser_section()
    for rule in ("sign-in wall", "challenge", "error page", "missing grid", "`DEGRADED`",
                 "validator rejects a mismatched page", "stop that query", "outcome as reported",
                 "tell the requester", "move on", "no retry loop or other collector"):
        assert rule in section, rule


def test_host_search_preserves_evidence_limits_and_finally_cleanup():
    section = _host_browser_section()
    for rule in ("verified no-results", "unknown", "bounded sample", "finally path",
                 "cancel a nonterminal request", "Preserve owner tabs and browser",
                 "model-built records", "Reels keeps its flag-free Playwright path"):
        assert rule in section, rule


def test_routine_distinguishes_threads_host_search_from_saved_sign_in():
    routine = " ".join(ROUTINE.read_text(encoding="utf-8").split())
    assert "`reels` and `tiktok_video_grid` need a saved sign-in: check `get_platform_auth_status`." in routine
    assert "`threads` collects only through host-browser search" in routine
    assert "host-browser search section of the `ignis-collect` skill" in routine
    assert "`threads`, `reels` and `tiktok_video_grid` need a saved sign-in" not in routine


def test_manual_stage_requires_the_complete_envelope_and_reprepare_after_rejection():
    section = _host_browser_section()
    for rule in ("full envelope", "`source`", "Threads only", "`request_id`", "`host_task_ref`",
                 "`session_ref`", "`extractor_version`", "`answers`", "one answer per approved query",
                 "prepare order", "extractor's retained object", "never reconstruct, transcribe or repair",
                 "rejected payload closes the relay", "prepare a new ticket"):
        assert rule in section, rule
    raw = COLLECT.read_text(encoding="utf-8").split("## Opt-in host-browser search\n", 1)[1]
    assert len(raw.splitlines()) <= 50
