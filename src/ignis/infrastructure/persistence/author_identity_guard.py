"""The repositories' last line against storing who said something (Spec 015, T009).

The mission pass applies the identity policy before anything is written. Both repositories call
these checks as well, inside the write, so a caller that skipped the policy fails instead of
leaking: the batch is refused and its transaction rolls back. The checks and the author facts are
shared here because the two backends must refuse exactly the same things.
"""

from __future__ import annotations

from typing import Iterable, Optional, Tuple

from ignis.domain.author_identity import (
    AuthorAssignment,
    AuthorState,
    author_identity_violation,
    has_handle_segment,
)
from ignis.domain.entities import TrendSignal
from ignis.domain.exceptions import RepositoryException
from ignis.domain.source_identity import KIND_URL, SourceIdentity

_URL_PREFIX = f"{KIND_URL}:"


def refuse_author_identity(signals: Iterable[TrendSignal]) -> None:
    """Refuse the whole batch when any signal still carries author identity.

    Checked before the first row is written, so a refusal never leaves part of a batch behind.
    """
    for signal in signals:
        violation = author_identity_violation(signal.metadata, signal.source_url)
        if violation is not None:
            raise RepositoryException(f"Refused to store author identity: {violation}.")


def refuse_identity_bearing_key(identity: SourceIdentity) -> None:
    """Refuse a source key derived from a link that names an account."""
    if identity.external_id.startswith(_URL_PREFIX) and has_handle_segment(
        identity.external_id[len(_URL_PREFIX):]
    ):
        raise RepositoryException("Refused to store author identity: a source key that names an account.")


def author_evidence_values(signal: TrendSignal) -> Tuple[str, Optional[str], Optional[str]]:
    """(author_state, author_marker, declared_account_id) for the signal's mission_evidence row.

    A signal the policy did not classify carries no author reference the store could see -- the
    guard has already refused any that did -- so it is recorded as UNKNOWN, never merged with
    another voice. NULL stays reserved for rows written before migration 031.
    """
    assignment = signal.author_assignment or AuthorAssignment(AuthorState.UNKNOWN)
    declared = str(assignment.declared_account_id) if assignment.declared_account_id else None
    return assignment.state.value, assignment.marker, declared
