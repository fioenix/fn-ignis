"""Reading and writing optional identifiers, the same way on both backends.

SQLite stores a UUID as text and PostgreSQL stores it as a UUID, but both have to answer the
same question about a nullable foreign key: is this empty, or is it something this build cannot
read? Keeping the answer in one place is what stops the two backends from disagreeing about a
mission that belongs to no workspace.
"""

from datetime import datetime, timezone
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


def platform_key(platform: str) -> str:
    """The canonical key a credential row is stored and found under: trimmed, lower case.

    Callers spell a platform however they were handed it ("Threads", "threads "), and the
    repository port is the boundary that makes those one platform on both backends.
    """
    return str(platform or "").strip().lower()


def log_level(level: Optional[str]) -> Optional[str]:
    """The canonical spelling of an audit-log level: upper case, or None when absent."""
    return level.upper() if level else level


def ambiguous_platform_message(key: str, stored: list) -> str:
    """Why two stored rows for one platform are refused instead of one being picked.

    A row written under another casing before the key was canonical is still that platform's
    credential, so two of them mean two secrets for one platform. Choosing one, or folding them
    together, would be a guess made on the operator's behalf; deleting the platform clears both.
    """
    return (
        f"Platform credentials for '{key}' are ambiguous: rows {sorted(stored)} all normalize to "
        f"'{key}'. Delete the platform's credentials and authenticate again."
    )


def utc_iso(value: Any) -> Optional[str]:
    """A stored timestamp as the UTC ISO-8601 string the port promises, or None.

    PostgreSQL hands back a datetime and SQLite hands back whatever text was written, including
    `datetime('now')`'s space-separated form. A naive value is read as UTC, the same way the auth
    managers already read one. Text that is not a timestamp at all is returned unchanged rather
    than replaced by a guess or dropped.
    """
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value))
        except ValueError:
            return str(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()
