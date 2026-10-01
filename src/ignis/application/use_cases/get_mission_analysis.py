import logging
from typing import Dict, Any, Optional
from uuid import UUID
from collections import defaultdict

from ignis.application.ports.repository_port import ITrendRepository
from ignis.application.ports.research_workspace_port import IResearchWorkspaceStore
from ignis.application.use_cases.current_evidence_frame import load_current_evidence_frame
from ignis.domain.research_workspace import (
    ClaimStatus,
    EvidenceRole,
    GapReport,
    InvalidMissionClaimError,
    MissionLineage,
    QualificationContext,
    QualificationRelation,
    ResearchSurface,
    assess_strategic_sufficiency,
    resolve_surface,
)

logger = logging.getLogger(__name__)


async def load_qualification_context(
    store: IResearchWorkspaceStore, mission, signals
) -> Optional[QualificationContext]:
    """The persisted qualification state of a surfaced mission, or None for a legacy one.

    Everything comes from stored rows -- the judgments, and the outcomes of the latest completed
    run -- so reopening a mission reads the same answer and calls no evaluator.
    """
    if resolve_surface(getattr(mission, "surface", None)) is None:
        return None
    return QualificationContext.build(
        observation_ids=[s.observation_id for s in signals if s.observation_id],
        qualifications=await store.list_evidence_qualifications(mission.id),
        probe_outcomes=await store.get_latest_completed_probe_outcomes(mission.id),
        geo=mission.geo_code,
        timeframe=mission.timeframe,
    )


class GetMissionAnalysisUseCase:
    """
    Use Case for retrieving Token-Efficient Mission Analysis data.
    Condenses datasets, extracts top signals, and strips redundant metadata to prevent LLM context bloat.
    """

    def __init__(
        self,
        repository: ITrendRepository,
        store: Optional[IResearchWorkspaceStore] = None,
    ):
        self._repo = repository
        self._store = store

    async def execute(
        self,
        mission_id: UUID,
        limit: int = 25,
        platform_filter: Optional[str] = None,
    ) -> Dict[str, Any]:
        mission = await self._repo.get_mission(mission_id)
        if not mission:
            raise ValueError(f"Research Mission {mission_id} does not exist.")

        signals = await self._repo.get_mission_signals(mission_id)

        # Which question these observations were collected to answer. A Market mission's own
        # evidence is what its Brief is judged against; an Attention mission's is context for a
        # question nobody has framed yet. A mission with no recorded surface gets no label,
        # because labelling it would claim a framing it never had.
        surface = resolve_surface(mission.surface)
        evidence_role = None
        if surface is ResearchSurface.MARKET:
            evidence_role = EvidenceRole.MARKET_EVIDENCE.value
        elif surface is ResearchSurface.ATTENTION:
            evidence_role = EvidenceRole.ATTENTION_CONTEXT.value
        lineage = MissionLineage.of_mission(mission)

        # Apply optional platform filter
        if platform_filter:
            signals = [
                s for s in signals 
                if (s.platform.value if hasattr(s.platform, "value") else str(s.platform)).lower() == platform_filter.lower()
            ]

        # Calculate platform distribution and channel breakdown
        platform_breakdown = defaultdict(int)
        channel_counts = defaultdict(int)
        total_views = 0.0

        for s in signals:
            p_val = s.platform.value if hasattr(s.platform, "value") else str(s.platform)
            platform_breakdown[p_val] += 1
            
            ch = s.metadata.get("channel_title")
            if ch:
                channel_counts[ch] += 1
            if p_val == "youtube":
                total_views += s.metric_value

        # Order signals by engagement metrics
        sorted_signals = sorted(signals, key=lambda x: (x.metric_value, x.growth_velocity), reverse=True)
        top_signals = sorted_signals[:limit]

        # Condense metadata to save tokens
        compact_signals = []
        for s in top_signals:
            p_str = s.platform.value if hasattr(s.platform, "value") else str(s.platform)
            
            clean_meta = {}
            if "channel_title" in s.metadata:
                clean_meta["channel"] = s.metadata["channel_title"]
            if "likes" in s.metadata:
                clean_meta["likes"] = s.metadata["likes"]
            if "comments" in s.metadata:
                clean_meta["comments"] = s.metadata["comments"]
            if "related_queries" in s.metadata:
                clean_meta["related_queries"] = s.metadata["related_queries"][:5]
            if "keyword" in s.metadata:
                clean_meta["keyword"] = s.metadata["keyword"]

            compact_signals.append({
                # The canonical evidence identity, so a reader can address the observation
                # rather than matching on a title or a URL.
                "observation_id": str(s.observation_id) if s.observation_id else None,
                "evidence_role": evidence_role,
                "platform": p_str,
                "title": s.raw_title,
                "metric_value": s.metric_value,
                "velocity_per_hour": s.growth_velocity,
                "url": s.source_url,
                "metadata": clean_meta,
            })

        # Top 5 most active creators
        top_channels = sorted(channel_counts.items(), key=lambda x: x[1], reverse=True)[:5]

        result = {
            "mission": {
                "id": str(mission.id),
                "title": mission.title,
                "keywords": mission.keywords,
                "geo": mission.geo_code.value if hasattr(mission.geo_code, "value") else str(mission.geo_code),
                "timeframe": mission.timeframe,
                "status": mission.status,
                "summary": mission.summary,
                "surface": surface.value if surface else None,
                "workspace_id": str(mission.workspace_id) if mission.workspace_id else None,
                "lineage": None if lineage.is_empty else lineage.to_payload(),
            },
            "stats": {
                "total_signals_collected": len(signals),
                "platform_breakdown": dict(platform_breakdown),
                "total_youtube_views": int(total_views),
                "top_creators": [{"channel": ch, "video_count": cnt} for ch, cnt in top_channels],
                "signals_returned": len(compact_signals),
                "note": f"Displaying top {len(compact_signals)} highest engagement signals. Use generate_mission_artifact to view the complete HTML dossier."
            },
            "top_signals": compact_signals,
        }
        if surface is ResearchSurface.MARKET:
            if self._store is None:
                result.update(
                    self._gap_payload(
                        None,
                        self._gap(
                            ("INCOMPLETE_MISSION_FRAME",),
                            ("Persisted mission workspace and Claim Ledger",),
                            "Open the mission with its persisted research workspace.",
                        ),
                        (),
                    )
                )
            else:
                result.update(await self._market_contract(mission))
        return result

    async def _market_contract(self, mission) -> Dict[str, Any]:
        """Return only current-frame persisted claims, or a typed Gap Report."""
        manifest = await self._store.get_mission_manifest(mission.id)
        brief = await self._store.get_brief_revision_for_mission(mission.id)
        signals = await self._repo.get_mission_signals(mission.id)
        qualifications = await self._store.list_evidence_qualifications(mission.id)
        outcomes = await self._store.get_latest_completed_probe_outcomes(mission.id)
        if manifest is None or brief is None:
            return self._gap_payload(
                None,
                self._gap(
                    ("INCOMPLETE_MISSION_FRAME",),
                    ("Mission Manifest and confirmed Market Brief",),
                    "Confirm a complete Market mission frame.",
                ),
                (),
            )
        try:
            frame = await load_current_evidence_frame(self._repo, self._store, mission, manifest)
        except InvalidMissionClaimError as exc:
            return self._gap_payload(
                None,
                self._gap(
                    ("INCOMPLETE_EVIDENCE_FRAME",),
                    (str(exc),),
                    "Complete one bounded collection frame.",
                ),
                (),
            )
        context = QualificationContext.build(
            [signal.observation_id for signal in signals if signal.observation_id],
            qualifications,
            outcomes,
            geo=mission.geo_code,
            timeframe=mission.timeframe,
        )
        qualification_payload = {
            **context.progress.to_payload(),
            "status": context.decision.status.value,
            "reason_code": context.decision.reason_code,
            "next_step": context.decision.next_step,
        }
        sufficiency = assess_strategic_sufficiency(
            manifest=manifest,
            brief=brief,
            qualifications=qualifications,
            probe_outcomes=outcomes,
            assessment_state=context.assessment_state,
            current_frame_digest=frame.frame_digest,
            submitted_frame_digest=frame.frame_digest,
            observations=signals,
            query_topics=mission.keywords,
        )
        await self._store.supersede_mission_claims(mission.id, frame.frame_digest)
        current = [
            claim
            for claim in await self._store.list_mission_claims(mission.id)
            if claim.frame_digest == frame.frame_digest
        ]
        permitted = [claim for claim in current if claim.status is ClaimStatus.PERMITTED]
        withheld = [claim for claim in current if claim.status is ClaimStatus.WITHHELD]
        if not sufficiency.ready:
            return self._gap_payload(
                frame,
                sufficiency.gap_report,
                withheld,
                qualification=qualification_payload,
            )
        if not permitted:
            reasons = tuple(
                dict.fromkeys(reason for claim in withheld for reason in claim.withheld_reasons)
            ) or ("NO_PERMITTED_CLAIMS",)
            return self._gap_payload(
                frame,
                GapReport(
                    withheld_outputs=self._forbidden_outputs(),
                    failed_gates=reasons,
                    missing_evidence=("current-frame permitted Claim Ledger entries",),
                    attempted_probes=tuple(self._outcome_payload(item) for item in outcomes),
                    safe_partial_conclusions=(),
                    next_best_probe=(
                        "Record evidence-bound candidate claims, including any required metric "
                        "denominator and timeframe."
                    ),
                    required_authority=None,
                    estimated_cost=None,
                ),
                withheld,
                qualification=qualification_payload,
            )

        grouped: Dict[str, list] = defaultdict(list)
        for claim in permitted:
            grouped[claim.claim_type.value].append(claim.to_payload())
        contradictions = [
            {
                "observation_id": str(item.observation_id),
                "hypothesis_target": item.hypothesis_target,
                "purpose": item.purpose.value,
                "confidence": item.confidence,
            }
            for item in qualifications
            if item.relation is QualificationRelation.QUALIFIED_CONTRADICTION
        ]
        return {
            "analysis_status": "READY",
            "evidence_frame": frame.to_payload(),
            "manifest_digest": manifest.manifest_digest,
            "brief_revision_id": str(brief.brief_revision_id),
            "collection_plan_digest": frame.collection_plan_digest,
            "channel_outcomes": [self._outcome_payload(item) for item in outcomes],
            "qualification": qualification_payload,
            "claim_ledger": dict(grouped),
            "contradictory_evidence": contradictions,
            "material_limitations": list(
                dict.fromkeys(
                    limitation for claim in permitted for limitation in claim.limitations
                )
            ),
            "decision_conditions": list(
                dict.fromkeys(
                    condition for claim in permitted for condition in claim.change_conditions
                )
            ),
            "withheld_claim_count": len(withheld),
            "withheld_reasons": list(
                dict.fromkeys(reason for claim in withheld for reason in claim.withheld_reasons)
            ),
            "retention_policy": manifest.retention_policy,
            "redaction_policy": "credentials-and-personal-data-redacted",
            "platform_policy": "authorized-surface-terms-apply",
            "reuse_limit": (
                "Another mission may use these records only after it explicitly associates and "
                "requalifies them against its own current frame."
            ),
        }

    @classmethod
    def _gap_payload(
        cls, frame, gap: GapReport, claims, qualification: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        payload = {
            "analysis_status": "INSUFFICIENT_EVIDENCE",
            **({"evidence_frame": frame.to_payload()} if frame is not None else {}),
            "gap_report": gap.to_payload(),
            "withheld_claim_count": len(claims),
            "withheld_reasons": list(
                dict.fromkeys(reason for claim in claims for reason in claim.withheld_reasons)
            ),
            "next_step": gap.next_best_probe,
        }
        if qualification is not None:
            payload["qualification"] = qualification
        return payload

    @classmethod
    def _gap(cls, gates, missing, next_probe) -> GapReport:
        return GapReport(
            withheld_outputs=cls._forbidden_outputs(),
            failed_gates=gates,
            missing_evidence=missing,
            attempted_probes=(),
            safe_partial_conclusions=(),
            next_best_probe=next_probe,
            required_authority=None,
            estimated_cost=None,
        )

    @staticmethod
    def _forbidden_outputs():
        return (
            "opportunity_index",
            "demand_gap",
            "whitespace",
            "saturation",
            "commercial_recommendations",
        )

    @staticmethod
    def _outcome_payload(outcome) -> Dict[str, Any]:
        return {
            "outcome_id": str(outcome.outcome_id),
            "connector_surface": outcome.connector_surface,
            "platform": outcome.platform,
            "status": outcome.status.value,
            "signals_collected": outcome.signals_collected,
            "query_fingerprint": outcome.query_fingerprint,
            "queried_window": outcome.queried_window,
        }
