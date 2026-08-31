import re
from typing import List, Dict, Any, Tuple
from collections import defaultdict

from ignis.domain.entities import TrendSignal, TopicCluster, ResearchMission
from ignis.domain.harness_models import (
    MarketOpportunity,
    TrendMaturityStage,
    HarnessResearchReport,
    QualityScorecard,
)
from ignis.domain.value_objects import PlatformType


class StrategicMarketReasoner:
    """
    Động cơ suy luận chiến lược & phát hiện cơ hội thị trường (White Space Analysis).
    Bóc tách insight sâu sắc, tính toán khoảng trống cung-cầu chuẩn xác dựa trên nội dung bản địa hóa.
    """

    VIETNAMESE_PATTERN = re.compile(r"[àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ]", re.IGNORECASE)

    def analyze_mission(
        self,
        mission: ResearchMission,
        signals: List[TrendSignal],
        clusters: List[TopicCluster],
        scorecard: QualityScorecard,
    ) -> HarnessResearchReport:
        # 1. Phát hiện Market Opportunities (White Spaces)
        opportunities = self._discover_market_opportunities(signals, mission.keywords)

        # 2. Xác định Giai đoạn Trưởng thành (Maturity Stage)
        maturity_stage, maturity_reasons = self._evaluate_maturity_stage(signals, clusters)

        # 3. Tổng hợp Cross-Platform Verified Trends
        verified_trends = self._extract_verified_trends(signals, clusters)

        # 4. Trích xuất Strategic Insights & Actionables
        insights, actionables = self._synthesize_insights(
            mission, signals, opportunities, maturity_stage, maturity_reasons
        )

        return HarnessResearchReport(
            mission_id=str(mission.id),
            title=mission.title,
            scorecard=scorecard,
            maturity_stage=maturity_stage,
            verified_cross_platform_trends=verified_trends,
            market_opportunities=opportunities,
            strategic_insights=insights,
            actionable_takeaways=actionables,
        )

    def _is_vietnamese(self, title: str) -> bool:
        return bool(self.VIETNAMESE_PATTERN.search(title) or "là gì" in title.lower() or "hướng dẫn" in title.lower() or "tự động hóa" in title.lower())

    def _matches_topic(self, title: str, kw: str) -> bool:
        """Kiểm tra xem tiêu đề video có thực sự đề cập đến chủ đề kw hay không."""
        title_lower = title.lower()
        kw_lower = kw.lower()

        if kw_lower in title_lower:
            return True

        # Nếu là từ ghép như "AI agent doanh nghiệp", kiểm tra có chứa đủ các thành tố cốt lõi
        words = [w for w in kw_lower.split() if len(w) > 1]
        if len(words) >= 3:
            return all(w in title_lower for w in words)
        return False

    def _discover_market_opportunities(
        self,
        signals: List[TrendSignal],
        target_keywords: List[str],
    ) -> List[MarketOpportunity]:
        """
        Tìm khoảng trống thị trường: So sánh giữa Nhu cầu tìm kiếm (Google) và Nguồn cung nội dung bản địa hóa (YouTube VN).
        """
        opportunities: List[MarketOpportunity] = []
        
        google_interests: Dict[str, float] = {}
        google_related: Dict[str, List[str]] = {}
        youtube_signals: List[TrendSignal] = []

        for s in signals:
            if s.platform == PlatformType.GOOGLE_TRENDS:
                kw = s.metadata.get("keyword", s.raw_title.replace("Google Search Trends: ", ""))
                google_interests[kw] = s.metric_value
                google_related[kw] = s.metadata.get("related_queries", [])
            elif s.platform == PlatformType.YOUTUBE:
                youtube_signals.append(s)

        for kw in target_keywords:
            # 1. Nhu cầu tìm kiếm (Demand Score)
            demand_score = google_interests.get(kw, 65.0)

            # 2. Tìm tất cả video YouTube khớp với chủ đề kw
            matching_videos = [
                s for s in youtube_signals 
                if s.metadata.get("keyword") == kw or self._matches_topic(s.raw_title, kw)
            ]

            # 3. Lọc video tiếng Việt thực tế
            vn_videos = [v for v in matching_videos if self._is_vietnamese(v.raw_title)]
            vn_views = sum(v.metric_value for v in vn_videos)
            vn_count = len(vn_videos)

            # 4. Tính điểm nguồn cung nội dung tiếng Việt chuẩn xác (0 - 100)
            if vn_count == 0:
                supply_score = 0.0
            else:
                # Mỗi video tiếng Việt đóng góp 8 điểm supply + 1 điểm cho mỗi 10,000 views (tối đa 100)
                supply_score = min(100.0, round(vn_count * 8.0 + (vn_views / 15000.0), 1))

            opportunity_index = round(demand_score - supply_score, 1)

            # 5. Phân loại khoảng trống cơ hội
            if vn_count == 0 or opportunity_index >= 45.0:
                opp_type = "HIGH_DEMAND_LOW_SUPPLY"
                rec = f"Nhu cầu tìm kiếm về '{kw}' đạt {demand_score:.0f}/100 nhưng thị trường Việt Nam có nguồn cung mỏng ({vn_count} video). Cơ hội vàng để dẫn đầu thị phần."
            elif "doanh nghiệp" in kw.lower() or "enterprise" in kw.lower() or "b2b" in kw.lower():
                opp_type = "ENTERPRISE_GAP"
                rec = f"Khoảng trống B2B: Thiếu hụt nghiêm trọng các case-study và giải pháp triển khai thực tế cho tầng Doanh nghiệp tại Việt Nam ({vn_count} video)."
            elif supply_score >= 70.0:
                opp_type = "SATURATED_SEGMENT"
                rec = f"Phân khúc '{kw}' đã có nhiều creator làm nội dung cơ bản ({vn_count} video tiếng Việt). Cần tiếp cận ở góc nhìn nâng cao hoặc chuyên ngành."
            else:
                opp_type = "GROWING_OPPORTUNITY"
                rec = f"Phân khúc '{kw}' đang trên đà tăng trưởng ({vn_count} video tiếng Việt), dung lượng thị trường còn rộng mở."

            opportunities.append(
                MarketOpportunity(
                    topic=kw,
                    opportunity_type=opp_type,
                    search_interest_score=round(demand_score, 1),
                    content_supply_score=supply_score,
                    opportunity_index=opportunity_index,
                    strategic_recommendation=rec,
                    supporting_signals=[s.raw_title for s in vn_videos[:3]] or [s.raw_title for s in matching_videos[:2]],
                )
            )

        # Sắp xếp các cơ hội có chỉ số chênh lệch cao nhất (White Space lớn nhất) lên đầu
        return sorted(opportunities, key=lambda x: x.opportunity_index, reverse=True)

    def _evaluate_maturity_stage(
        self,
        signals: List[TrendSignal],
        clusters: List[TopicCluster],
    ) -> Tuple[TrendMaturityStage, List[str]]:
        yt_signals = [s for s in signals if s.platform == PlatformType.YOUTUBE]
        how_to_count = sum(1 for s in yt_signals if "hướng dẫn" in s.raw_title.lower() or "là gì" in s.raw_title.lower() or "tutorial" in s.raw_title.lower() or "cơ bản" in s.raw_title.lower())
        total_yt = len(yt_signals)

        reasons = []
        if total_yt == 0:
            return TrendMaturityStage.EMERGING, ["Chưa có nhiều nội dung video được tạo ra trên thị trường."]

        how_to_ratio = how_to_count / float(total_yt)
        
        if how_to_ratio >= 0.5:
            reasons.append(f"{how_to_ratio * 100:.0f}% nội dung tập trung ở tầng nhập môn / kỹ năng cá nhân ('hướng dẫn', 'là gì').")
            reasons.append("Thị trường đang ở giai đoạn phổ cập kỹ năng (Early Adopter Wave).")
            return TrendMaturityStage.EMERGING, reasons
        elif any(c.cross_platform_score >= 70.0 for c in clusters):
            reasons.append("Tín hiệu bùng nổ đồng thời trên nhiều nền tảng với lượng tương tác đột biến.")
            return TrendMaturityStage.HYPING, reasons
        else:
            reasons.append("Nội dung phân hóa đa dạng và có sự tham gia của các tổ chức chính thống.")
            return TrendMaturityStage.MATURE, reasons

    def _extract_verified_trends(
        self,
        signals: List[TrendSignal],
        clusters: List[TopicCluster],
    ) -> List[Dict[str, Any]]:
        verified = []
        for c in clusters[:6]:
            p_counts = defaultdict(int)
            total_views = 0.0
            for s in c.signals:
                p_counts[s.platform.value if hasattr(s.platform, "value") else str(s.platform)] += 1
                total_views += s.metric_value

            verified.append({
                "canonical_name": c.canonical_name,
                "momentum": c.momentum_category.value,
                "cross_platform_score": c.cross_platform_score,
                "platform_diversity": len(p_counts),
                "total_estimated_reach": int(total_views),
                "summary": c.summary_text,
            })
        return verified

    def _synthesize_insights(
        self,
        mission: ResearchMission,
        signals: List[TrendSignal],
        opportunities: List[MarketOpportunity],
        maturity_stage: TrendMaturityStage,
        maturity_reasons: List[str],
    ) -> Tuple[List[str], List[str]]:
        insights = []
        actionables = []

        insights.append(f"Giai đoạn thị trường: **{maturity_stage.value}** — {'; '.join(maturity_reasons)}")

        # Phân tích khoảng trống nổi bật nhất
        top_gaps = [o for o in opportunities if o.opportunity_type in ["HIGH_DEMAND_LOW_SUPPLY", "ENTERPRISE_GAP"]]
        if top_gaps:
            gap_names = ", ".join([f"'{o.topic}'" for o in top_gaps[:3]])
            insights.append(f"Khoảng trống cơ hội chiến lược lớn nhất tập trung tại: {gap_names}.")
            actionables.append(f"Tập trung đầu tư nội dung / giải pháp chuyên sâu cho các phân khúc {gap_names} để tận dụng lợi thế người tiên phong.")

        # Nhận diện No-code / n8n / Shadow Automation
        n8n_signals = [s for s in signals if "n8n" in s.raw_title.lower()]
        if len(n8n_signals) >= 3:
            insights.append("Cộng đồng No-code & Workflow Automation (đặc biệt là n8n) chiếm áp đảo về số lượng tutorial và case study thực hành.")
            actionables.append("Cảnh báo rủi ro Shadow Automation khi triển khai workflow tự động hóa không có cơ chế quản lý tập trung trong doanh nghiệp.")

        actionables.append("Thiết lập chu kỳ Ingress định kỳ mỗi 15 phút để phát hiện sớm các case-study mới xuất hiện.")

        return insights, actionables
