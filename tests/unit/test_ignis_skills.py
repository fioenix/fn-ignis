"""Capability skills stay thin pointers to one persisted evidence contract."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
COLLECT = ROOT / ".agents/skills/ignis-collect/SKILL.md"
ANALYZE = ROOT / ".agents/skills/ignis-analyze/SKILL.md"


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
