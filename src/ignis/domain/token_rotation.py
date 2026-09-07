"""Expiry accounting and staggered refresh planning for platform credentials.

Tier-1 sessions (Threads, Instagram Reels, TikTok) are captured by hand, so they tend to be
created in one sitting and therefore expire in one sitting too. Planning refreshes apart from
each other keeps the always-on radar from losing every authenticated channel on the same day.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

# A credential is reported as expiring soon once it has less than this many days left.
TOKEN_EXPIRY_WARNING_DAYS = 7
# Minimum spacing between two recommended refreshes.
REFRESH_STAGGER_HOURS = 24
# A refresh is never planned later than this margin before the actual expiry.
MIN_REFRESH_MARGIN_HOURS = 24

STATUS_OK = "OK"
STATUS_EXPIRING_SOON = "EXPIRING_SOON"
STATUS_EXPIRED = "EXPIRED"
STATUS_UNKNOWN = "UNKNOWN_EXPIRY"


def parse_expiry(raw: Any) -> Optional[datetime]:
    """Parse an ISO-8601 expiry into an aware UTC datetime, or None when unusable."""
    if not raw:
        return None
    if isinstance(raw, datetime):
        parsed = raw
    else:
        try:
            parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def plan_staggered_refresh(
    credentials: List[Dict[str, Any]],
    now: Optional[datetime] = None,
    warning_days: int = TOKEN_EXPIRY_WARNING_DAYS,
    stagger_hours: int = REFRESH_STAGGER_HOURS,
) -> List[Dict[str, Any]]:
    """Return an expiry report per credential with a refresh slot spaced from the others.

    Credentials are planned in expiry order; each recommended slot starts `warning_days`
    before expiry and is pushed back until it is at least `stagger_hours` after the previous
    one, without ever crossing the safety margin in front of the real expiry.
    """
    now = now or datetime.now(timezone.utc)

    entries: List[Dict[str, Any]] = []
    for cred in credentials or []:
        platform = str(cred.get("platform") or "unknown").lower()
        expires_at = parse_expiry(cred.get("expires_at"))
        entries.append({
            "platform": platform,
            "auth_type": cred.get("auth_type"),
            "expires_at": expires_at.isoformat() if expires_at else None,
            "_expires_at": expires_at,
        })

    dated = sorted([e for e in entries if e["_expires_at"]], key=lambda e: e["_expires_at"])
    undated = [e for e in entries if not e["_expires_at"]]

    previous_slot: Optional[datetime] = None
    for entry in dated:
        expires_at = entry["_expires_at"]
        remaining = expires_at - now
        days_remaining = int(remaining.total_seconds() // 86400)

        if remaining.total_seconds() <= 0:
            entry["status"] = STATUS_EXPIRED
        elif days_remaining < warning_days:
            entry["status"] = STATUS_EXPIRING_SOON
        else:
            entry["status"] = STATUS_OK
        entry["days_remaining"] = days_remaining

        latest_safe = expires_at - timedelta(hours=MIN_REFRESH_MARGIN_HOURS)
        slot = max(expires_at - timedelta(days=warning_days), now)
        if previous_slot is not None and slot - previous_slot < timedelta(hours=stagger_hours):
            slot = previous_slot + timedelta(hours=stagger_hours)

        entry["stagger_conflict"] = slot > latest_safe
        if entry["stagger_conflict"]:
            slot = max(latest_safe, now)

        entry["recommended_refresh_at"] = slot.isoformat()
        previous_slot = slot

    for entry in undated:
        entry["status"] = STATUS_UNKNOWN
        entry["days_remaining"] = None
        entry["recommended_refresh_at"] = None
        entry["stagger_conflict"] = False

    for entry in dated + undated:
        entry.pop("_expires_at", None)
    return dated + undated


def build_expiry_alerts(plan: List[Dict[str, Any]], now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """Turn a refresh plan into health alerts for expired and soon-to-expire credentials."""
    now = now or datetime.now(timezone.utc)
    alerts: List[Dict[str, Any]] = []
    for entry in plan:
        if entry["status"] == STATUS_EXPIRED:
            alerts.append({
                "level": "CRITICAL",
                "type": "TOKEN_EXPIRED",
                "component": entry["platform"],
                "message": (
                    f"Credential for {entry['platform']} expired at {entry['expires_at']}. "
                    f"Re-authenticate with authenticate_{entry['platform']}()."
                ),
                "timestamp": now.isoformat(),
            })
        elif entry["status"] == STATUS_EXPIRING_SOON:
            message = (
                f"Credential for {entry['platform']} expires in {entry['days_remaining']} days "
                f"({entry['expires_at']}). Planned refresh: {entry['recommended_refresh_at']}."
            )
            if entry["stagger_conflict"]:
                message += " Refresh window overlaps another credential; refresh them on separate days."
            alerts.append({
                "level": "WARNING",
                "type": "TOKEN_EXPIRING_SOON",
                "component": entry["platform"],
                "message": message,
                "timestamp": now.isoformat(),
            })
    return alerts
