"""The research workspace boundary and the two analytical surfaces that live inside it.

A research is a durable thing; the chat that started it is not. This module holds the identity
of that durable thing -- the workspace, the surface a mission analyses through, and the Market
Brief revision that authorizes a Market mission to run at all -- so that none of it depends on
which Agent host happened to open the conversation.

Two rules are enforced here rather than in a renderer, because a rule that only a renderer knows
is a rule the next caller will get wrong:

- an ``ATTENTION`` mission never carries an Opportunity Index, and
- a ``MARKET`` mission never runs without all seven requester-confirmed Brief fields.
"""

import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple
from uuid import UUID, uuid4

from ignis.domain.exceptions import IgnisDomainException
from ignis.domain.harness_models import ChannelHealthStatus

# Bumped when a workspace on disk can no longer be read by this build. A workspace whose manifest
# names a higher version is reported INCOMPATIBLE rather than opened and partially understood.
WORKSPACE_FORMAT_VERSION = 1

# The child folder every research lives under, relative to the host workspace root.
RESEARCH_ROOT_SEGMENTS = (".ignis", "research")
MANIFEST_FILENAME = "workspace.json"
JOURNAL_DIRNAME = "journals"

# Names the layout itself uses. A research called "journals" would put its manifest and its run
# journals in the same place.
RESERVED_SLUGS = frozenset({"ignis", "research", "journals", "artifacts", "workspace"})

MAX_SLUG_LENGTH = 64


class ResearchSurface(str, Enum):
    """What question a mission is answering."""

    ATTENTION = "ATTENTION"   # What is gaining attention? No hypothesis required, no market claim.
    MARKET = "MARKET"         # Is this a market opportunity? Requires a confirmed Market Brief.


class WorkspaceStatus(str, Enum):
    READY = "READY"                  # Manifest present and readable by this build
    INCOMPATIBLE = "INCOMPATIBLE"    # Manifest present but written by a format this build cannot read


class EvidenceRole(str, Enum):
    """Why an observation appears under a mission."""

    MARKET_EVIDENCE = "MARKET_EVIDENCE"      # Collected for, and evaluated against, this Brief
    ATTENTION_CONTEXT = "ATTENTION_CONTEXT"  # Carried over as lineage; never counted as support


class EvidenceDirection(str, Enum):
    """How evidence affects a named hypothesis inside an analysis frame."""

    SUPPORT = "SUPPORT"
    CONTRADICTION = "CONTRADICTION"
    CONTEXT = "CONTEXT"


class MissionOutputType(str, Enum):
    """The deliverable one explicit mission is allowed to produce."""

    COLLECTION_FRAME = "COLLECTION_FRAME"
    ATTENTION_REPORT = "ATTENTION_REPORT"
    MARKET_ANALYSIS = "MARKET_ANALYSIS"
    STRATEGIC_ARTIFACT = "STRATEGIC_ARTIFACT"


class ClaimType(str, Enum):
    OBSERVATION = "OBSERVATION"
    MEASUREMENT = "MEASUREMENT"
    INFERENCE = "INFERENCE"
    ASSUMPTION = "ASSUMPTION"
    RECOMMENDATION = "RECOMMENDATION"
    UNKNOWN = "UNKNOWN"


class ClaimStatus(str, Enum):
    PERMITTED = "PERMITTED"
    WITHHELD = "WITHHELD"
    SUPERSEDED = "SUPERSEDED"


class InvalidWorkspaceSlugError(IgnisDomainException):
    """The requested research name cannot become a child-folder name."""


class WorkspaceScopeMismatchError(IgnisDomainException):
    """A record was addressed through a workspace that does not own it.

    Returned as an error rather than as an empty result: an empty result reads as "this research
    has no such mission", which is a different and much quieter untruth.
    """


class InvalidWorkspaceManifestError(IgnisDomainException):
    """The manifest exists but does not describe a research workspace this build can open."""


class WorkspaceAdoptionRequiredError(IgnisDomainException):
    """A non-empty folder without a valid manifest needs an explicit adoption confirmation."""


class IncompleteMarketBriefError(IgnisDomainException):
    """A Market Brief was submitted without every field that authorizes execution."""

    def __init__(self, missing_fields: Sequence[str]):
        self.missing_fields: List[str] = list(missing_fields)
        super().__init__(
            "Market execution is not authorized until the requester confirms every required "
            f"Brief field. Missing: {', '.join(self.missing_fields)}."
        )


class SurfaceViolationError(IgnisDomainException):
    """An operation was asked for on a surface that does not offer it."""


class MissionWriterConflictError(IgnisDomainException):
    """A mission already has an active writer, so this run has nothing of its own to write into."""


class InvalidMissionLineageError(IgnisDomainException):
    """The selected Attention origin does not describe a handoff this workspace can make.

    Raised rather than silently dropped. Lineage that cannot be resolved is a requester pointing
    at a topic nobody can find again, and recording the Market mission without it would leave a
    hypothesis whose origin is unrecoverable.
    """


class InvalidMissionManifestError(IgnisDomainException):
    """A mission authority boundary is incomplete, contradictory, or credential-shaped."""


class InvalidMissionClaimError(IgnisDomainException):
    """A claim or evidence binding cannot be traced to one valid evidence frame."""


@dataclass(frozen=True)
class AuthorityBoundary:
    """Boolean authority only; credentials remain in their dedicated secure stores."""

    public_http: bool
    official_api: bool
    browser_session: bool
    paid_quota: bool

    def __post_init__(self) -> None:
        for name in ("public_http", "official_api", "browser_session", "paid_quota"):
            if type(getattr(self, name)) is not bool:
                raise InvalidMissionManifestError(f"authority_boundary.{name} must be boolean.")

    def to_payload(self) -> Dict[str, bool]:
        return {
            "public_http": self.public_http,
            "official_api": self.official_api,
            "browser_session": self.browser_session,
            "paid_quota": self.paid_quota,
        }


@dataclass(frozen=True)
class MissionManifest:
    """Immutable outcome, resource, authority, and stop boundary for one assigned task."""

    outcome: str
    decision_context: Optional[str]
    required_channels: Tuple[str, ...]
    optional_channels: Tuple[str, ...]
    authority_boundary: AuthorityBoundary
    quota_budget: Mapping[str, int]
    output_type: MissionOutputType
    stop_conditions: Tuple[str, ...]
    analysis_policy: str
    retention_policy: str
    created_by: str
    confirmed_at: datetime
    mission_id: Optional[UUID] = None

    def __post_init__(self) -> None:
        required = _clean_unique_strings(self.required_channels, "required_channels")
        optional = _clean_unique_strings(self.optional_channels, "optional_channels", allow_empty=True)
        stops = _clean_unique_strings(self.stop_conditions, "stop_conditions")
        object.__setattr__(self, "required_channels", required)
        object.__setattr__(self, "optional_channels", optional)
        object.__setattr__(self, "stop_conditions", stops)
        if required and set(required) & set(optional):
            raise InvalidMissionManifestError(
                "required_channels and optional_channels must be disjoint."
            )
        if not isinstance(self.authority_boundary, AuthorityBoundary):
            raise InvalidMissionManifestError("authority_boundary must be an AuthorityBoundary.")
        for name in ("outcome", "analysis_policy", "retention_policy", "created_by"):
            if _is_blank(getattr(self, name)):
                raise InvalidMissionManifestError(f"{name} is required.")
        for name in ("analysis_policy", "created_by"):
            if not isinstance(getattr(self, name), str) or len(getattr(self, name)) > 128:
                raise InvalidMissionManifestError(
                    f"{name} must be a string of at most 128 characters."
                )
        output_type = _manifest_enum(MissionOutputType, self.output_type, "output_type")
        object.__setattr__(self, "output_type", output_type)
        if output_type in (MissionOutputType.MARKET_ANALYSIS, MissionOutputType.STRATEGIC_ARTIFACT):
            if _is_blank(self.decision_context):
                raise InvalidMissionManifestError(
                    "decision_context is required for Market outputs."
                )
        budget = dict(self.quota_budget or {})
        for name, value in budget.items():
            if not isinstance(name, str) or not name.strip():
                raise InvalidMissionManifestError("quota_budget keys must be non-empty strings.")
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise InvalidMissionManifestError(
                    f"quota_budget.{name} must be a non-negative integer."
                )
        object.__setattr__(self, "quota_budget", MappingProxyType(budget))
        if self.mission_id is not None:
            object.__setattr__(self, "mission_id", _claim_uuid(self.mission_id, "mission_id"))
        if not isinstance(self.confirmed_at, datetime) or self.confirmed_at.tzinfo is None:
            raise InvalidMissionManifestError("confirmed_at must be a timezone-aware datetime.")

    def to_payload(self) -> Dict[str, Any]:
        return {
            "mission_id": str(self.mission_id) if self.mission_id else None,
            "outcome": self.outcome.strip(),
            "decision_context": (
                self.decision_context.strip() if isinstance(self.decision_context, str) else None
            ),
            "required_channels": list(self.required_channels),
            "optional_channels": list(self.optional_channels),
            "authority_boundary": self.authority_boundary.to_payload(),
            "quota_budget": dict(self.quota_budget),
            "output_type": self.output_type.value,
            "stop_conditions": list(self.stop_conditions),
            "analysis_policy": self.analysis_policy.strip(),
            "retention_policy": self.retention_policy.strip(),
            "created_by": self.created_by.strip(),
            "confirmed_at": self.confirmed_at.astimezone(timezone.utc).isoformat(),
        }

    @property
    def manifest_digest(self) -> str:
        return _digest(self.to_payload())


def _clean_unique_strings(
    values: Sequence[Any], field_name: str, *, allow_empty: bool = False
) -> Tuple[str, ...]:
    if isinstance(values, str):
        values = (values,)
    cleaned = tuple(str(value).strip() for value in (values or ()) if not _is_blank(value))
    if not cleaned and not allow_empty:
        raise InvalidMissionManifestError(f"{field_name} must contain at least one value.")
    if len(cleaned) != len(set(cleaned)):
        raise InvalidMissionManifestError(f"{field_name} must not contain duplicates.")
    return cleaned


def _manifest_enum(enum_type, value: Any, field_name: str):
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(str(value).strip().upper())
    except ValueError as exc:
        raise InvalidMissionManifestError(f"{field_name} is invalid: {value!r}.") from exc


# ---------------------------------------------------------------------------
# Surface
# ---------------------------------------------------------------------------

def resolve_surface(value: Any) -> Optional[ResearchSurface]:
    """Read a stored surface back, or None when the mission never recorded one.

    None is a real answer here. Missions created before this feature carry no surface, and
    inventing MARKET for them would gate every one of them on a Brief that was never collected.
    """
    if value is None:
        return None
    if isinstance(value, ResearchSurface):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return ResearchSurface(text.upper())
    except ValueError as exc:
        raise SurfaceViolationError(
            f"'{value}' is not a research surface. Expected one of: "
            f"{', '.join(s.value for s in ResearchSurface)}."
        ) from exc


def opportunity_index_is_allowed(surface: Any) -> bool:
    """Whether a mission on this surface may carry an Opportunity Index.

    ATTENTION may not: it measures what is being looked at, and an index presented beside that
    would read as a commercial verdict the evidence does not support. A mission with no recorded
    surface keeps the behaviour it already had.
    """
    return resolve_surface(surface) is not ResearchSurface.ATTENTION


# ---------------------------------------------------------------------------
# Slug and workspace identity
# ---------------------------------------------------------------------------

_SLUG_ALLOWED = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_SLUG_SEPARATORS = re.compile(r"[^a-zA-Z0-9]+")


def slugify_research_name(name: str) -> str:
    """Turn a research name into the child-folder name it is proposed under.

    ASCII only, and deliberately so: the slug is a path segment that has to survive being typed
    into a shell, copied between hosts and compared for equality on a case-insensitive
    filesystem. The research keeps its full name in the manifest.
    """
    if not isinstance(name, str) or not name.strip():
        raise InvalidWorkspaceSlugError("A research needs a name before it can be given a folder.")
    ascii_only = name.encode("ascii", "ignore").decode("ascii")
    slug = _SLUG_SEPARATORS.sub("-", ascii_only).strip("-").lower()
    slug = slug[:MAX_SLUG_LENGTH].strip("-")
    if not slug:
        raise InvalidWorkspaceSlugError(
            f"'{name}' contains no character that can become a folder name. "
            "Supply a name using latin letters or digits."
        )
    return validate_slug(slug)


def validate_slug(slug: str) -> str:
    """Refuse a slug that would escape the research root or collide with the layout itself."""
    if not isinstance(slug, str) or not slug:
        raise InvalidWorkspaceSlugError("A research slug cannot be empty.")
    if len(slug) > MAX_SLUG_LENGTH:
        raise InvalidWorkspaceSlugError(
            f"'{slug}' is longer than the {MAX_SLUG_LENGTH}-character limit for a research slug."
        )
    if not _SLUG_ALLOWED.match(slug):
        raise InvalidWorkspaceSlugError(
            f"'{slug}' is not a valid research slug. Use lowercase letters, digits and single "
            "hyphens, for example 'ai-customer-service'."
        )
    if slug in RESERVED_SLUGS:
        raise InvalidWorkspaceSlugError(
            f"'{slug}' is reserved by the workspace layout and cannot name a research."
        )
    return slug


def research_root(host_workspace: Path) -> Path:
    """The directory every research of one host workspace is proposed under."""
    return Path(host_workspace).joinpath(*RESEARCH_ROOT_SEGMENTS)


@dataclass(frozen=True)
class ResearchWorkspace:
    """One research boundary: an identity, a folder, and the format that folder was written in."""

    slug: str
    root_path: Path
    workspace_id: UUID = field(default_factory=uuid4)
    name: Optional[str] = None
    format_version: int = WORKSPACE_FORMAT_VERSION
    status: WorkspaceStatus = WorkspaceStatus.READY
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        validate_slug(self.slug)
        object.__setattr__(self, "root_path", Path(self.root_path))

    @property
    def manifest_path(self) -> Path:
        return self.root_path / MANIFEST_FILENAME

    @property
    def journal_dir(self) -> Path:
        return self.root_path / JOURNAL_DIRNAME

    def to_manifest(self) -> Dict[str, Any]:
        return {
            "workspace_id": str(self.workspace_id),
            "slug": self.slug,
            "name": self.name or self.slug,
            "format_version": self.format_version,
            "created_at": self.created_at.isoformat(),
        }

    def manifest_json(self) -> str:
        return json.dumps(self.to_manifest(), indent=2, sort_keys=True) + "\n"

    @classmethod
    def from_manifest(cls, payload: Mapping[str, Any], root_path: Path) -> "ResearchWorkspace":
        """Read a manifest back, marking it INCOMPATIBLE rather than half-understanding it."""
        try:
            workspace_id = UUID(str(payload["workspace_id"]))
            slug = str(payload["slug"])
            format_version = int(payload["format_version"])
        except (KeyError, ValueError, TypeError) as exc:
            raise InvalidWorkspaceManifestError(
                f"{Path(root_path) / MANIFEST_FILENAME} is not a readable workspace manifest."
            ) from exc

        raw_created = payload.get("created_at")
        try:
            created_at = datetime.fromisoformat(str(raw_created))
        except (TypeError, ValueError):
            created_at = datetime.now(timezone.utc)

        return cls(
            slug=slug,
            root_path=Path(root_path),
            workspace_id=workspace_id,
            name=payload.get("name") or slug,
            format_version=format_version,
            status=(
                WorkspaceStatus.READY
                if format_version <= WORKSPACE_FORMAT_VERSION
                else WorkspaceStatus.INCOMPATIBLE
            ),
            created_at=created_at,
        )


# ---------------------------------------------------------------------------
# Mission lineage
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class MissionLineage:
    """Where a Market mission came from: an Attention result, an earlier Brief, or both.

    Lineage is context. It records which Attention mission and cluster were selected for
    investigation, and which Market mission's confirmed Brief was changed to produce this one.
    It never makes the earlier evidence into support for the new hypothesis.

    `revises_mission_id` is the one canonical name for the Market-to-Market relation, and it is
    held by the newer mission: the revised one is immutable from the moment its Brief was
    confirmed, so a pointer written onto it afterwards would be the later work editing history.
    """

    parent_attention_mission_id: Optional[UUID] = None
    parent_cluster_id: Optional[UUID] = None
    revises_mission_id: Optional[UUID] = None

    @property
    def is_empty(self) -> bool:
        return (
            self.parent_attention_mission_id is None
            and self.parent_cluster_id is None
            and self.revises_mission_id is None
        )

    @property
    def attention_origin(self) -> "MissionLineage":
        """Only the Attention half, for comparing two missions' origins."""
        return MissionLineage(
            parent_attention_mission_id=self.parent_attention_mission_id,
            parent_cluster_id=self.parent_cluster_id,
        )

    def to_payload(self) -> Dict[str, Any]:
        return {
            "parent_attention_mission_id": (
                str(self.parent_attention_mission_id)
                if self.parent_attention_mission_id else None
            ),
            "parent_cluster_id": (
                str(self.parent_cluster_id) if self.parent_cluster_id else None
            ),
            "revises_mission_id": (
                str(self.revises_mission_id) if self.revises_mission_id else None
            ),
        }

    @classmethod
    def of_mission(cls, mission: Any) -> "MissionLineage":
        """Read the lineage a stored mission carries."""
        return cls(
            parent_attention_mission_id=getattr(mission, "parent_attention_mission_id", None),
            parent_cluster_id=getattr(mission, "parent_cluster_id", None),
            revises_mission_id=getattr(mission, "revises_mission_id", None),
        )


# ---------------------------------------------------------------------------
# Market Brief
# ---------------------------------------------------------------------------

REQUIRED_BRIEF_FIELDS: Tuple[str, ...] = (
    "decision",
    "target_user",
    "problem",
    "geo",
    "timeframe",
    "hypothesis",
    "falsifiers",
)


def _is_blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def missing_brief_fields(payload: Mapping[str, Any]) -> List[str]:
    """Name every required field the requester has not actually answered.

    Used by the execution gate as well as by construction, so that a caller can report what is
    still outstanding without having to provoke an exception to find out.
    """
    missing: List[str] = []
    for name in REQUIRED_BRIEF_FIELDS:
        value = payload.get(name)
        if name == "falsifiers":
            entries = [f for f in (value or []) if not _is_blank(f)]
            if not entries:
                missing.append(name)
            continue
        if _is_blank(value):
            missing.append(name)
    return missing


@dataclass(frozen=True)
class MarketBriefRevision:
    """The immutable decision frame that authorizes one Market mission.

    Frozen on purpose. Evidence is collected against a specific hypothesis, so editing the
    hypothesis afterwards would silently re-label evidence that was gathered to answer a
    different question. A change creates a new revision instead.
    """

    decision: str
    target_user: str
    problem: str
    geo: str
    timeframe: str
    hypothesis: str
    falsifiers: Tuple[str, ...]
    confirmed_by: str
    alternative_hypotheses: Optional[Tuple[str, ...]] = None
    null_hypothesis: Optional[str] = None
    kill_criteria: Optional[Tuple[str, ...]] = None
    revision_rule: Optional[str] = None
    brief_revision_id: UUID = field(default_factory=uuid4)
    workspace_id: Optional[UUID] = None
    mission_id: Optional[UUID] = None
    revision_number: int = 1
    confirmed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        falsifiers = self.falsifiers
        if isinstance(falsifiers, str):
            falsifiers = [falsifiers]
        cleaned = tuple(f.strip() for f in (falsifiers or []) if not _is_blank(f))
        object.__setattr__(self, "falsifiers", cleaned)

        extension_values = (
            self.alternative_hypotheses,
            self.null_hypothesis,
            self.kill_criteria,
            self.revision_rule,
        )
        uses_evidence_contract = any(value is not None for value in extension_values)
        alternatives: Optional[Tuple[str, ...]] = None
        kill_criteria: Optional[Tuple[str, ...]] = None
        if uses_evidence_contract:
            alternatives = _clean_brief_entries(self.alternative_hypotheses)
            kill_criteria = _clean_brief_entries(self.kill_criteria)
            object.__setattr__(self, "alternative_hypotheses", alternatives)
            object.__setattr__(self, "kill_criteria", kill_criteria)

        missing = missing_brief_fields(
            {
                "decision": self.decision,
                "target_user": self.target_user,
                "problem": self.problem,
                "geo": self.geo,
                "timeframe": self.timeframe,
                "hypothesis": self.hypothesis,
                "falsifiers": cleaned,
            }
        )
        # The requester identity is what makes the revision a confirmation rather than a draft,
        # so it is refused on the same path as an unanswered field.
        if _is_blank(self.confirmed_by):
            missing.append("confirmed_by")
        if uses_evidence_contract:
            if alternatives is None or len(alternatives) < 2:
                missing.append("alternative_hypotheses")
            if _is_blank(self.null_hypothesis):
                missing.append("null_hypothesis")
            if not kill_criteria:
                missing.append("kill_criteria")
            if _is_blank(self.revision_rule):
                missing.append("revision_rule")
        if missing:
            raise IncompleteMarketBriefError(missing)

    @property
    def core_hypothesis(self) -> str:
        """Public semantic name while the compatible storage column remains `hypothesis`."""
        return self.hypothesis

    @property
    def evidence_contract_version(self) -> int:
        return 2 if self.alternative_hypotheses is not None else 1

    def to_payload(self) -> Dict[str, Any]:
        return {
            "brief_revision_id": str(self.brief_revision_id),
            "workspace_id": str(self.workspace_id) if self.workspace_id else None,
            "mission_id": str(self.mission_id) if self.mission_id else None,
            "revision_number": self.revision_number,
            "decision": self.decision,
            "target_user": self.target_user,
            "problem": self.problem,
            "geo": self.geo,
            "timeframe": self.timeframe,
            "hypothesis": self.hypothesis,
            "falsifiers": list(self.falsifiers),
            "alternative_hypotheses": (
                list(self.alternative_hypotheses)
                if self.alternative_hypotheses is not None
                else None
            ),
            "null_hypothesis": self.null_hypothesis,
            "kill_criteria": list(self.kill_criteria) if self.kill_criteria is not None else None,
            "revision_rule": self.revision_rule,
            "evidence_contract_version": self.evidence_contract_version,
            "confirmed_by": self.confirmed_by,
            "confirmed_at": self.confirmed_at.isoformat(),
        }


def _clean_brief_entries(values: Optional[Sequence[Any]]) -> Optional[Tuple[str, ...]]:
    if values is None:
        return None
    if isinstance(values, str):
        values = (values,)
    cleaned = tuple(str(value).strip() for value in values if not _is_blank(value))
    if len(cleaned) != len(set(cleaned)):
        raise IncompleteMarketBriefError(["alternative_hypotheses"])
    return cleaned


# ---------------------------------------------------------------------------
# Evidence qualification
# ---------------------------------------------------------------------------
#
# A citation that reaches a canonical observation is traceable; that does not make it support.
# The host Agent judges whether each observation addresses the mission's question and submits a
# typed judgment. These records keep that judgment bounded and self-consistent, and keep it apart
# from the immutable observation: one observation can support one question and be noise to another.


class QualificationRelation(str, Enum):
    """How one observation relates to the mission's question."""

    QUALIFIED_SUPPORT = "QUALIFIED_SUPPORT"      # Directly addresses the declared scope or Brief
    QUALIFIED_CONTRADICTION = "QUALIFIED_CONTRADICTION"  # Weakens the target or supports a rival
    CONTEXT_ONLY = "CONTEXT_ONLY"                # Related, visible, never counted as support
    EXCLUDED_IRRELEVANT = "EXCLUDED_IRRELEVANT"  # Does not address the question at all
    UNASSESSED = "UNASSESSED"                    # No judgment was obtained


class EvidencePurpose(str, Enum):
    """What a qualified observation can measure."""

    DEMAND = "DEMAND"
    SUPPLY = "SUPPLY"
    VOC = "VOC"
    CONTEXT = "CONTEXT"


class QualificationReason(str, Enum):
    """The bounded explanation for a judgment. Free text is refused on purpose."""

    DIRECT_TO_FRAME = "DIRECT_TO_FRAME"
    ADJACENT_ONLY = "ADJACENT_ONLY"
    KEYWORD_ONLY = "KEYWORD_ONLY"
    WRONG_AUDIENCE_OR_PROBLEM = "WRONG_AUDIENCE_OR_PROBLEM"
    FICTION_NEWS_OR_ENTERTAINMENT = "FICTION_NEWS_OR_ENTERTAINMENT"
    INSUFFICIENT_CONTENT = "INSUFFICIENT_CONTENT"
    EVALUATOR_UNAVAILABLE = "EVALUATOR_UNAVAILABLE"


class QualificationStatus(str, Enum):
    """Where a mission's evidence stands between raw collection and a permitted conclusion."""

    QUALIFICATION_REQUIRED = "QUALIFICATION_REQUIRED"  # Current evidence still lacks a judgment
    READY = "READY"                                    # Assessed, and a conclusion is permitted
    INSUFFICIENT_RELEVANT_EVIDENCE = "INSUFFICIENT_RELEVANT_EVIDENCE"
    UNAVAILABLE = "UNAVAILABLE"                        # A judgment could not be obtained
    NOT_APPLICABLE = "NOT_APPLICABLE"                  # No declared surface; legacy behaviour


class EvidenceSufficiency(str, Enum):
    """Whether one Market topic meets the minimum evidence for a demand-versus-supply verdict."""

    SUFFICIENT_POSITIVE_SUPPLY = "SUFFICIENT_POSITIVE_SUPPLY"
    SUFFICIENT_ZERO_SUPPLY = "SUFFICIENT_ZERO_SUPPLY"
    MISSING_DEMAND = "MISSING_DEMAND"
    MISSING_SUPPLY = "MISSING_SUPPLY"
    QUALIFICATION_REQUIRED = "QUALIFICATION_REQUIRED"
    QUALIFIER_UNAVAILABLE = "QUALIFIER_UNAVAILABLE"

    @property
    def permits_verdict(self) -> bool:
        return self in (
            EvidenceSufficiency.SUFFICIENT_POSITIVE_SUPPLY,
            EvidenceSufficiency.SUFFICIENT_ZERO_SUPPLY,
        )


class HandoffStatus(str, Enum):
    """Whether an Attention result offers anything worth a new Market Brief."""

    QUALIFIED_CANDIDATE_AVAILABLE = "QUALIFIED_CANDIDATE_AVAILABLE"
    NO_QUALIFIED_CANDIDATE = "NO_QUALIFIED_CANDIDATE"
    QUALIFICATION_REQUIRED = "QUALIFICATION_REQUIRED"
    UNAVAILABLE = "UNAVAILABLE"


class InvalidEvidenceQualificationError(IgnisDomainException):
    """A judgment or probe outcome is malformed, contradicts itself, or names foreign evidence."""


class EvidenceQualificationConflictError(IgnisDomainException):
    """A submission disagrees with what is already recorded, or with the current frame.

    Semantic history is not rewritten in place. A different judgment needs a new mission or a new
    Market Brief revision, so the report a reader already saw keeps meaning what it meant.
    """


# The reasons an honest UNASSESSED row can give.
UNASSESSED_REASONS = frozenset(
    {QualificationReason.INSUFFICIENT_CONTENT, QualificationReason.EVALUATOR_UNAVAILABLE}
)

# An evaluator identifier such as "claude-code" or "anthropic/claude-opus-5-5". No whitespace is
# allowed, which keeps a prompt, a transcript or a model's reasoning from being pasted in here.
MAX_EVALUATOR_IDENTIFIER_LENGTH = 128
_EVALUATOR_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+\-]*$")
MAX_FINGERPRINT_LENGTH = 128


def _coerce_enum(enum_type, value: Any, field_name: str):
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(str(value).strip().upper())
    except ValueError as exc:
        raise InvalidEvidenceQualificationError(
            f"'{value}' is not a valid {field_name}. Expected one of: "
            f"{', '.join(member.value for member in enum_type)}."
        ) from exc


def _coerce_uuid(value: Any, field_name: str) -> UUID:
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (TypeError, ValueError) as exc:
        raise InvalidEvidenceQualificationError(f"{field_name} '{value}' is not a UUID.") from exc


def _evaluator_identifier(value: Any, field_name: str, required: bool) -> Optional[str]:
    if value is None and not required:
        return None
    text = value if isinstance(value, str) else ""
    if (
        not text
        or len(text) > MAX_EVALUATOR_IDENTIFIER_LENGTH
        or not _EVALUATOR_IDENTIFIER.match(text)
    ):
        raise InvalidEvidenceQualificationError(
            f"{field_name} must be a bounded identifier of at most "
            f"{MAX_EVALUATOR_IDENTIFIER_LENGTH} characters with no whitespace, such as "
            "'claude-code'. It is metadata, never a prompt, transcript or credential."
        )
    return text


def _fingerprint(value: Any, field_name: str) -> str:
    text = value if isinstance(value, str) else ""
    if not text.strip() or len(text) > MAX_FINGERPRINT_LENGTH:
        raise InvalidEvidenceQualificationError(
            f"{field_name} must be a non-empty digest of at most {MAX_FINGERPRINT_LENGTH} "
            "characters."
        )
    return text


@dataclass(frozen=True)
class EvidenceQualification:
    """One mission's judgment of one observation it holds, against one immutable frame."""

    mission_id: UUID
    observation_id: UUID
    frame_fingerprint: str
    relation: QualificationRelation
    purpose: EvidencePurpose
    confidence: Optional[float]
    reason_code: QualificationReason
    judged_by: str
    brief_revision_id: Optional[UUID] = None
    model: Optional[str] = None
    created_at: Optional[datetime] = None
    hypothesis_target: Optional[str] = None
    evidence_role: Optional[EvidenceDirection] = None
    evidence_contract_version: Optional[int] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "mission_id", _coerce_uuid(self.mission_id, "mission_id"))
        object.__setattr__(
            self, "observation_id", _coerce_uuid(self.observation_id, "observation_id")
        )
        if self.brief_revision_id is not None:
            object.__setattr__(
                self,
                "brief_revision_id",
                _coerce_uuid(self.brief_revision_id, "brief_revision_id"),
            )
        object.__setattr__(
            self, "frame_fingerprint", _fingerprint(self.frame_fingerprint, "frame_fingerprint")
        )
        relation = _coerce_enum(QualificationRelation, self.relation, "relation")
        purpose = _coerce_enum(EvidencePurpose, self.purpose, "purpose")
        reason = _coerce_enum(QualificationReason, self.reason_code, "reason_code")
        object.__setattr__(self, "relation", relation)
        object.__setattr__(self, "purpose", purpose)
        object.__setattr__(self, "reason_code", reason)
        contract_version = self.evidence_contract_version
        if contract_version is None:
            contract_version = (
                2
                if relation is QualificationRelation.QUALIFIED_CONTRADICTION
                or self.evidence_role is not None
                or not _is_blank(self.hypothesis_target)
                else 1
            )
        if isinstance(contract_version, bool) or contract_version not in (1, 2):
            raise InvalidEvidenceQualificationError(
                "evidence_contract_version must be 1 or 2."
            )
        if contract_version == 1 and (
            relation is QualificationRelation.QUALIFIED_CONTRADICTION
            or self.evidence_role is not None
            or not _is_blank(self.hypothesis_target)
        ):
            raise InvalidEvidenceQualificationError(
                "Evidence contract v1 cannot carry contradiction, evidence_role, or "
                "hypothesis_target fields."
            )
        object.__setattr__(self, "evidence_contract_version", contract_version)
        if contract_version == 2 and self.evidence_role is None:
            raise InvalidEvidenceQualificationError(
                "Evidence contract v2 requires an evidence_role."
            )
        if self.evidence_role is not None:
            direction = _coerce_enum(EvidenceDirection, self.evidence_role, "evidence_role")
            object.__setattr__(self, "evidence_role", direction)
            expected = {
                QualificationRelation.QUALIFIED_SUPPORT: EvidenceDirection.SUPPORT,
                QualificationRelation.QUALIFIED_CONTRADICTION: EvidenceDirection.CONTRADICTION,
            }.get(relation)
            if expected is not None and direction is not expected:
                raise InvalidEvidenceQualificationError(
                    f"{relation.value} requires evidence_role {expected.value}."
                )
            if relation in (
                QualificationRelation.QUALIFIED_SUPPORT,
                QualificationRelation.QUALIFIED_CONTRADICTION,
            ) and _is_blank(self.hypothesis_target):
                raise InvalidEvidenceQualificationError(
                    f"{relation.value} requires a hypothesis_target."
                )
        object.__setattr__(
            self, "judged_by", _evaluator_identifier(self.judged_by, "judged_by", required=True)
        )
        object.__setattr__(
            self, "model", _evaluator_identifier(self.model, "model", required=False)
        )

        if relation in (
            QualificationRelation.QUALIFIED_SUPPORT,
            QualificationRelation.QUALIFIED_CONTRADICTION,
        ) and purpose is EvidencePurpose.CONTEXT:
            raise InvalidEvidenceQualificationError(
                f"{relation.value} must name what it measures: DEMAND, SUPPLY or VOC, not CONTEXT."
            )
        if relation is QualificationRelation.CONTEXT_ONLY and purpose is not EvidencePurpose.CONTEXT:
            raise InvalidEvidenceQualificationError(
                "CONTEXT_ONLY evidence measures nothing, so its purpose must be CONTEXT."
            )

        confidence = self.confidence
        if relation is QualificationRelation.UNASSESSED:
            if confidence is not None:
                raise InvalidEvidenceQualificationError(
                    "An UNASSESSED row holds no judgment, so its confidence must be null."
                )
            if reason not in UNASSESSED_REASONS:
                raise InvalidEvidenceQualificationError(
                    "An UNASSESSED row must give the reason INSUFFICIENT_CONTENT or "
                    "EVALUATOR_UNAVAILABLE."
                )
            return
        # bool is an int in Python, and True is not a probability.
        if (
            isinstance(confidence, bool)
            or not isinstance(confidence, (int, float))
            or math.isnan(confidence)
            or not 0.0 <= float(confidence) <= 1.0
        ):
            raise InvalidEvidenceQualificationError(
                "An assessed judgment needs a confidence from 0.0 through 1.0."
            )
        object.__setattr__(self, "confidence", float(confidence))

    @property
    def contributes_to(self) -> Optional[EvidencePurpose]:
        """What this judgment lets the observation measure. Only support measures anything."""
        if self.relation is QualificationRelation.QUALIFIED_SUPPORT:
            return self.purpose
        return None

    def same_judgment(self, other: "EvidenceQualification") -> bool:
        """Whether a replay says exactly what was recorded. The persisted time is not compared."""
        return (
            self.mission_id,
            self.observation_id,
            self.frame_fingerprint,
            self.brief_revision_id,
            self.relation,
            self.purpose,
            self.confidence,
            self.reason_code,
            self.judged_by,
            self.model,
            self.hypothesis_target,
            self.evidence_role,
            self.evidence_contract_version,
        ) == (
            other.mission_id,
            other.observation_id,
            other.frame_fingerprint,
            other.brief_revision_id,
            other.relation,
            other.purpose,
            other.confidence,
            other.reason_code,
            other.judged_by,
            other.model,
            other.hypothesis_target,
            other.evidence_role,
            other.evidence_contract_version,
        )


@dataclass(frozen=True)
class MissionProbeOutcome:
    """What one connector surface did during one workspace run.

    A measured zero is this record with EMPTY_NO_DATA, for the query its fingerprint names. A
    surface that failed, was rate limited or had no session measured nothing, and says so.
    """

    run_id: UUID
    platform: str
    connector_surface: str
    status: ChannelHealthStatus
    signals_collected: int
    query_fingerprint: str
    completed_at: datetime
    # The keywords this surface attested to having queried during the run. A measured zero
    # covers only these: a connector that probes ten keywords never measured the eleventh.
    queried_keywords: Tuple[str, ...] = ()
    # The window the platform attested to filtering by during the run, or None when it applied
    # none. A measured zero holds only for the frame's own window.
    queried_window: Optional[str] = None
    scope_attestation: Optional[Mapping[str, Any]] = None
    note: Optional[str] = None
    collection_plan_digest: Optional[str] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "run_id", _coerce_uuid(self.run_id, "run_id"))
        object.__setattr__(
            self, "queried_keywords", tuple(str(k) for k in (self.queried_keywords or ()))
        )
        status = _coerce_enum(ChannelHealthStatus, self.status, "probe status")
        object.__setattr__(self, "status", status)
        for name in ("platform", "connector_surface"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise InvalidEvidenceQualificationError(f"A probe outcome needs its {name}.")
        object.__setattr__(
            self, "query_fingerprint", _fingerprint(self.query_fingerprint, "query_fingerprint")
        )
        count = self.signals_collected
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise InvalidEvidenceQualificationError(
                "signals_collected must be a non-negative integer."
            )
        if (status is ChannelHealthStatus.HEALTHY) != (count > 0):
            raise InvalidEvidenceQualificationError(
                f"A {status.value} surface cannot report {count} collected signals: HEALTHY means "
                "signals came back, and every other outcome collected none."
            )
        if status is ChannelHealthStatus.EMPTY_NO_DATA and not self.queried_keywords:
            raise InvalidEvidenceQualificationError(
                "An EMPTY_NO_DATA outcome must name the keywords the surface attested to querying; "
                "an empty answer to no known query measured nothing."
            )
        if self.collection_plan_digest is not None:
            object.__setattr__(
                self,
                "collection_plan_digest",
                _fingerprint(self.collection_plan_digest, "collection_plan_digest"),
            )
            if status in (ChannelHealthStatus.HEALTHY, ChannelHealthStatus.EMPTY_NO_DATA):
                if not isinstance(self.scope_attestation, Mapping):
                    raise InvalidEvidenceQualificationError(
                        f"{status.value} requires a scope_attestation."
                    )
            elif _is_blank(self.note):
                raise InvalidEvidenceQualificationError(
                    f"{status.value} requires an operational note."
                )

    @property
    def measures_zero(self) -> bool:
        return self.status is ChannelHealthStatus.EMPTY_NO_DATA

    def measured_zero_for(self, topic: str, geo: Any, timeframe: Any) -> bool:
        """Whether this outcome is a measured zero for `topic` in the given frame.

        True only for an EMPTY_NO_DATA surface that attested querying the topic within exactly
        the frame's window, and whose stored fingerprint is the digest of that recorded query --
        so a keyword the surface never sent, a window it did not filter by (or no window at all),
        or a row describing some other geo or query measures nothing.
        """
        if not self.measures_zero or self.queried_window is None:
            return False
        if self.queried_window != _plain(timeframe):
            return False
        if _normalized_keyword(topic) not in {_normalized_keyword(k) for k in self.queried_keywords}:
            return False
        return self.query_fingerprint == compute_query_fingerprint(
            self.queried_keywords, geo, self.queried_window
        )


def require_complete_channel_outcomes(
    required_channels: Sequence[str],
    optional_channels: Sequence[str],
    outcomes: Sequence[MissionProbeOutcome],
) -> None:
    """Refuse a manifested run unless every declared surface has exactly one outcome."""
    declared = tuple(required_channels) + tuple(optional_channels)
    actual = tuple(outcome.connector_surface for outcome in outcomes)
    if len(actual) != len(set(actual)) or set(actual) != set(declared):
        missing = sorted(set(declared) - set(actual))
        unexpected = sorted(set(actual) - set(declared))
        raise InvalidEvidenceQualificationError(
            "Probe outcomes must cover the manifest-declared channels exactly once; "
            f"missing={missing}, unexpected={unexpected}."
        )
    plan_digests = {outcome.collection_plan_digest for outcome in outcomes}
    if None in plan_digests or len(plan_digests) != 1:
        raise InvalidEvidenceQualificationError(
            "Every outcome of a manifested run must carry the same collection_plan_digest."
        )


def _normalized_keyword(keyword: str) -> str:
    return " ".join(str(keyword).split()).casefold()


def _canonicalize(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, Mapping):
        return {str(key): _canonicalize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonicalize(item) for item in value]
    return value


def _digest(payload: Mapping[str, Any]) -> str:
    canonical = json.dumps(
        _canonicalize(payload), sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _plain(value: Any) -> str:
    # A str-based Enum renders as "Timeframe.LAST_7D" under str(), and one backend reads the
    # value back as the enum while the other keeps the string, so the value is taken explicitly.
    return str(value.value if hasattr(value, "value") else value)


def compute_collection_plan_digest(plan: Mapping[str, Any]) -> str:
    """Bind the exact query, target, role, scope, sampling, and authority projection."""
    if not isinstance(plan, Mapping) or not plan:
        raise InvalidMissionManifestError("A collection plan must be a non-empty mapping.")
    return _digest(plan)


def compute_evidence_frame_digest(
    *,
    mission_id: Any,
    brief_revision_id: Optional[Any],
    manifest_digest: str,
    collection_plan_digest: str,
    observations_digest: str,
    qualifications_digest: str,
    channel_outcomes_digest: str,
    analysis_policy: str,
) -> str:
    """Derive the immutable identity consumed by qualification, claims, and rendering."""
    return _digest(
        {
            "mission_id": str(mission_id),
            "brief_revision_id": (
                str(brief_revision_id) if brief_revision_id is not None else None
            ),
            "manifest_digest": manifest_digest,
            "collection_plan_digest": collection_plan_digest,
            "observations_digest": observations_digest,
            "qualifications_digest": qualifications_digest,
            "channel_outcomes_digest": channel_outcomes_digest,
            "analysis_policy": analysis_policy,
        }
    )


def compute_candidate_claim_key(claim: Mapping[str, Any]) -> str:
    """Create a deterministic caller key when the host has not supplied one."""
    if not isinstance(claim, Mapping) or not claim:
        raise InvalidMissionClaimError("A candidate claim must be a non-empty mapping.")
    return _digest(claim)


def _claim_uuid(value: Any, field_name: str) -> UUID:
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (TypeError, ValueError) as exc:
        raise InvalidMissionClaimError(f"{field_name} '{value}' is not a UUID.") from exc


@dataclass(frozen=True)
class EvidenceFrame:
    mission_id: UUID
    brief_revision_id: Optional[UUID]
    manifest_digest: str
    collection_plan_digest: str
    observations_digest: str
    qualifications_digest: str
    channel_outcomes_digest: str
    analysis_policy: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "mission_id", _claim_uuid(self.mission_id, "mission_id"))
        if self.brief_revision_id is not None:
            object.__setattr__(
                self,
                "brief_revision_id",
                _claim_uuid(self.brief_revision_id, "brief_revision_id"),
            )
        for name in (
            "manifest_digest",
            "collection_plan_digest",
            "observations_digest",
            "qualifications_digest",
            "channel_outcomes_digest",
            "analysis_policy",
        ):
            if _is_blank(getattr(self, name)):
                raise InvalidMissionClaimError(f"{name} is required for an evidence frame.")

    @property
    def frame_digest(self) -> str:
        return compute_evidence_frame_digest(
            mission_id=self.mission_id,
            brief_revision_id=self.brief_revision_id,
            manifest_digest=self.manifest_digest,
            collection_plan_digest=self.collection_plan_digest,
            observations_digest=self.observations_digest,
            qualifications_digest=self.qualifications_digest,
            channel_outcomes_digest=self.channel_outcomes_digest,
            analysis_policy=self.analysis_policy,
        )

    def to_payload(self) -> Dict[str, Any]:
        return {
            "mission_id": str(self.mission_id),
            "brief_revision_id": (
                str(self.brief_revision_id) if self.brief_revision_id is not None else None
            ),
            "manifest_digest": self.manifest_digest,
            "collection_plan_digest": self.collection_plan_digest,
            "observations_digest": self.observations_digest,
            "qualifications_digest": self.qualifications_digest,
            "channel_outcomes_digest": self.channel_outcomes_digest,
            "analysis_policy": self.analysis_policy,
            "frame_digest": self.frame_digest,
        }


@dataclass(frozen=True)
class MissionClaimEvidence:
    claim_id: UUID
    observation_id: Optional[UUID]
    probe_outcome_id: Optional[UUID]
    role: EvidenceDirection
    hypothesis_target: Optional[str]
    binding_id: UUID = field(default_factory=uuid4)

    def __post_init__(self) -> None:
        object.__setattr__(self, "claim_id", _claim_uuid(self.claim_id, "claim_id"))
        object.__setattr__(self, "binding_id", _claim_uuid(self.binding_id, "binding_id"))
        identities = int(self.observation_id is not None) + int(self.probe_outcome_id is not None)
        if identities != 1:
            raise InvalidMissionClaimError(
                "A claim binding must name exactly one observation_id or probe_outcome_id."
            )
        if self.observation_id is not None:
            object.__setattr__(
                self, "observation_id", _claim_uuid(self.observation_id, "observation_id")
            )
        if self.probe_outcome_id is not None:
            object.__setattr__(
                self,
                "probe_outcome_id",
                _claim_uuid(self.probe_outcome_id, "probe_outcome_id"),
            )
        role = _coerce_claim_enum(EvidenceDirection, self.role, "role")
        object.__setattr__(self, "role", role)
        if role is not EvidenceDirection.CONTEXT and _is_blank(self.hypothesis_target):
            raise InvalidMissionClaimError(
                f"{role.value} bindings require a hypothesis_target."
            )

    def to_payload(self) -> Dict[str, Any]:
        return {
            "binding_id": str(self.binding_id),
            "claim_id": str(self.claim_id),
            "observation_id": str(self.observation_id) if self.observation_id else None,
            "probe_outcome_id": (
                str(self.probe_outcome_id) if self.probe_outcome_id else None
            ),
            "role": self.role.value,
            "hypothesis_target": self.hypothesis_target,
        }


def _coerce_claim_enum(enum_type, value: Any, field_name: str):
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(str(value).strip().upper())
    except ValueError as exc:
        raise InvalidMissionClaimError(f"{field_name} is invalid: {value!r}.") from exc


@dataclass(frozen=True)
class MissionClaim:
    mission_id: UUID
    frame_digest: str
    client_claim_key: str
    claim_type: ClaimType
    wording: str
    status: ClaimStatus
    created_by: str
    evidence_bindings: Tuple[MissionClaimEvidence, ...] = ()
    inference_method: Optional[str] = None
    confidence: Optional[float] = None
    limitations: Tuple[str, ...] = ()
    change_conditions: Tuple[str, ...] = ()
    withheld_reasons: Tuple[str, ...] = ()
    brief_revision_id: Optional[UUID] = None
    claim_id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        object.__setattr__(self, "mission_id", _claim_uuid(self.mission_id, "mission_id"))
        object.__setattr__(self, "claim_id", _claim_uuid(self.claim_id, "claim_id"))
        if self.brief_revision_id is not None:
            object.__setattr__(
                self,
                "brief_revision_id",
                _claim_uuid(self.brief_revision_id, "brief_revision_id"),
            )
        claim_type = _coerce_claim_enum(ClaimType, self.claim_type, "claim_type")
        status = _coerce_claim_enum(ClaimStatus, self.status, "status")
        object.__setattr__(self, "claim_type", claim_type)
        object.__setattr__(self, "status", status)
        for name in ("frame_digest", "client_claim_key", "wording", "created_by"):
            if _is_blank(getattr(self, name)):
                raise InvalidMissionClaimError(f"{name} is required.")
        if not isinstance(self.created_by, str) or len(self.created_by) > 128:
            raise InvalidMissionClaimError(
                "created_by must be a string of at most 128 characters."
            )
        if not isinstance(self.created_at, datetime) or self.created_at.tzinfo is None:
            raise InvalidMissionClaimError(
                "created_at must be a timezone-aware datetime."
            )
        if claim_type in (ClaimType.MEASUREMENT, ClaimType.INFERENCE, ClaimType.RECOMMENDATION):
            if _is_blank(self.inference_method):
                raise InvalidMissionClaimError(
                    f"{claim_type.value} requires an inference_method."
                )
        if claim_type in (ClaimType.INFERENCE, ClaimType.RECOMMENDATION):
            if not self.limitations or not self.change_conditions:
                raise InvalidMissionClaimError(
                    f"{claim_type.value} requires limitations and change_conditions."
                )
        if self.confidence is not None:
            if (
                isinstance(self.confidence, bool)
                or not isinstance(self.confidence, (int, float))
                or math.isnan(self.confidence)
                or not 0 <= float(self.confidence) <= 1
            ):
                raise InvalidMissionClaimError("confidence must be null or between 0 and 1.")
            object.__setattr__(self, "confidence", float(self.confidence))

    def to_payload(self) -> Dict[str, Any]:
        return {
            "claim_id": str(self.claim_id),
            "mission_id": str(self.mission_id),
            "brief_revision_id": (
                str(self.brief_revision_id) if self.brief_revision_id else None
            ),
            "frame_digest": self.frame_digest,
            "client_claim_key": self.client_claim_key,
            "claim_type": self.claim_type.value,
            "wording": self.wording,
            "inference_method": self.inference_method,
            "confidence": self.confidence,
            "limitations": list(self.limitations),
            "change_conditions": list(self.change_conditions),
            "status": self.status.value,
            "withheld_reasons": list(self.withheld_reasons),
            "created_by": self.created_by,
            "created_at": self.created_at.astimezone(timezone.utc).isoformat(),
            "evidence_bindings": [binding.to_payload() for binding in self.evidence_bindings],
        }

    def idempotency_payload(self) -> Dict[str, Any]:
        """Semantic caller payload, excluding server identities and persistence clocks."""
        bindings = [
            {
                "observation_id": (
                    str(binding.observation_id) if binding.observation_id else None
                ),
                "probe_outcome_id": (
                    str(binding.probe_outcome_id) if binding.probe_outcome_id else None
                ),
                "role": binding.role.value,
                "hypothesis_target": binding.hypothesis_target,
            }
            for binding in self.evidence_bindings
        ]
        bindings.sort(
            key=lambda item: (
                item["observation_id"] or "",
                item["probe_outcome_id"] or "",
                item["role"],
                item["hypothesis_target"] or "",
            )
        )
        return {
            "mission_id": str(self.mission_id),
            "brief_revision_id": (
                str(self.brief_revision_id) if self.brief_revision_id else None
            ),
            "frame_digest": self.frame_digest,
            "client_claim_key": self.client_claim_key,
            "claim_type": self.claim_type.value,
            "wording": self.wording,
            "inference_method": self.inference_method,
            "confidence": self.confidence,
            "limitations": list(self.limitations),
            "change_conditions": list(self.change_conditions),
            "status": self.status.value,
            "withheld_reasons": list(self.withheld_reasons),
            "created_by": self.created_by,
            "evidence_bindings": bindings,
        }


@dataclass(frozen=True)
class GapReport:
    withheld_outputs: Tuple[str, ...]
    failed_gates: Tuple[str, ...]
    missing_evidence: Tuple[str, ...]
    attempted_probes: Tuple[Mapping[str, Any], ...]
    safe_partial_conclusions: Tuple[str, ...]
    next_best_probe: str
    required_authority: Optional[str]
    estimated_cost: Optional[str]

    def to_payload(self) -> Dict[str, Any]:
        return {
            "withheld_outputs": list(self.withheld_outputs),
            "failed_gates": list(self.failed_gates),
            "missing_evidence": list(self.missing_evidence),
            "attempted_probes": [dict(probe) for probe in self.attempted_probes],
            "safe_partial_conclusions": list(self.safe_partial_conclusions),
            "next_best_probe": self.next_best_probe,
            "required_authority": self.required_authority,
            "estimated_cost": self.estimated_cost,
        }


# What a batch read or an analysis tells the Agent when recorded judgments leave the frame
# without an assessment: those judgments are final, so no further batch read can help.
REASSESSMENT_GUIDANCE = (
    "This mission's recorded judgments are final. Start a new mission or confirm a new Market "
    "Brief revision to assess the evidence again."
)
QUALIFICATION_STEP = (
    "Read the pending evidence with get_mission_evidence_qualification_batch, judge it, and record "
    "the judgments with submit_mission_evidence_qualifications."
)
ANALYSIS_STEP = "Every observation is assessed. Read the result with get_mission_analysis."


def compute_query_fingerprint(keywords: Sequence[str], geo: Any, timeframe: Any) -> str:
    """A digest of the exact query one surface ran, so a measured zero names what it measured."""
    return _digest(
        {
            "keywords": sorted(" ".join(str(k).split()) for k in keywords or []),
            "geo": _plain(geo),
            "timeframe": _plain(timeframe) if timeframe is not None else None,
        }
    )


def compute_frame_fingerprint(mission: Any, brief: Optional[MarketBriefRevision]) -> str:
    """A digest of the immutable question a judgment answers.

    Market: the exact confirmed Brief revision and its complete legacy or evidence-contract
    payload. Attention: the declared scope -- title and keywords, which hold the seed -- plus geo
    and timeframe. Run state is not part of the question, so a later run never invalidates a
    judgment of evidence it retained.
    """
    surface = resolve_surface(getattr(mission, "surface", None))
    payload: Dict[str, Any] = {"mission_id": str(mission.id), "surface": _plain(surface)}
    if surface is ResearchSurface.MARKET:
        if brief is None:
            raise InvalidEvidenceQualificationError(
                f"Market mission {mission.id} has no readable confirmed Brief, so there is no "
                "frame to judge its evidence against."
            )
        payload["brief"] = brief.to_payload()
    else:
        payload["scope"] = {
            "title": mission.title,
            "keywords": list(mission.keywords or []),
            "geo": _plain(mission.geo_code),
            "timeframe": _plain(mission.timeframe),
        }
    return _digest(payload)


@dataclass(frozen=True)
class QualificationProgress:
    """Counts over a mission's current evidence. Derived from persisted rows, never stored."""

    total_evidence: int = 0
    qualified_support: int = 0
    context_only: int = 0
    excluded_irrelevant: int = 0
    unassessed: int = 0
    evaluator_unavailable: int = 0
    # Current evidence with no persisted row at all: what the next batch read will hand out.
    unjudged: int = 0

    @classmethod
    def from_evidence(
        cls,
        observation_ids: Sequence[Any],
        qualifications: Sequence[EvidenceQualification],
    ) -> "QualificationProgress":
        current = {str(observation_id) for observation_id in observation_ids}
        by_observation = {
            str(q.observation_id): q for q in qualifications if str(q.observation_id) in current
        }
        relations = [q.relation for q in by_observation.values()]
        return cls(
            total_evidence=len(current),
            qualified_support=relations.count(QualificationRelation.QUALIFIED_SUPPORT),
            context_only=relations.count(QualificationRelation.CONTEXT_ONLY),
            excluded_irrelevant=relations.count(QualificationRelation.EXCLUDED_IRRELEVANT),
            unassessed=(len(current) - len(by_observation))
            + relations.count(QualificationRelation.UNASSESSED),
            evaluator_unavailable=sum(
                1
                for q in by_observation.values()
                if q.relation is QualificationRelation.UNASSESSED
                and q.reason_code is QualificationReason.EVALUATOR_UNAVAILABLE
            ),
            unjudged=len(current) - len(by_observation),
        )

    @property
    def assessed(self) -> int:
        return self.total_evidence - self.unassessed

    @property
    def is_complete(self) -> bool:
        return self.unassessed == 0

    @property
    def question_relevance_score(self) -> float:
        """Qualified support as a percentage of assessed evidence; zero when nothing was assessed."""
        if self.assessed <= 0:
            return 0.0
        return round(self.qualified_support / self.assessed * 100.0, 1)

    def to_payload(self) -> Dict[str, int]:
        return {
            "total_evidence": self.total_evidence,
            "qualified_support": self.qualified_support,
            "context_only": self.context_only,
            "excluded_irrelevant": self.excluded_irrelevant,
            "unassessed": self.unassessed,
        }


@dataclass(frozen=True)
class QualificationDecision:
    """Where the qualification of one persisted evidence state stands, and what the Agent does next."""

    status: QualificationStatus
    reason_code: Optional[str]
    next_step: str

    @property
    def pages_evidence(self) -> bool:
        """Only an incomplete frame hands out evidence; a terminal one would only waste judgments."""
        return self.reason_code == "QUALIFICATION_INCOMPLETE"


def decide_qualification(progress: QualificationProgress) -> QualificationDecision:
    """The one authority for qualification state, reason and next step.

    The submit response, the batch read, the analysis and the artifact all answer from this, so
    consecutive tool answers cannot contradict each other. Priority: a recorded evaluator failure
    outranks everything, pending evidence included, because the evaluator the rest would need has
    already failed. A recorded INSUFFICIENT_CONTENT row is a judgment about one item: the rest is
    still handed out, so the qualification counts stay complete for inspection, and the frame turns
    terminal once nothing is left to judge, because recorded judgments are write-once.
    """
    if progress.evaluator_unavailable:
        return QualificationDecision(
            QualificationStatus.UNAVAILABLE, "EVALUATOR_UNAVAILABLE", REASSESSMENT_GUIDANCE
        )
    if progress.unjudged:
        return QualificationDecision(
            QualificationStatus.QUALIFICATION_REQUIRED, "QUALIFICATION_INCOMPLETE", QUALIFICATION_STEP
        )
    if progress.unassessed:
        return QualificationDecision(
            QualificationStatus.QUALIFICATION_REQUIRED, "UNASSESSED_EVIDENCE", REASSESSMENT_GUIDANCE
        )
    return QualificationDecision(QualificationStatus.READY, None, ANALYSIS_STEP)


# ---------------------------------------------------------------------------
# Evidence sufficiency: the deterministic minimum for a verdict
# ---------------------------------------------------------------------------
#
# Product safety defaults, deliberately not configurable in this feature. The semantic judgment
# decides what an observation is; these decide whether enough of it exists to say anything.

QUALIFIED_DEMAND_MINIMUM = 1
POSITIVE_SUPPLY_OBSERVATIONS = 2
POSITIVE_SUPPLY_SOURCES = 2
MEASURED_ZERO_SURFACES = 2
HANDOFF_OBSERVATIONS = 2
HANDOFF_SOURCES = 2

# The platforms whose surfaces measure content supply. Platform identifiers, not vocabulary.
SUPPLY_SURFACE_PLATFORMS = frozenset({"youtube", "tiktok", "reels"})


@dataclass(frozen=True)
class QualifiedObservation:
    """One observation a mission's judgment qualified as support, reduced to what policy counts."""

    observation_id: str
    source_id: Optional[str]
    purpose: EvidencePurpose
    platform: str


@dataclass(frozen=True)
class TopicSufficiency:
    """Whether one Market topic may carry a demand-versus-supply verdict, and why."""

    topic: str
    state: EvidenceSufficiency
    qualified_demand_count: int = 0
    qualified_supply_count: int = 0
    independent_supply_sources: int = 0
    measured_zero_surfaces: Tuple[str, ...] = ()
    reason: str = ""


def assess_topic_sufficiency(
    topic: str,
    qualified: Sequence[QualifiedObservation],
    probe_outcomes: Sequence[MissionProbeOutcome],
    geo: Any,
    timeframe: Any,
    assessment_state: QualificationStatus,
) -> TopicSufficiency:
    """Apply the evidence minimum to one topic.

    `qualified` is the topic's QUALIFIED_SUPPORT evidence only; context-only, excluded and
    unassessed observations never reach this function. A measured zero is read from the persisted
    outcomes of the latest completed run, and only from surfaces that attested querying this
    topic in this geo and timeframe.
    """
    if assessment_state is QualificationStatus.QUALIFICATION_REQUIRED:
        return TopicSufficiency(
            topic=topic,
            state=EvidenceSufficiency.QUALIFICATION_REQUIRED,
            reason="Current mission evidence still requires semantic qualification.",
        )
    if assessment_state is QualificationStatus.UNAVAILABLE:
        return TopicSufficiency(
            topic=topic,
            state=EvidenceSufficiency.QUALIFIER_UNAVAILABLE,
            reason="A semantic judgment could not be obtained for some of the mission's evidence.",
        )

    demand = [q for q in qualified if q.purpose is EvidencePurpose.DEMAND]
    supply = [q for q in qualified if q.purpose is EvidencePurpose.SUPPLY]
    sources = {q.source_id for q in supply if q.source_id}
    zero_surfaces = tuple(sorted({
        o.connector_surface
        for o in probe_outcomes
        if o.platform in SUPPLY_SURFACE_PLATFORMS and o.measured_zero_for(topic, geo, timeframe)
    }))
    counts = dict(
        qualified_demand_count=len(demand),
        qualified_supply_count=len(supply),
        independent_supply_sources=len(sources),
        measured_zero_surfaces=zero_surfaces,
    )

    if len(demand) < QUALIFIED_DEMAND_MINIMUM:
        return TopicSufficiency(
            topic=topic,
            state=EvidenceSufficiency.MISSING_DEMAND,
            reason="No qualified demand observation addresses this topic.",
            **counts,
        )
    if len(supply) >= POSITIVE_SUPPLY_OBSERVATIONS and len(sources) >= POSITIVE_SUPPLY_SOURCES:
        return TopicSufficiency(
            topic=topic,
            state=EvidenceSufficiency.SUFFICIENT_POSITIVE_SUPPLY,
            reason="Qualified demand and qualified supply from independent sources.",
            **counts,
        )
    if not supply and len(zero_surfaces) >= MEASURED_ZERO_SURFACES:
        return TopicSufficiency(
            topic=topic,
            state=EvidenceSufficiency.SUFFICIENT_ZERO_SUPPLY,
            reason="Qualified demand, and relevant supply surfaces completed with no results.",
            **counts,
        )
    return TopicSufficiency(
        topic=topic,
        state=EvidenceSufficiency.MISSING_SUPPLY,
        reason=(
            "Supply is neither qualified by two observations from two independent sources nor "
            "measured absent by two completed, empty supply surfaces."
        ),
        **counts,
    )


@dataclass(frozen=True)
class HandoffCandidate:
    """An Attention cluster qualified to become the question of a new Market Brief."""

    cluster_id: str
    observation_ids: Tuple[str, ...]
    independent_sources: int


def select_handoff_candidates(
    qualified_by_cluster: Mapping[str, Sequence[QualifiedObservation]],
) -> List[HandoffCandidate]:
    """Every cluster backed by enough directly relevant evidence from independent sources.

    No fallback: when nothing qualifies the answer is an empty list, never the least-bad cluster.
    """
    candidates: List[HandoffCandidate] = []
    for cluster_id, observations in qualified_by_cluster.items():
        sources = {o.source_id for o in observations if o.source_id}
        if len(observations) >= HANDOFF_OBSERVATIONS and len(sources) >= HANDOFF_SOURCES:
            candidates.append(
                HandoffCandidate(
                    cluster_id=str(cluster_id),
                    observation_ids=tuple(sorted(o.observation_id for o in observations)),
                    independent_sources=len(sources),
                )
            )
    return sorted(candidates, key=lambda c: (-c.independent_sources, c.cluster_id))


@dataclass(frozen=True)
class QualificationContext:
    """Everything the analysis needs to know about a surfaced mission's evidence qualification.

    Read from persisted rows only. `assessment_state` is the status `decide_qualification` gives:
    UNAVAILABLE when an evaluator failure was recorded, QUALIFICATION_REQUIRED while any current
    observation has no row or carries an explicit UNASSESSED row, and READY only when every
    observation carries an actual assessment --
    READY here means "assessed"; whether a conclusion is permitted is decided afterwards by the
    sufficiency policy. A persisted row is not an assessment: UNASSESSED says none was made.
    """

    assessment_state: QualificationStatus
    progress: QualificationProgress
    qualifications: Mapping[str, EvidenceQualification] = field(default_factory=dict)
    probe_outcomes: Tuple[MissionProbeOutcome, ...] = ()
    geo: Optional[str] = None
    timeframe: Optional[str] = None

    @classmethod
    def build(
        cls,
        observation_ids: Sequence[Any],
        qualifications: Sequence[EvidenceQualification],
        probe_outcomes: Sequence[MissionProbeOutcome],
        geo: Any = None,
        timeframe: Any = None,
    ) -> "QualificationContext":
        current = {str(observation_id) for observation_id in observation_ids}
        by_observation = {
            str(q.observation_id): q for q in qualifications if str(q.observation_id) in current
        }
        progress = QualificationProgress.from_evidence(list(current), list(by_observation.values()))
        return cls(
            assessment_state=decide_qualification(progress).status,
            progress=progress,
            qualifications=by_observation,
            probe_outcomes=tuple(probe_outcomes),
            geo=_plain(geo) if geo is not None else None,
            timeframe=_plain(timeframe) if timeframe is not None else None,
        )

    @property
    def decision(self) -> QualificationDecision:
        return decide_qualification(self.progress)

    def judgment_of(self, observation_id: Any) -> Optional[EvidenceQualification]:
        return self.qualifications.get(str(observation_id)) if observation_id else None

    def support_of(self, observation_id: Any) -> Optional[EvidenceQualification]:
        """The judgment, only when it qualifies the observation as support."""
        judged = self.judgment_of(observation_id)
        if judged is not None and judged.relation is QualificationRelation.QUALIFIED_SUPPORT:
            return judged
        return None
