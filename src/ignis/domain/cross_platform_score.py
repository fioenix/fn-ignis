"""How a topic's cross-platform score is computed. One definition, three callers.

The clusterer scores a group it has just built, and the persisted readers score a cluster from
the observations stored under it. Those answers have to agree: a topic that scores 62 when it is
formed and 41 when it is read back is not a score, it is two.

There were three copies before this: Python in the clusterer, and SQL in each repository, which
is how the SQL came to divide the platform count by five while the recorded decision says the
bands are 1 -> 0, 2 -> 20, 3+ -> 40. The repositories now aggregate in SQL and score here.

The 40 / 40 / 20 split is unchanged from the recorded contract: platform diversity, demand
volume, and growth velocity.
"""

from __future__ import annotations

import math

# A single platform says nothing about reach across platforms, which is what this score is for.
# Two is the first real signal of it, three or more is the whole of the available credit -- the
# corpus has five connectors and asking for all five would make the top band unreachable for a
# topic that is genuinely everywhere it belongs.
PLATFORM_BANDS = ((3, 40.0), (2, 20.0), (1, 0.0))

PLATFORM_WEIGHT = 40.0
METRIC_WEIGHT = 40.0
VELOCITY_WEIGHT = 20.0

# Logarithmic, because demand spans several orders of magnitude: 10^8 views is the ceiling of
# the metric scale and 10^4 %/hour of the velocity scale.
METRIC_LOG_CEILING = 8.0
VELOCITY_LOG_CEILING = 4.0


def platform_diversity_score(distinct_platforms: int) -> float:
    """Banded, not proportional. See PLATFORM_BANDS."""
    for threshold, score in PLATFORM_BANDS:
        if distinct_platforms >= threshold:
            return score
    return 0.0


def metric_score(total_metric: float) -> float:
    return min(
        METRIC_WEIGHT,
        (math.log10(max(0.0, total_metric) + 1.0) / METRIC_LOG_CEILING) * METRIC_WEIGHT,
    )


def velocity_score(average_velocity: float) -> float:
    return min(
        VELOCITY_WEIGHT,
        (math.log10(max(0.0, average_velocity) + 1.0) / VELOCITY_LOG_CEILING) * VELOCITY_WEIGHT,
    )


def cross_platform_score(
    distinct_platforms: int, total_metric: float, average_velocity: float
) -> float:
    """The score, from aggregates either caller can produce.

    The inputs are counted over one observation per source -- the most recent in the window --
    so a source polled hourly contributes exactly as much as one polled daily. Polling frequency
    is a property of the harness, not of the topic.
    """
    return round(
        min(
            100.0,
            platform_diversity_score(distinct_platforms)
            + metric_score(total_metric)
            + velocity_score(average_velocity),
        ),
        1,
    )
