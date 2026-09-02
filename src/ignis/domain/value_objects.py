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
    TH = "TH"
    SG = "SG"
    ID = "ID"
    DE = "DE"
    FR = "FR"

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

class MomentumCategory(str, Enum):
    BREAKOUT = "breakout"    # Explosive velocity (> +100%)
    SURGING = "surging"      # Rapid growth (+50% to +100%)
    STEADY = "steady"        # Stable baseline
    DECLINING = "declining"  # Downward momentum

