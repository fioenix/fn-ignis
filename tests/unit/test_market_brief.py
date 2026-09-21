"""The Market Brief is the contract that authorizes a Market mission.

Seven fields, confirmed by a requester, immutable once confirmed. Everything here is about what
the domain refuses: an incomplete Brief, an empty falsifier list, and a mutation of a revision
that evidence has already been attached to.
"""

import dataclasses

import pytest

from ignis.domain.research_workspace import (
    REQUIRED_BRIEF_FIELDS,
    IncompleteMarketBriefError,
    MarketBriefRevision,
    missing_brief_fields,
)

COMPLETE_PAYLOAD = {
    "decision": "Should we test a VN-focused customer service assistant?",
    "target_user": "VN fashion retailers running their own support inbox",
    "problem": "Support replies take hours and lose the sale",
    "geo": "VN",
    "timeframe": "30d",
    "hypothesis": "VN retailers will pay for an assistant that answers in under a minute",
    "falsifiers": ["No retailer reports reply latency as a top-three cost"],
}


def _revision(**overrides):
    payload = {**COMPLETE_PAYLOAD, **overrides}
    return MarketBriefRevision(confirmed_by="requester@example.com", **payload)


def test_required_field_list_is_the_seven_the_specification_names():
    assert REQUIRED_BRIEF_FIELDS == (
        "decision",
        "target_user",
        "problem",
        "geo",
        "timeframe",
        "hypothesis",
        "falsifiers",
    )


@pytest.mark.parametrize("field_name", REQUIRED_BRIEF_FIELDS)
def test_every_required_field_is_named_when_it_is_missing(field_name):
    payload = {k: v for k, v in COMPLETE_PAYLOAD.items() if k != field_name}
    assert missing_brief_fields(payload) == [field_name]


@pytest.mark.parametrize("blank", ["", "   ", None])
def test_a_blank_text_field_counts_as_missing_rather_than_as_an_answer(blank):
    assert "hypothesis" in missing_brief_fields({**COMPLETE_PAYLOAD, "hypothesis": blank})


def test_falsifiers_holding_only_blank_entries_is_not_a_useful_falsifier():
    assert "falsifiers" in missing_brief_fields({**COMPLETE_PAYLOAD, "falsifiers": ["  ", ""]})


def test_constructing_an_incomplete_revision_names_every_missing_field():
    with pytest.raises(IncompleteMarketBriefError) as excinfo:
        MarketBriefRevision(
            confirmed_by="requester",
            decision="",
            target_user="",
            problem=COMPLETE_PAYLOAD["problem"],
            geo="VN",
            timeframe="30d",
            hypothesis=COMPLETE_PAYLOAD["hypothesis"],
            falsifiers=[],
        )
    assert excinfo.value.missing_fields == ["decision", "target_user", "falsifiers"]


def test_a_confirmed_revision_cannot_be_mutated():
    revision = _revision()
    with pytest.raises(dataclasses.FrozenInstanceError):
        revision.hypothesis = "something else"


def test_falsifiers_are_stored_as_an_immutable_sequence():
    revision = _revision()
    assert revision.falsifiers == ("No retailer reports reply latency as a top-three cost",)
    assert isinstance(revision.falsifiers, tuple)


def test_confirmation_metadata_is_recorded_on_the_revision():
    revision = _revision()
    assert revision.confirmed_by == "requester@example.com"
    assert revision.confirmed_at.tzinfo is not None
    assert revision.revision_number == 1


def test_a_revision_confirms_without_a_requester_identity_being_optional():
    with pytest.raises(IncompleteMarketBriefError) as excinfo:
        MarketBriefRevision(confirmed_by="  ", **COMPLETE_PAYLOAD)
    assert excinfo.value.missing_fields == ["confirmed_by"]


def test_the_workspace_store_offers_no_way_to_persist_a_draft():
    """There is no draft operation, so an abandoned framing cannot leave a record behind.

    This is a structural check rather than a behavioural one on purpose. The guarantee the
    specification makes is about what fn-ignis is unable to store, and an absent operation is
    the only form of that guarantee a later caller cannot work around.
    """
    from ignis.application.ports.research_workspace_port import IResearchWorkspaceStore

    operations = {name for name in dir(IResearchWorkspaceStore) if not name.startswith("_")}
    forbidden = [
        name
        for name in operations
        if any(word in name for word in ("draft", "transcript", "question", "answer"))
    ]
    assert forbidden == []
    assert "save_brief_revision" in operations


def test_an_edit_before_confirmation_is_just_a_different_payload():
    """Editing happens in the host Agent's context, so the domain sees only the final answer."""
    edited = _revision(hypothesis="VN retailers will pay only when latency costs them a sale")
    assert edited.hypothesis.endswith("costs them a sale")
    assert edited.revision_number == 1
