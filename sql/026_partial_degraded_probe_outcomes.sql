-- Owner-approved UAT-50 correction: keep partial observations from mixed-query failures.
-- Only the count CHECK changes. No evidence row, ID, attestation, qualification or claim is
-- updated; DEGRADED remains an incomplete measurement in the strategic sufficiency gate.
BEGIN;
ALTER TABLE mission_probe_outcomes
    DROP CONSTRAINT IF EXISTS mission_probe_outcomes_count_check;
ALTER TABLE mission_probe_outcomes
    ADD CONSTRAINT mission_probe_outcomes_count_check CHECK (
        signals_collected >= 0
        AND (
            (status = 'HEALTHY' AND signals_collected > 0)
            OR status = 'DEGRADED'
            OR (status NOT IN ('HEALTHY', 'DEGRADED') AND signals_collected = 0)
        )
    );
COMMIT;
