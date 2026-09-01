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
    BREAKOUT = "breakout"    # Tăng trưởng đột biến (> +100%)
    SURGING = "surging"      # Tăng trưởng nhanh (+50% đến +100%)
    STEADY = "steady"        # Ổn định
    DECLINING = "declining"  # Đang thoái trào
