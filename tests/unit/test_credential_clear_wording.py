"""What the clear tools tell an operator they did.

Clearing local storage and revoking a token at the provider are two operations. This release
implements the first. Saying "revoked" merges them, and an operator who reads it has no reason to
go to Meta's security settings -- so a token that leaked stays valid while they believe it does
not. That is the whole harm: the wording decides whether a second, necessary action happens.

These read the live tool objects and handler output rather than the source text, so renaming a
constant cannot make them pass while the user-visible string still says revoked.
"""

import asyncio
import json
import re
from unittest.mock import AsyncMock

import pytest

from ignis.interfaces.mcp import server as mcp_server

# "Revoke"/"revoked" as a claim about what this tool just did. An instruction telling the operator
# to revoke access themselves at the provider is the correct advice and must stay allowed, so the
# checks below look at the tool's own claim rather than banning the word everywhere.
REVOCATION_CLAIM = re.compile(r"\brevoke[ds]?\b", re.IGNORECASE)

# Saying "does not revoke the token at Meta" is the correction, not the defect, and it is worth
# more to an agent reading the tool than silence would be. Only an affirmative claim is a problem,
# so a negation or an instruction pointing at the provider clears the match.
CLAIM_IS_DENIED = re.compile(
    r"\b(not|never|no|without|cannot)\b[^.]{0,40}$"
    r"|\b(remove|revoke)\b[^.]{0,60}\b(in|at|through)\b[^.]{0,40}(Meta|provider|settings)",
    re.IGNORECASE,
)


def _claims_revocation(text: str) -> bool:
    """True only where revocation is asserted as something this tool did."""
    for match in REVOCATION_CLAIM.finditer(text):
        before = text[max(0, match.start() - 60): match.start()]
        after = text[match.start(): match.start() + 120]
        if CLAIM_IS_DENIED.search(before) or CLAIM_IS_DENIED.search(after):
            continue
        return True
    return False

CLEAR_TOOLS = ("clear_threads_auth", "clear_instagram_auth", "clear_platform_auth")


def _tool_descriptions() -> dict:
    tools = asyncio.run(mcp_server.mcp._list_tools())
    return {
        getattr(tool, "name", None): (getattr(tool, "description", "") or "")
        for tool in tools
    }


@pytest.mark.parametrize("tool_name", CLEAR_TOOLS)
def test_clear_tool_description_does_not_claim_remote_revocation(tool_name):
    descriptions = _tool_descriptions()
    assert tool_name in descriptions, f"{tool_name} is not registered"
    description = descriptions[tool_name]

    assert not _claims_revocation(description), (
        f"The {tool_name} description claims revocation: {description!r}. The runtime sends no "
        "revocation request to the provider; it deletes the locally stored encrypted credential."
    )
    assert re.search(r"(?i)(delete|clear|remove)", description), (
        f"The {tool_name} description does not say what it actually does: {description!r}"
    )


@pytest.mark.parametrize(
    "handler_name, manager_key, browser_key",
    [
        ("handle_clear_threads_auth", "threads_auth_manager", "threads_browser_auth_manager"),
        ("handle_clear_instagram_auth", "instagram_auth_manager", "instagram_browser_auth_manager"),
    ],
)
def test_clear_handler_reports_local_deletion_not_revocation(
    monkeypatch, handler_name, manager_key, browser_key
):
    auth_manager = AsyncMock()
    auth_manager.clear_auth = AsyncMock(return_value=True)
    browser_manager = AsyncMock()
    browser_manager.clear_auth = AsyncMock(return_value=True)

    monkeypatch.setattr(
        mcp_server,
        "get_components",
        lambda: {manager_key: auth_manager, browser_key: browser_manager},
    )

    payload = json.loads(asyncio.run(getattr(mcp_server, handler_name)()))
    message = payload["message"]

    assert payload["cleared"] is True
    assert not _claims_revocation(message), (
        f"{handler_name} tells the operator the credential was revoked: {message!r}. Nothing was "
        "sent to the provider, so the token is still valid there."
    )
    assert re.search(r"(?i)(delete|cleared|removed)", message), (
        f"{handler_name} does not state that local storage was cleared: {message!r}"
    )
    assert re.search(r"(?i)(local|stored)", message), (
        f"{handler_name} does not scope its claim to local storage: {message!r}"
    )
