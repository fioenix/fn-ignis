"""Deterministic evidence for the additive migration-025 control plane."""

import json

from scripts import rehearse_evidence_grounded_schema as rehearsal


def test_rehearsal_preserves_baseline_and_does_not_promote_it():
    record = rehearsal.run_rehearsal()

    assert record["result"] == "PASSED"
    assert record["baseline"]["before"] == record["baseline"]["after"]
    assert record["control_plane"]["mission_evidence_count"] == 0
    assert record["control_plane"]["legacy_promoted"] is False


def test_rehearsal_names_exact_migration_and_projects_every_new_table():
    record = rehearsal.run_rehearsal()

    assert record["migration"]["file"] == rehearsal.MIGRATION_UNDER_REHEARSAL
    assert record["migration"]["sha256"] == rehearsal.sha256_of(
        rehearsal.SQL_DIR / rehearsal.MIGRATION_UNDER_REHEARSAL
    )
    assert set(record["control_plane"]["table_counts"]) == set(rehearsal.CONTROL_TABLES)
    assert all(record["control_plane"]["table_counts"][name] > 0 for name in rehearsal.CONTROL_TABLES)


def test_rehearsal_probes_constraints_instead_of_reading_only_schema_text():
    record = rehearsal.run_rehearsal()

    assert record["constraint_probes"] == {
        "empty_required_channels_refused": True,
        "invalid_v2_empty_outcome_refused": True,
        "foreign_observation_binding_refused": True,
        "inference_without_limitations_refused": True,
        "overlapping_manifest_channels_refused": True,
    }


def test_rehearsal_digest_is_deterministic_and_sensitive_to_projection_changes():
    first = rehearsal.run_rehearsal()
    second = rehearsal.run_rehearsal()

    assert first["evidence_digest"] == second["evidence_digest"]
    changed = json.loads(json.dumps(first))
    changed.pop("evidence_digest")
    changed["control_plane"]["table_counts"]["mission_claims"] += 1
    assert rehearsal.canonical_digest(changed) != first["evidence_digest"]


def test_failed_negative_control_makes_the_rehearsal_fail(monkeypatch):
    real = rehearsal.constraint_probes

    def weakened(connection):
        result = real(connection)
        result["foreign_observation_binding_refused"] = False
        return result

    monkeypatch.setattr(rehearsal, "constraint_probes", weakened)
    record = rehearsal.run_rehearsal()

    assert record["result"] == "FAILED"


def test_record_contains_no_target_or_credential_material():
    serialized = json.dumps(rehearsal.run_rehearsal())

    assert "://" not in serialized
    assert "password" not in serialized.lower()
    assert "/private/" not in serialized
