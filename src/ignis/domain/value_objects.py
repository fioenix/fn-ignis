from enum import Enum

class PlatformType(str, Enum):
    YOUTUBE = "youtube"
    GOOGLE_TRENDS = "google"
    TIKTOK = "tiktok"
    THREADS = "threads"
    REELS = "reels"

class GeoCode(str, Enum):
    VN = "VN"
    US = "US"
    GLOBAL = "GLOBAL"

class Timeframe(str, Enum):
    LAST_24H = "24h"
    LAST_7D = "7d"
    LAST_30D = "30d"

class MomentumCategory(str, Enum):
    BREAKOUT = "breakout"    # Explosive velocity (> +100%)
    SURGING = "surging"      # Rapid growth (+50% to +100%)
    STEADY = "steady"        # Stable baseline
    DECLINING = "declining"  # Downward momentum

