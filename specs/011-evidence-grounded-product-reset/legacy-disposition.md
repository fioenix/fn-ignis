# Legacy disposition — Supabase development inventory

## Authority and scope

On 2026-10-02 the owner confirmed that fn-ignis Supabase PostgreSQL is development-only and
authorized in-scope development operations without another database permission request.
This authorization does not itself establish that historical rows have no remaining value.

## Read-only inventory

- Unscoped legacy signals: 14,637; linked legacy metrics: 3,433.
- Mission-scoped signal rows excluded: 1,301; orphan metrics: 0.
- Capture range: 2026-08-09 through 2026-09-10.
- All 14,637 unscoped rows have a source URL and metadata.
- Remaining product value: unassessed; reproducibility: unverified.
- Exact private target list: `.handoff/011-dev-legacy-targets.json` (ignored runtime artifact).
- Target SHA-256: `a33608549ff45adf6a69cceb987710da4d6baa8efea9454f7e976e55617884ee`.

## Disposition

Keep the historical corpus untouched for now, excluded from mission evidence unless an explicitly
authorized task independently collects and qualifies observations. No record is promoted by the
migration. Archive/deletion is parked pending a concrete value assessment and a verified recovery
export; the owner has already authorized development database operations, so this is an evidence
safeguard, not an unresolved environment-permission gate.

The automatic classification labels all 14,637 rows as deletion candidates solely because no
retention reasons were supplied. That label is not proof of obsolescence and is not a deletion
instruction. Source/observation data and mission associations remain intact.
