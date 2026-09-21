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

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple
from uuid import UUID, uuid4

from ignis.domain.exceptions import IgnisDomainException

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
    """Where a Market mission came from, when it came from an Attention result.

    Lineage is context. It records which Attention mission and cluster were selected for
    investigation; it never makes that Attention evidence into support for the Market hypothesis.
    """

    parent_attention_mission_id: Optional[UUID] = None
    parent_cluster_id: Optional[UUID] = None

    @property
    def is_empty(self) -> bool:
        return self.parent_attention_mission_id is None and self.parent_cluster_id is None

    def to_payload(self) -> Dict[str, Any]:
        return {
            "parent_attention_mission_id": (
                str(self.parent_attention_mission_id)
                if self.parent_attention_mission_id else None
            ),
            "parent_cluster_id": (
                str(self.parent_cluster_id) if self.parent_cluster_id else None
            ),
        }

    @classmethod
    def of_mission(cls, mission: Any) -> "MissionLineage":
        """Read the lineage a stored mission carries."""
        return cls(
            parent_attention_mission_id=getattr(mission, "parent_attention_mission_id", None),
            parent_cluster_id=getattr(mission, "parent_cluster_id", None),
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
        if missing:
            raise IncompleteMarketBriefError(missing)

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
            "confirmed_by": self.confirmed_by,
            "confirmed_at": self.confirmed_at.isoformat(),
        }
