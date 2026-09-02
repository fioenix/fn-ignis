import logging
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any
from email.utils import parsedate_to_datetime
import urllib.parse

import httpx

from ignis.application.ports.connector_port import IConnectorPlugin
from ignis.domain.entities import TrendSignal
from ignis.domain.exceptions import ConnectorExecutionException
from ignis.domain.value_objects import GeoCode, PlatformType, Timeframe

logger = logging.getLogger(__name__)


class GoogleTrendsRssPlugin(IConnectorPlugin):
    """
    Ingress Plugin for Google Trends & Google Search Intent Intelligence.
    Measures dynamic search demand, query breadth, and intent depth via Google Suggest API multi-probing.
    """

    BASE_RSS_URL = "https://trends.google.com/trending/rss"
    SUGGEST_API_URL = "https://suggestqueries.google.com/complete/search"
    HT_NAMESPACE = {"ht": "https://trends.google.com/trending/rss"}

    # Localized probe variations to gauge market penetration across geographic targets
    DEFAULT_GEO_PROBES: Dict[str, List[str]] = {
        "VN": ["{}", "{} là gì", "{} việt nam", "cách dùng {}", "ứng dụng {}"],
        "DEFAULT": ["{}", "what is {}", "how to use {}", "best {} tools", "{} tutorial"],
    }

    @property
    def platform(self) -> PlatformType:
        return PlatformType.GOOGLE_TRENDS

    @property
    def name(self) -> str:
        return "Google Trends Intelligence"

    def _get_probe_patterns(self, geo_str: str) -> List[str]:
        return self.DEFAULT_GEO_PROBES.get(geo_str.upper(), self.DEFAULT_GEO_PROBES["DEFAULT"])

    def _geo_to_param(self, geo: GeoCode) -> str:
        geo_str = geo.value if hasattr(geo, "value") else str(geo)
        if geo_str.upper() in ("", "GLOBAL"):
            return ""
        return geo_str.upper()


    def _normalize_timeframe(self, timeframe_str: str) -> str:
        tf = timeframe_str.lower().strip()
        if tf in ["1d", "24h", "now 1-d"]:
            return "now 1-d"
        elif tf in ["7d", "now 7-d"]:
            return "now 7-d"
        elif tf in ["30d", "1m", "today 1-m"]:
            return "today 1-m"
        elif tf in ["90d", "3m", "today 3-m"]:
            return "today 3-m"
        elif tf in ["12m", "1y", "today 12-m"]:
            return "today 12-m"
        elif tf in ["5y", "today 5-y"]:
            return "today 5-y"
        return "today 3-m" if "90" in tf else "now 7-d"

    def _parse_traffic(self, traffic_str: Optional[str]) -> float:
        if not traffic_str:
            return 0.0
        cleaned = traffic_str.replace(",", "").replace("+", "").strip().upper()
        try:
            if cleaned.endswith("K"):
                return float(cleaned[:-1]) * 1000.0
            elif cleaned.endswith("M"):
                return float(cleaned[:-1]) * 1000000.0
            return float(cleaned)
        except ValueError:
            return 0.0

    def _parse_pub_date(self, date_str: Optional[str]) -> datetime:
        if not date_str:
            return datetime.now(timezone.utc)
        try:
            return parsedate_to_datetime(date_str)
        except Exception:
            return datetime.now(timezone.utc)

    async def is_healthy(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self.BASE_RSS_URL}?geo=VN")
                return resp.status_code == 200
        except Exception as e:
            logger.warning(f"Google Trends health check failed: {e}")
            return False

    async def _probe_suggest(self, query: str, geo_str: str) -> List[str]:
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
        }
        params = {
            "client": "firefox",
            "q": query,
            "gl": geo_str.lower() if geo_str else "vn",
            "hl": "vi",
        }
        try:
            async with httpx.AsyncClient(timeout=6.0, headers=headers) as client:
                resp = await client.get(self.SUGGEST_API_URL, params=params)
                if resp.status_code == 200:
                    data = resp.json()
                    if len(data) > 1 and isinstance(data[1], list):
                        return [q for q in data[1] if isinstance(q, str)]
        except Exception:
            pass
        return []

    async def _calculate_dynamic_search_demand(self, keyword: str, geo_str: str) -> Dict[str, Any]:
        """
        Multi-probe Google Suggest to calculate real, differentiated search demand index (0 - 100).
        Different topics exhibit varying penetration depth across query intents.
        """
        all_unique_queries = set()
        active_probes = 0

        probe_patterns = self._get_probe_patterns(geo_str)
        for pattern in probe_patterns:
            probe_q = pattern.format(keyword)
            results = await self._probe_suggest(probe_q, geo_str)
            if results:
                active_probes += 1
                for r in results:
                    all_unique_queries.add(r.lower().strip())

        total_unique_variants = len(all_unique_queries)

        # Baseline demand calculated from probe penetration & query variety
        penetration_score = (active_probes / float(len(probe_patterns))) * 45.0
        variety_score = min(35.0, total_unique_variants * 1.4)
        
        # Commercial / Practical intent depth bonus across VN and International markers
        intent_keywords = [
            "giá", "cách", "hướng dẫn", "doanh nghiệp", "tự động", "tool", "khóa học", "workflow", "cài đặt",
            "price", "how", "guide", "tutorial", "best", "tools", "enterprise", "api", "setup", "download", "free"
        ]
        intent_matches = sum(1 for q in all_unique_queries if any(k in q for k in intent_keywords))
        intent_bonus = min(20.0, intent_matches * 2.0)


        raw_score = penetration_score + variety_score + intent_bonus

        # Dynamic calibrated score (20.0 - 98.0)
        demand_index = round(min(98.0, max(25.0, raw_score)), 1)
        velocity = round(float(total_unique_variants * 1.5 + active_probes * 3.0), 1)

        return {
            "demand_index": demand_index,
            "velocity": velocity,
            "related_queries": sorted(list(all_unique_queries))[:12],
            "active_probes": active_probes,
            "unique_variants": total_unique_variants,
        }

    async def fetch_signals(
        self,
        geo: GeoCode = GeoCode.VN,
        timeframe: Timeframe = Timeframe.LAST_24H,
        limit: int = 50,
    ) -> List[TrendSignal]:
        geo_param = self._geo_to_param(geo)
        url = f"{self.BASE_RSS_URL}?geo={geo_param}" if geo_param else self.BASE_RSS_URL

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(url)
                response.raise_for_status()

            xml_data = response.content if isinstance(response.content, (bytes, bytearray)) else response.text.encode("utf-8")
            root = ET.fromstring(xml_data)
            signals: List[TrendSignal] = []

            for item in root.findall(".//item")[:limit]:
                title_elem = item.find("title")
                title = title_elem.text.strip() if title_elem is not None and title_elem.text else ""
                
                traffic_elem = item.find("ht:approx_traffic", self.HT_NAMESPACE)
                traffic_str = traffic_elem.text if traffic_elem is not None else "0"
                metric_value = self._parse_traffic(traffic_str)

                pub_date_elem = item.find("pubDate")
                pub_date = self._parse_pub_date(pub_date_elem.text if pub_date_elem is not None else None)

                link_elem = item.find("link")
                source_url = link_elem.text if link_elem is not None and link_elem.text else ""

                metadata: Dict[str, Any] = {
                    "raw_traffic": traffic_str,
                    "platform_source": "google_trends_rss",
                }

                news_item = item.find("ht:news_item", self.HT_NAMESPACE)
                if news_item is not None:
                    news_title = news_item.find("ht:news_item_title", self.HT_NAMESPACE)
                    news_snippet = news_item.find("ht:news_item_snippet", self.HT_NAMESPACE)
                    news_url = news_item.find("ht:news_item_url", self.HT_NAMESPACE)
                    news_source = news_item.find("ht:news_item_source", self.HT_NAMESPACE)

                    if news_title is not None and news_title.text:
                        metadata["news_title"] = news_title.text
                    if news_snippet is not None and news_snippet.text:
                        metadata["news_snippet"] = news_snippet.text
                    if news_url is not None and news_url.text:
                        metadata["news_url"] = news_url.text
                    if news_source is not None and news_source.text:
                        metadata["news_source"] = news_source.text

                signal = TrendSignal(
                    platform=PlatformType.GOOGLE_TRENDS,
                    raw_title=title,
                    metric_value=metric_value,
                    growth_velocity=0.0,
                    source_url=source_url,
                    geo_code=geo,
                    metadata=metadata,
                    captured_at=pub_date,
                )
                signals.append(signal)

            return signals
        except Exception as e:
            logger.error(f"Error parsing Google Trends RSS: {e}", exc_info=True)
            raise ConnectorExecutionException(f"Failed to parse Google Trends RSS: {e}") from e

    async def search_signals(
        self,
        keywords: List[str],
        geo: GeoCode = GeoCode.VN,
        timeframe: Timeframe = Timeframe.LAST_24H,
        limit: int = 20,
        custom_timeframe: Optional[str] = None,
    ) -> List[TrendSignal]:
        signals: List[TrendSignal] = []
        geo_code_str = self._geo_to_param(geo)
        
        tf_input = custom_timeframe or (timeframe.value if hasattr(timeframe, "value") else str(timeframe))
        tf_google = self._normalize_timeframe(tf_input)

        for kw in keywords:
            encoded_kw = urllib.parse.quote(kw)
            explore_url = f"https://trends.google.com/trends/explore?date={urllib.parse.quote(tf_google)}&geo={geo_code_str}&q={encoded_kw}"

            # Calculate real dynamic demand via multi-probe analysis
            demand_data = await self._calculate_dynamic_search_demand(kw, geo_code_str)

            meta = {
                "keyword": kw,
                "timeframe_requested": tf_input,
                "timeframe_google": tf_google,
                "explore_url": explore_url,
                "related_queries": demand_data["related_queries"],
                "active_probes": demand_data["active_probes"],
                "unique_variants": demand_data["unique_variants"],
                "data_source": "google_search_dynamic_probes",
            }

            signal = TrendSignal(
                platform=PlatformType.GOOGLE_TRENDS,
                raw_title=f"Google Search Trends: {kw}",
                metric_value=demand_data["demand_index"],
                growth_velocity=demand_data["velocity"],
                source_url=explore_url,
                geo_code=geo,
                metadata=meta,
                captured_at=datetime.now(timezone.utc),
            )
            signals.append(signal)

        return signals
