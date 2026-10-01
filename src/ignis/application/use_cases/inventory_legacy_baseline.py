"""Read-only classification of the historical unscoped baseline."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from typing import Any, Dict, Mapping

from ignis.application.ports.research_workspace_port import IResearchWorkspaceStore


class InventoryLegacyBaselineUseCase:
    """Propose exact targets without treating old sightings as mission evidence."""

    def __init__(self, store: IResearchWorkspaceStore):
        self._store = store

    async def execute(
        self, retention_reasons: Mapping[str, str] | None = None
    ) -> Dict[str, Any]:
        rows = await self._store.inventory_legacy_baseline()
        reasons = {
            str(signal_id): reason.strip() if isinstance(reason, str) else ""
            for signal_id, reason in (retention_reasons or {}).items()
        }
        if any(not reason for reason in reasons.values()):
            raise ValueError("Retention reason must be non-empty.")
        signals = rows["signals"]
        known_ids = {row["id"] for row in signals}
        unknown_ids = set(reasons) - known_ids
        if unknown_ids:
            raise ValueError("Retention reasons refer to targets outside the legacy baseline.")

        metric_ids: dict[str, list[int]] = defaultdict(list)
        for row in rows["metrics"]:
            metric_ids[row["signal_id"]].append(row["id"])

        archive = []
        deletion = []
        for row in signals:
            target = {
                "table": "trend_signals",
                "id": row["id"],
                "captured_at": row["captured_at"],
                "linked_metric_ids": metric_ids[row["id"]],
            }
            if row["id"] in reasons:
                archive.append({**target, "reason": reasons[row["id"]]})
            else:
                deletion.append(target)
        archive.extend(
            {"table": "signal_metrics", "id": metric_id, "reason": "MISSING_PARENT"}
            for metric_id in rows["orphan_metric_ids"]
        )

        target_bytes = json.dumps(
            {"archive": archive, "deletion": deletion, "orphan_metric_ids": rows["orphan_metric_ids"]},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        captured = sorted(str(row["captured_at"]) for row in signals if row["captured_at"])
        return {
            "status": "INVENTORY_ONLY",
            "archive_candidates": archive,
            "deletion_candidates": deletion,
            "orphan_metric_ids": rows["orphan_metric_ids"],
            "excluded_mission_rows": rows["excluded_mission_rows"],
            "legacy_signal_count": len(signals),
            "legacy_metric_count": len(rows["metrics"]),
            "captured_at_range": [captured[0], captured[-1]] if captured else None,
            "source_url_present": sum(bool(row["source_url_present"]) for row in signals),
            "metadata_present": sum(bool(row["metadata_present"]) for row in signals),
            "reproducibility": "UNVERIFIED",
            "remaining_product_value": "UNASSESSED",
            "target_digest": hashlib.sha256(target_bytes).hexdigest(),
            "recovery_required_before_deletion": True,
            "archive_verified": False,
            "promoted_to_mission_evidence": False,
        }
