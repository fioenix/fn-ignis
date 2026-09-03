from enum import Enum

class PlatformType(str, Enum):
    """
    Extensible connector platform identifier.
    Supports core built-in platforms and dynamic custom plugin registrations.
    """
    YOUTUBE = "youtube"
    GOOGLE_TRENDS = "google"
    TIKTOK = "tiktok"
    THREADS = "threads"
    REELS = "reels"

    @classmethod
    def _missing_(cls, value: object):
        if isinstance(value, str):
            clean_val = value.lower().strip()
            obj = str.__new__(cls, clean_val)
            obj._value_ = clean_val
            obj._name_ = clean_val.upper()
            return obj
        return None


class GeoCode(str, Enum):
    """
    ISO-3166-1 alpha-2 Geographic region code.
    Supports standard global country codes and custom regional targets.
    """
    VN = "VN"
    US = "US"
    GLOBAL = "GLOBAL"
    GB = "GB"
    JP = "JP"
    KR = "KR"
    TH = "TH"
    SG = "SG"
    MY = "MY"
    ID = "ID"
    PH = "PH"
    BR = "BR"
    DE = "DE"
    FR = "FR"
    ES = "ES"
    IT = "IT"
    AU = "AU"
    CA = "CA"
    IN = "IN"
    MX = "MX"

    @classmethod
    def _missing_(cls, value: object):
        if isinstance(value, str):
            clean_val = value.upper().strip()
            obj = str.__new__(cls, clean_val)
            obj._value_ = clean_val
            obj._name_ = clean_val
            return obj
        return None


class Timeframe(str, Enum):
    LAST_24H = "24h"
    LAST_7D = "7d"
    LAST_30D = "30d"
    LAST_90D = "90d"
    LAST_12M = "12m"


    @classmethod
    def _missing_(cls, value: object):
        if isinstance(value, str):
            clean_val = value.lower().strip()
            obj = str.__new__(cls, clean_val)
            obj._value_ = clean_val
            obj._name_ = clean_val.upper()
            return obj
        return None


class MomentumCategory(str, Enum):
    BREAKOUT = "breakout"    # Explosive velocity (> +100%)
    SURGING = "surging"      # Rapid growth (+50% to +100%)
    STEADY = "steady"        # Stable baseline
    DECLINING = "declining"  # Downward momentum


def resolve_geo(geo_input: object) -> GeoCode:
    """
    Resolve and validate Geographic region code without silent substitution.
    Accepts GeoCode enum or ISO-3166 alpha-2 country string (e.g. 'BR', 'KR', 'JP', 'DE', 'VN').
    """
    if isinstance(geo_input, GeoCode):
        return geo_input
    if not geo_input or not str(geo_input).strip():
        return GeoCode.VN
    clean = str(geo_input).strip().upper()
    return GeoCode(clean)


def resolve_platform(platform_input: object) -> PlatformType:
    """
    Resolve platform identifier for built-in or custom community connectors.
    Accepts PlatformType enum or string (e.g. 'youtube', 'reddit', 'xiaohongshu').
    """
    if isinstance(platform_input, PlatformType):
        return platform_input
    clean = str(platform_input).strip().lower()
    return PlatformType(clean)


def resolve_timeframe(timeframe_input: object) -> Timeframe:
    """Resolve timeframe expression."""
    if isinstance(timeframe_input, Timeframe):
        return timeframe_input
    clean = str(timeframe_input).strip().lower() if timeframe_input else "24h"
    return Timeframe(clean)


def timeframe_to_days(timeframe_input: object) -> int:
    """Convert timeframe enum or string into number of days for window calculations."""
    tf = resolve_timeframe(timeframe_input).value
    if tf == "24h":
        return 1
    elif tf == "7d":
        return 7
    elif tf == "30d":
        return 30
    elif tf == "90d":
        return 90
    elif tf == "12m":
        return 365
    return 90


