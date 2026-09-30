#!/usr/bin/env python
"""Rehearse the migration-025 projection on a disposable SQLite database.

The rehearsal never accepts a database target. It creates one temporary file, projects fixed
synthetic baseline and mission rows into the current SQLite schema contract, probes constraints by
violating them, and removes the file. PostgreSQL executes the SQL migration itself in the migration
contract suite; this script supplies a deterministic, reviewable evidence manifest without a path
that can write to a configured or persistent database.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from ignis.infrastructure.persistence.sqlite_repository import (  # noqa: E402
    SqliteTrendRepository,
)


SQL_DIR = REPO / "sql"
MIGRATION_UNDER_REHEARSAL = "025_evidence_grounded_claim_ledger.sql"
CONTROL_TABLES = (
    "market_brief_revisions",
    "mission_manifests",
    "mission_probe_outcomes",
    "mission_evidence_qualifications",
    "mission_claims",
    "mission_claim_evidence",
)

STAMP = "2026-09-30T00:00:00+00:00"
WORKSPACE = "00000000-0000-4000-8000-000000000101"
MARKET_MISSION = "00000000-0000-4000-8000-000000000102"
OTHER_MISSION = "00000000-0000-4000-8000-000000000103"
BRIEF = "00000000-0000-4000-8000-000000000104"
RUN = "00000000-0000-4000-8000-000000000105"
OTHER_RUN = "00000000-0000-4000-8000-000000000106"
SOURCE = "00000000-0000-4000-8000-000000000107"
OTHER_SOURCE = "00000000-0000-4000-8000-000000000108"
OBSERVATION = "00000000-0000-4000-8000-000000000109"
OTHER_OBSERVATION = "00000000-0000-4000-8000-000000000110"
CLAIM = "00000000-0000-4000-8000-000000000111"


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_digest(payload: Any) -> str:
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _rows_digest(connection: sqlite3.Connection, table: str, columns: tuple[str, ...]) -> Dict[str, Any]:
    rows = connection.execute(
        f"SELECT {', '.join(columns)} FROM {table} ORDER BY {', '.join(columns)}"
    ).fetchall()
    projection = [list(row) for row in rows]
    return {"count": len(rows), "digest": canonical_digest(projection)}


def baseline_projection(connection: sqlite3.Connection) -> Dict[str, Any]:
    return {
        "trend_signals": _rows_digest(
            connection,
            "trend_signals",
            ("id", "platform", "raw_title", "metric_value", "captured_at"),
        ),
        "signal_metrics": _rows_digest(
            connection,
            "signal_metrics",
            ("id", "signal_id", "captured_at", "metric_value", "growth_velocity"),
        ),
    }


def _seed_synthetic_projection(connection: sqlite3.Connection) -> None:
    connection.execute(
        "INSERT INTO trend_signals"
        " (id, platform, raw_title, metric_value, captured_at) VALUES (?, ?, ?, ?, ?)",
        ("legacy-signal", "youtube", "Legacy baseline only", 7.0, STAMP),
    )
    connection.execute(
        "INSERT INTO signal_metrics"
        " (id, signal_id, captured_at, metric_value, growth_velocity) VALUES (?, ?, ?, ?, ?)",
        (1, "legacy-signal", STAMP, 7.0, 0.0),
    )
    connection.commit()


def _seed_control_plane(connection: sqlite3.Connection) -> None:
    connection.execute(
        "INSERT INTO research_workspaces (id, slug, root_path, status, created_at)"
        " VALUES (?, ?, ?, ?, ?)",
        (WORKSPACE, "schema-rehearsal", "/synthetic", "READY", STAMP),
    )
    for mission_id, surface in ((MARKET_MISSION, "MARKET"), (OTHER_MISSION, "ATTENTION")):
        connection.execute(
            "INSERT INTO research_missions"
            " (id, title, keywords, platforms, workspace_id, surface, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                mission_id,
                f"Synthetic {surface.lower()} mission",
                '["synthetic"]',
                '["youtube"]',
                WORKSPACE,
                surface,
                STAMP,
            ),
        )
    connection.execute(
        "INSERT INTO market_brief_revisions"
        " (id, workspace_id, mission_id, revision_number, decision, target_user, problem, geo,"
        " timeframe, hypothesis, falsifiers, alternative_hypotheses, null_hypothesis,"
        " kill_criteria, revision_rule, evidence_contract_version, confirmed_by, confirmed_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            BRIEF,
            WORKSPACE,
            MARKET_MISSION,
            1,
            "Decide whether to proceed",
            "Operators",
            "Manual setup",
            "VN",
            "30d",
            "Setup friction is material",
            '["No repeated friction"]',
            '["Training gap", "Temporary novelty"]',
            "There is no material effect",
            '["No qualified friction"]',
            "Reframe when the target user changes",
            2,
            "schema-rehearsal",
            STAMP,
        ),
    )
    connection.execute(
        "INSERT INTO mission_manifests"
        " (mission_id, outcome, decision_context, required_channels, optional_channels,"
        " authority_boundary, quota_budget, output_type, stop_conditions, analysis_policy,"
        " retention_policy, created_by, confirmed_at, manifest_digest)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            MARKET_MISSION,
            "Produce an auditable frame",
            "Owner decides whether to proceed",
            '["youtube"]',
            "[]",
            '{"public_http":true}',
            "{}",
            "MARKET_ANALYSIS",
            '["frame complete"]',
            "evidence-gated-v1",
            "mission-only",
            "schema-rehearsal",
            STAMP,
            "a" * 64,
        ),
    )
    for run_id, mission_id, sequence in ((RUN, MARKET_MISSION, 1), (OTHER_RUN, OTHER_MISSION, 2)):
        connection.execute(
            "INSERT INTO mission_run_journals"
            " (id, workspace_id, mission_id, journal_path, sequence, status, started_at, completed_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                run_id,
                WORKSPACE,
                mission_id,
                f"/synthetic/{run_id}.md",
                sequence,
                "COMPLETED",
                STAMP,
                STAMP,
            ),
        )
    connection.execute(
        "INSERT INTO mission_probe_outcomes"
        " (id, run_id, platform, connector_surface, status, signals_collected, queried_keywords,"
        " queried_window, query_fingerprint, scope_attestation, collection_plan_digest,"
        " evidence_contract_version, completed_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "00000000-0000-4000-8000-000000000112",
            RUN,
            "youtube",
            "youtube",
            "EMPTY_NO_DATA",
            0,
            '["synthetic"]',
            "30d",
            "b" * 64,
            '{"geo":"VN","timeframe":"30d"}',
            "c" * 64,
            2,
            STAMP,
        ),
    )
    for source_id, external_id, observation_id, title in (
        (SOURCE, "video:owned", OBSERVATION, "Owned evidence"),
        (OTHER_SOURCE, "video:foreign", OTHER_OBSERVATION, "Foreign evidence"),
    ):
        connection.execute(
            "INSERT INTO sources (id, platform, external_id) VALUES (?, ?, ?)",
            (source_id, "youtube", external_id),
        )
        connection.execute(
            "INSERT INTO observations"
            " (id, source_id, observed_at, time_provenance, identity_source, observed_title)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (
                observation_id,
                source_id,
                STAMP,
                "exact_ingestion",
                "metadata_external_id",
                title,
            ),
        )
    connection.execute(
        "INSERT INTO mission_evidence (id, mission_id, observation_id, recorded_at)"
        " VALUES (?, ?, ?, ?)",
        ("00000000-0000-4000-8000-000000000113", MARKET_MISSION, OBSERVATION, STAMP),
    )
    connection.execute(
        "INSERT INTO mission_evidence (id, mission_id, observation_id, recorded_at)"
        " VALUES (?, ?, ?, ?)",
        ("00000000-0000-4000-8000-000000000114", OTHER_MISSION, OTHER_OBSERVATION, STAMP),
    )
    connection.execute(
        "INSERT INTO mission_evidence_qualifications"
        " (id, mission_id, observation_id, brief_revision_id, frame_fingerprint, relation,"
        " purpose, confidence, reason_code, judged_by, hypothesis_target, evidence_role,"
        " evidence_contract_version, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "00000000-0000-4000-8000-000000000115",
            MARKET_MISSION,
            OBSERVATION,
            BRIEF,
            "d" * 64,
            "QUALIFIED_SUPPORT",
            "VOC",
            0.8,
            "DIRECT_TO_FRAME",
            "schema-rehearsal",
            "core",
            "SUPPORT",
            2,
            STAMP,
        ),
    )
    connection.execute(
        "INSERT INTO mission_claims"
        " (id, mission_id, brief_revision_id, frame_digest, client_claim_key, claim_type,"
        " wording, status, created_by, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            CLAIM,
            MARKET_MISSION,
            BRIEF,
            "e" * 64,
            "synthetic-claim",
            "OBSERVATION",
            "One owned source describes friction.",
            "PERMITTED",
            "schema-rehearsal",
            STAMP,
        ),
    )
    connection.execute(
        "INSERT INTO mission_claim_evidence"
        " (id, claim_id, observation_id, role, hypothesis_target) VALUES (?, ?, ?, ?, ?)",
        (
            "00000000-0000-4000-8000-000000000116",
            CLAIM,
            OBSERVATION,
            "SUPPORT",
            "core",
        ),
    )
    connection.commit()


def _refused(connection: sqlite3.Connection, statement: str, parameters: tuple[Any, ...]) -> bool:
    try:
        connection.execute(statement, parameters)
    except sqlite3.IntegrityError:
        connection.rollback()
        return True
    connection.rollback()
    return False


def constraint_probes(connection: sqlite3.Connection) -> Dict[str, bool]:
    return {
        "empty_required_channels_refused": _refused(
            connection,
            "INSERT INTO mission_manifests"
            " (mission_id, outcome, required_channels, optional_channels, authority_boundary,"
            " quota_budget, output_type, stop_conditions, analysis_policy, retention_policy,"
            " created_by, confirmed_at, manifest_digest)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                OTHER_MISSION,
                "Invalid manifest",
                "[]",
                "[]",
                "{}",
                "{}",
                "COLLECTION_FRAME",
                '["stop"]',
                "v1",
                "mission-only",
                "schema-rehearsal",
                STAMP,
                "f" * 64,
            ),
        ),
        "overlapping_manifest_channels_refused": _refused(
            connection,
            "INSERT INTO mission_manifests"
            " (mission_id, outcome, required_channels, optional_channels, authority_boundary,"
            " quota_budget, output_type, stop_conditions, analysis_policy, retention_policy,"
            " created_by, confirmed_at, manifest_digest)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                OTHER_MISSION,
                "Invalid overlap",
                '["youtube"]',
                '["youtube"]',
                "{}",
                "{}",
                "COLLECTION_FRAME",
                '["stop"]',
                "v1",
                "mission-only",
                "schema-rehearsal",
                STAMP,
                "i" * 64,
            ),
        ),
        "invalid_v2_empty_outcome_refused": _refused(
            connection,
            "INSERT INTO mission_probe_outcomes"
            " (id, run_id, platform, connector_surface, status, signals_collected,"
            " queried_keywords, query_fingerprint, scope_attestation, collection_plan_digest,"
            " evidence_contract_version, completed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "00000000-0000-4000-8000-000000000117",
                OTHER_RUN,
                "youtube",
                "youtube",
                "EMPTY_NO_DATA",
                0,
                "[]",
                "g" * 64,
                '{"geo":"VN"}',
                "h" * 64,
                2,
                STAMP,
            ),
        ),
        "foreign_observation_binding_refused": _refused(
            connection,
            "INSERT INTO mission_claim_evidence"
            " (id, claim_id, observation_id, role, hypothesis_target) VALUES (?, ?, ?, ?, ?)",
            (
                "00000000-0000-4000-8000-000000000118",
                CLAIM,
                OTHER_OBSERVATION,
                "SUPPORT",
                "core",
            ),
        ),
        "inference_without_limitations_refused": _refused(
            connection,
            "INSERT INTO mission_claims"
            " (id, mission_id, brief_revision_id, frame_digest, client_claim_key, claim_type,"
            " wording, inference_method, change_conditions, status, created_by, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "00000000-0000-4000-8000-000000000119",
                MARKET_MISSION,
                BRIEF,
                "e" * 64,
                "inference-without-limitations",
                "INFERENCE",
                "Unsupported inference",
                "method-v1",
                '["new evidence"]',
                "WITHHELD",
                "schema-rehearsal",
                STAMP,
            ),
        ),
    }


def _legacy_promoted_count(connection: sqlite3.Connection) -> int:
    return connection.execute(
        "SELECT count(*) FROM mission_evidence e"
        " JOIN observations o ON o.id = e.observation_id"
        " WHERE o.observed_title = 'Legacy baseline only'"
    ).fetchone()[0]


def _initialize(path: Path) -> None:
    async def _run() -> None:
        repository = SqliteTrendRepository(str(path))
        try:
            await repository._ensure_schema()
        finally:
            await repository.close()

    asyncio.run(_run())


def run_rehearsal() -> Dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="ignis-evidence-rehearsal-") as directory:
        path = Path(directory) / "rehearsal.sqlite"
        _initialize(path)
        with sqlite3.connect(path) as connection:
            connection.execute("PRAGMA foreign_keys = ON")
            _seed_synthetic_projection(connection)
            before = baseline_projection(connection)
            _seed_control_plane(connection)
            probes = constraint_probes(connection)
            after = baseline_projection(connection)
            promoted = _legacy_promoted_count(connection)
            counts = {
                table: connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                for table in CONTROL_TABLES
            }
            mission_evidence_total = connection.execute(
                "SELECT count(*) FROM mission_evidence"
            ).fetchone()[0]

    record: Dict[str, Any] = {
        "task": "T019",
        "migration": {
            "file": MIGRATION_UNDER_REHEARSAL,
            "sha256": sha256_of(SQL_DIR / MIGRATION_UNDER_REHEARSAL),
        },
        "backend": "sqlite-disposable",
        "baseline": {"before": before, "after": after},
        "control_plane": {
            "table_counts": counts,
            "mission_evidence_count": promoted,
            "mission_evidence_total": mission_evidence_total,
            "legacy_promoted": promoted > 0,
        },
        "constraint_probes": probes,
        "disposition": {
            "scratch_only": True,
            "persistent_database_touched": False,
            "baseline_rows_mutated": before != after,
        },
    }
    record["result"] = (
        "PASSED"
        if before == after and promoted == 0 and all(probes.values())
        else "FAILED"
    )
    record["evidence_digest"] = canonical_digest(record)
    return record


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args(argv)
    record = run_rehearsal()
    rendered = json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0 if record["result"] == "PASSED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
