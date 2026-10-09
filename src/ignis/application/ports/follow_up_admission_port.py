"""Private host authority providers; unavailable providers fail closed without acquiring sessions."""

from dataclasses import dataclass
from uuid import UUID
from ignis.domain.follow_up_admission import OperationalGap, ParentBudget, AssignmentBudget, digest
from ignis.domain.research_work import _uuid, _integer, _text


from contextlib import AbstractAsyncContextManager, AbstractContextManager
from typing import Protocol

from ignis.domain.follow_up_admission import CapabilityProof, WorkAuthority


class FollowUpCapabilityLease(Protocol):
    proof: CapabilityProof

    def guard(self) -> AbstractContextManager:
        """Hold thread-safe policy/capability and operational stop/cancel generations until commit."""
        ...

    def is_current(self) -> bool:
        """Check held process, plan, source capability and operational stop/cancel generations."""
        ...


class FollowUpAdmissionVerifier(Protocol):
    def verify_owner(self, reference: str, content_digest: str) -> bool:
        """Validate an existing explicit confirmation for this exact content, never issue a grant."""
        ...

    def hold_current(self, request: WorkAuthority) -> AbstractAsyncContextManager[FollowUpCapabilityLease]:
        """Validate exact plugin ID/platform pairs against the current checked plan and registry.

        Hold their revision and capability generation through commit. Inspect existing
        policy/capability registries only; never initialize authentication or probe.
        """
        ...


@dataclass(frozen=True, slots=True, kw_only=True)
class FollowUpFactCommand:
    """Private fact recording CAS/retry context; trusted host identity is not permission."""

    mission_id: UUID
    record: OperationalGap | ParentBudget | AssignmentBudget | WorkAuthority
    expected_revision: int
    idempotency_key: str
    host_authorized: bool

    def __post_init__(self):
        _uuid(self.mission_id)
        _integer(self.expected_revision)
        _text(self.idempotency_key, maximum=256)
        if (
            type(self.record) not in {OperationalGap, ParentBudget, AssignmentBudget, WorkAuthority}
            or type(self.host_authorized) is not bool
        ):
            raise ValueError("Invalid private fact command.")

    @property
    def fingerprint(self):
        return digest(self)


class AsyncFollowUpCapabilityLease(FollowUpCapabilityLease, Protocol):
    """Optional PostgreSQL shared generation reservation; absent capability fails closed."""

    def async_guard(self) -> AbstractAsyncContextManager:
        """Atomically verify generations and register a shared admission token.

        Policy, capability, checked plan/platform and operational stop/cancel publishers
        share authoritative token state across threads/coroutines and wait for every
        token to settle. Release only after physical commit or completed rollback.
        No blocking thread lock spans await; providers acquire no DB/auth locks.
        """
        ...
