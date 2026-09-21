"""Reading and writing optional identifiers, the same way on both backends.

SQLite stores a UUID as text and PostgreSQL stores it as a UUID, but both have to answer the
same question about a nullable foreign key: is this empty, or is it something this build cannot
read? Keeping the answer in one place is what stops the two backends from disagreeing about a
mission that belongs to no workspace.
"""

from typing import Any, Optional
from uuid import UUID


def uuid_text(value: Optional[UUID]) -> Optional[str]:
    """An identifier in the form a parameter binding expects, or None.

    None is a value here, not a missing one: a mission created outside a research workspace
    genuinely has no workspace, and writing a placeholder would invent one.
    """
    return str(value) if value else None


def uuid_or_none(value: Any) -> Optional[UUID]:
    """Read a stored identifier back, leaving an unreadable one as None rather than raising.

    A mission row whose workspace column holds something that is not an identifier is a mission
    this build cannot scope. Refusing to hydrate it at all would make the entire mission
    unreadable over a field that every pre-workspace mission legitimately leaves empty.
    """
    if not value:
        return None
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return None
