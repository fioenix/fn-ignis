import logging
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any
from email.utils import parsedate_to_datetime
import urllib.parse

import httpx

from ignis.application.ports.connector_port import IConnectorPlugin
from ignis.domain.entities import TrendSignal
from ignis.domain.exceptions import ConnectorCapabilityUnavailableException, ConnectorExecutionException
from ignis.domain.value_objects import GeoCode, IngressScope, PlatformType, Timeframe

logger = logging.getLogger(__name__)


class GoogleTrendsRssPlugin(IConnectorPlugin):
    """
    Google Trends RSS observations and separately identified Autocomplete suggestions.

    Autocomplete expands keywords; it cannot measure demand, volume, or temporal growth.
    """

    BASE_RSS_URL = "https://trends.google.com/trending/rss"
    SUGGEST_API_URL = "https://suggestqueries.google.com/complete/search"
    HT_NAMESPACE = {"ht": "https://trends.google.com/trending/rss"}

    # The bare keyword. Not vocabulary in any language, so it is the one probe this plugin can
    # run before anybody hands it the persisted templates.
    BARE_KEYWORD_TEMPLATE = "{}"

    def __init__(self) -> None:
        # Both are filled from market_lexicons by the requested-task runtime before probing.
        self._probe_templates: Dict[str, List[str]] = {}
        self._intent_keywords: List[str] = []

    @property
    def platform(self) -> PlatformType:
        return PlatformType.GOOGLE_TRENDS

    @property
    def name(self) -> str:
        return "Google Trends Intelligence"

    def register_probe_templates(self, templates: Dict[str, List[str]]) -> None:
        """Bind the per-geo Google Suggest templates from the probe_templates_* lexicon domains.

        How a market phrases a question around a keyword is market vocabulary, so it is stored
        rather than compiled in. Keys are geo codes, plus DEFAULT for everywhere else.
        """
        cleaned = {
            str(geo).upper(): [str(p) for p in patterns if "{}" in str(p)]
            for geo, patterns in (templates or {}).items()
        }
        self._probe_templates = {geo: patterns for geo, patterns in cleaned.items() if patterns}

    def register_intent_keywords(self, terms: List[str]) -> None:
        """Bind the commercial and practical intent markers from the search_intent domain."""
        self._intent_keywords = sorted({t.strip().lower() for t in terms or [] if t and t.strip()})

    def _get_probe_patterns(self, geo_str: str) -> List[str]:
        if not self._probe_templates:
            logger.warning(
                "No probe templates registered: expanding the bare keyword alone. "
                "Check the probe_templates_* domains in market_lexicons."
            )
            return [self.BARE_KEYWORD_TEMPLATE]
        return self._probe_templates.get(
            geo_str.upper(),
            self._probe_templates.get("DEFAULT", [self.BARE_KEYWORD_TEMPLATE]),
        )

    def _geo_to_param(self, geo: GeoCode) -> str:
        geo_str = geo.value if hasattr(geo, "value") else str(geo)
        if geo_str.upper() in ("", "GLOBAL"):
            return ""
        return geo_str.upper()


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

    async def _probe_suggest(self, query: str, geo_str: str) -> Optional[List[str]]:
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
        }
        params = {
            "client": "firefox",
            "q": query,
            "hl": "vi",
        }
        if geo_str:
            params["gl"] = geo_str.lower()
        try:
            async with httpx.AsyncClient(timeout=6.0, headers=headers) as client:
                resp = await client.get(self.SUGGEST_API_URL, params=params)
                if resp.status_code == 200:
                    data = resp.json()
                    if (
                        isinstance(data, list) and len(data) > 1 and isinstance(data[1], list)
                        and all(isinstance(q, str) for q in data[1])
                    ):
                        return data[1]
        except Exception:
            pass
        return None

    async def fetch_suggestions(
        self, keywords: List[str], geo: GeoCode = GeoCode.VN,
    ) -> List[Dict[str, Any]]:
        """Return query-expansion observations, never Trends metric signals.

        A valid empty reply measures no suggestions, not zero market demand. A failed
        request measures nothing; retain that gap even if other probes answered.
        """
        batches: List[Dict[str, Any]] = []
        geo_str = self._geo_to_param(geo)
        for keyword in keywords:
            variants: Dict[str, str] = {}
            executed = failed = 0
            for pattern in self._get_probe_patterns(geo_str):
                suggestions = await self._probe_suggest(pattern.format(keyword), geo_str)
                if suggestions is None:
                    failed += 1
                    continue
                executed += 1
                for suggestion in suggestions:
                    cleaned = suggestion.strip()
                    if cleaned:
                        variants.setdefault(cleaned.casefold(), cleaned)
            batches.append({
                "keyword": keyword,
                "platform": "google_autocomplete",
                "data_source": "google_autocomplete",
                "measurement_type": "keyword_expansion",
                "geo_code": geo.value,
                "source_url": self.SUGGEST_API_URL,
                "captured_at": datetime.now(timezone.utc).isoformat(),
                "status": "DEGRADED" if failed else ("HEALTHY" if variants else "EMPTY_NO_DATA"),
                "probes_executed": executed,
                "failed_probes": failed,
                "suggestions_count": len(variants) if executed else None,
                "suggestions": [
                    {"query": value, "type": "autocomplete"}
                    for value in variants.values()
                ],
            })
        return batches

    def _explore_url(self, query: str, geo: GeoCode) -> str:
        """The Google Trends explore URL for one keyword, used as that topic's stable address."""
        geo_param = geo.value if hasattr(geo, "value") else str(geo)
        return (
            "https://trends.google.com/trends/explore?"
            f"date=now%207-d&geo={urllib.parse.quote(geo_param)}&q={urllib.parse.quote(query)}"
        )

    async def fetch_signals(
        self,
        geo: GeoCode = GeoCode.VN,
        timeframe: Timeframe = Timeframe.LAST_24H,
        limit: int = 50,
        scope: IngressScope = IngressScope.PUBLIC_MARKET,
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
                item_link = (link_elem.text or "").strip() if link_elem is not None else ""
                # Google repeats the feed's own URL in every item's <link>, so it identifies the
                # feed rather than the topic. Fall back to the keyword's explore URL, which is
                # distinct per trending topic and stable across polls.
                source_url = item_link if item_link and "/trending/rss" not in item_link \
                    else self._explore_url(title, geo)

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
                    captured_at=datetime.now(timezone.utc),
                    published_at=pub_date,
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
        """Fail visibly until a genuine keyword Trends measurement source is available."""
        if not keywords:
            return []
        raise ConnectorCapabilityUnavailableException(
            "Keyword Google Trends measurements are unavailable. Autocomplete is keyword "
            "expansion only; use fetch_suggestions. Trends RSS remains available as macro context."
        )
