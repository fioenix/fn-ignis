"""The one state no runtime may serve queries from.

sql/016 creates sources, observations and mission_evidence empty, and the corpus only moves into
them when scripts/backfill_observations.py runs. In between, a database holds a full legacy
trend_signals corpus and an empty new model: every read answers "there is nothing", every write
starts a second history beside the first, and the cluster pruner sees 15,754 memberships as
empty topics. Both backends refuse to open there, and say what ends the state.
"""

UNBACKFILLED_CORPUS = (
    "This database has rows in trend_signals and none in observations: sql/016 has been applied"
    " but the corpus was never carried over. Reads would answer from an empty model and writes"
    " would start a second history beside the legacy one. Run"
    " scripts/backfill_observations.py --apply, check it with"
    " scripts/post_migration_verification.py, and start the runtime after that."
)


def is_unbackfilled(has_legacy_rows: bool, has_observations: bool) -> bool:
    """True only for a legacy corpus that has not been carried over.

    A database with no legacy corpus at all was never waiting on anything, and one observation is
    enough to say the backfill ran -- how far it got is the verifier's question, not this one.
    """
    return bool(has_legacy_rows) and not bool(has_observations)
