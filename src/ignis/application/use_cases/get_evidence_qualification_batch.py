"""Hand the host Agent a bounded batch of mission evidence that still needs a semantic judgment.

Ignis does not judge relevance itself: that is semantic synthesis, and it belongs to the Agent in
the loop. What Ignis owns is the frame -- the exact question the evidence is judged against --
and the identity of every observation handed out, so a judgment can only ever land on evidence the
mission actually holds.
"""

import base64
import binascii
import json
from typing import Any, Dict, Optional

from ignis.application.ports.repository_port import ITrendRepository
from ignis.application.ports.research_workspace_port import IResearchWorkspaceStore
from ignis.domain.entities import TrendSignal
from ignis.domain.probe_provenance import PROBE_KEY_ALIASES
from ignis.domain.research_workspace import (
    EvidencePurpose,
    QualificationProgress,
    QualificationRelation,
    ResearchSurface,
    compute_frame_fingerprint,
    resolve_surface,
)
from ignis.infrastructure.security.pii_sanitizer import sanitize_pii_text

DEFAULT_BATCH_LIMIT = 25
MAX_BATCH_LIMIT = 50
VIDEO_PLATFORMS = frozenset({"youtube", "tiktok", "reels"})


def _platform(signal: TrendSignal) -> str:
    platform = signal.platform
    return platform.value if hasattr(platform, "value") else str(platform)


def _metric_highlight(signal: TrendSignal) -> str:
    platform = _platform(signal)
    value = int(float(signal.metric_value or 0))
    if platform == "google":
        return f"search index {value}/100"
    unit = "views" if platform in VIDEO_PLATFORMS else "engagements"
    return f"{value} {unit}"


def encode_cursor(mission_id: str, frame_fingerprint: str, after: str) -> str:
    """An opaque position in one mission's pending evidence, bound to its frame."""
    payload = json.dumps({"m": mission_id, "f": frame_fingerprint, "a": after}, separators=(",", ":"))
    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii")


def decode_cursor(cursor: str) -> Optional[Dict[str, str]]:
    try:
        payload = json.loads(base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8"))
    except (ValueError, UnicodeError, binascii.Error):
        return None
    if not isinstance(payload, dict) or not all(isinstance(payload.get(k), str) for k in "mfa"):
        return None
    return payload


def market_frame_payload(brief: Any) -> Dict[str, Any]:
    return {
        "brief_revision_id": str(brief.brief_revision_id),
        "decision": brief.decision,
        "target_user": brief.target_user,
        "problem": brief.problem,
        "hypothesis": brief.hypothesis,
        "falsifiers": list(brief.falsifiers),
        "geo": brief.geo,
        "timeframe": brief.timeframe,
    }


def attention_frame_payload(mission: Any) -> Dict[str, Any]:
    # The seed is stored as the first keyword when one was given, so keywords carry it.
    geo = mission.geo_code
    timeframe = mission.timeframe
    return {
        "title": mission.title,
        "keywords": list(mission.keywords or []),
        "geo": geo.value if hasattr(geo, "value") else str(geo),
        "timeframe": timeframe.value if hasattr(timeframe, "value") else str(timeframe),
    }


class GetEvidenceQualificationBatchUseCase:
    """Read one stable, bounded page of current mission evidence that still lacks a judgment."""

    def __init__(self, repository: ITrendRepository, store: IResearchWorkspaceStore):
        self._repo = repository
        self._store = store

    async def execute(
        self,
        mission_id: str,
        cursor: Optional[str] = None,
        limit: int = DEFAULT_BATCH_LIMIT,
    ) -> Dict[str, Any]:
        mission = await self._repo.get_mission(mission_id)
        if mission is None:
            return {
                "status": "NOT_FOUND",
                "mission_id": str(mission_id),
                "error": f"No research mission found with ID or shortcode '{mission_id}'.",
            }
        surface = resolve_surface(mission.surface)
        base = {"mission_id": str(mission.id), "shortcode": mission.shortcode}
        if surface is None:
            return {
                **base,
                "status": "NOT_APPLICABLE",
                "note": (
                    "This mission declared no research surface, so it keeps its existing "
                    "behaviour and has nothing to qualify."
                ),
            }
        brief = None
        if surface is ResearchSurface.MARKET:
            brief = await self._store.get_brief_revision_for_mission(mission.id)
            if brief is None:
                return {
                    **base,
                    "status": "BLOCKED",
                    "surface": surface.value,
                    "error": (
                        "Market evidence is judged against the confirmed Market Brief, and this "
                        "mission has no readable confirmed Brief."
                    ),
                }

        frame_fingerprint = compute_frame_fingerprint(mission, brief)
        after = ""
        if cursor:
            position = decode_cursor(cursor)
            if (
                position is None
                or position["m"] != str(mission.id)
                or position["f"] != frame_fingerprint
            ):
                return {
                    **base,
                    "status": "CONFLICT",
                    "surface": surface.value,
                    "evidence": [],
                    "error": (
                        "The cursor does not belong to this mission and frame. Read the first "
                        "batch again without a cursor."
                    ),
                }
            after = position["a"]

        signals = await self._repo.get_mission_signals(mission.id)
        qualifications = await self._store.list_evidence_qualifications(mission.id)
        progress = QualificationProgress.from_evidence(
            [s.observation_id for s in signals], qualifications
        )
        judged = {str(q.observation_id) for q in qualifications}
        pending = sorted(
            (s for s in signals if s.observation_id and str(s.observation_id) not in judged),
            key=lambda s: str(s.observation_id),
        )
        payload: Dict[str, Any] = {
            **base,
            "surface": surface.value,
            "frame_fingerprint": frame_fingerprint,
            "progress": progress.to_payload(),
        }
        if not pending:
            return {**payload, "status": "READY", "evidence": [], "next_cursor": None}

        page_size = max(1, min(int(limit), MAX_BATCH_LIMIT))
        remaining = [s for s in pending if str(s.observation_id) > after]
        page = remaining[:page_size]
        next_cursor = (
            encode_cursor(str(mission.id), frame_fingerprint, str(page[-1].observation_id))
            if len(remaining) > page_size
            else None
        )
        return {
            **payload,
            "status": "QUALIFICATION_REQUIRED",
            "frame": (
                market_frame_payload(brief)
                if surface is ResearchSurface.MARKET
                else attention_frame_payload(mission)
            ),
            "pending_batches": -(-len(pending) // page_size),
            "evidence": [self._evidence(s) for s in page],
            "next_cursor": next_cursor,
            "recommended_judgment": {
                "relation": [r.value for r in QualificationRelation],
                "purpose": [p.value for p in EvidencePurpose],
            },
        }

    @staticmethod
    def _evidence(signal: TrendSignal) -> Dict[str, Any]:
        metadata = signal.metadata or {}
        excerpt = metadata.get("top_comment") or metadata.get("excerpt")
        return {
            "observation_id": str(signal.observation_id),
            "source_id": str(signal.source_id) if signal.source_id else None,
            "platform": _platform(signal),
            "connector_surface": metadata.get("connector_surface") or _platform(signal),
            "title": signal.raw_title,
            # Comments are written by the public, so a phone number or an e-mail in one is
            # masked before it leaves the server.
            "excerpt": sanitize_pii_text(str(excerpt)) if excerpt else None,
            # As the connector recorded it, not casefolded: it is shown to the Agent as the query.
            "probe_keyword": next(
                (
                    metadata[key].strip()
                    for key in PROBE_KEY_ALIASES
                    if isinstance(metadata.get(key), str) and metadata[key].strip()
                ),
                None,
            ),
            "metric_highlight": _metric_highlight(signal),
            "cluster_id": str(signal.cluster_id) if signal.cluster_id else None,
        }
