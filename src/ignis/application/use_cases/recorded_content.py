"""The recorded public content text an observation carries, as its connector stored it."""
from typing import Any, Mapping


def recorded_excerpt(metadata: Mapping[str, Any]) -> Any:
    """The recorded excerpt, else a recorded public description; None when neither was kept.

    An explicitly recorded excerpt wins and is returned as stored, so a malformed value still reaches
    the caller's own validation. A description is used only as non-empty text. This is a projection of
    persisted metadata: it never changes the observation, its judgment or any frame digest.
    """
    excerpt = metadata.get("excerpt")
    if excerpt is not None:
        return excerpt
    description = metadata.get("description")
    return description if isinstance(description, str) and description.strip() else None
