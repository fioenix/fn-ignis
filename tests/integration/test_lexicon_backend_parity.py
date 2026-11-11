"""Spec 024: explicit registration replaces system ownership on both stores."""

import pytest


@pytest.mark.asyncio
async def test_reregistering_system_term_replaces_owner_and_category(repository_case):
    repository = repository_case.repository
    domain, term = "synthetic_024", "synthetic term"
    assert await repository.register_lexicon_terms(
        domain, [term], category="system_category", created_by="system",
    ) == 1
    before = await repository.get_domain_lexicons(domain)
    assert [(row["term"], row["category"], row["created_by"]) for row in before] == [
        (term, "system_category", "system"),
    ]

    assert await repository.register_lexicon_terms(
        domain, [term], category="operator_category", created_by="operator",
    ) == 1

    rows = await repository.get_domain_lexicons(domain)
    assert [(row["term"], row["category"], row["created_by"]) for row in rows] == [
        (term, "operator_category", "operator"),
    ]
