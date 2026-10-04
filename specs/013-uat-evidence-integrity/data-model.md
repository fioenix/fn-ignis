# Data Model

Threads search observations retain the first-query `matched_keyword` and add an ordered, unique `matched_keywords` list of actual query hits in existing metadata. Qualification batches preserve `probe_keyword` and expose additive `probe_keywords`; legacy scalar-only observations expose only their recorded scalar, never reconstructed historical hits. These labels do not establish semantic support or contradiction. No storage schema, source identity or qualification authority changes.

No new persisted schema is planned. Existing SearchAttestation queried/failures receive only proven public-query responses. Valid empty proves execution; missing/invalid response records failure. Observations are extracted only inside admitted result envelopes; windows remain unknown unless measured.

Existing authority chain: Mission Manifest → collection plan → channel outcome → observation association → semantic qualification → current frame → typed Claim Ledger. Downstream prose cannot replace a missing earlier proof.

UAT case fields: ID, baseline, linked issue/task, final revision/evidence and state. Runtime evidence is ignored; the canonical acceptance ledger is uat-ledger.md. States: pending → baseline observed → remediation verified → final UAT verified → integrated or explicitly parked.

Diagnostic projection permits query, exact-match boolean, HTTP status, schema field paths and hashed public post identities. It forbids headers/cookies/tokens/raw bodies/private content. Diagnostics never become market evidence.
