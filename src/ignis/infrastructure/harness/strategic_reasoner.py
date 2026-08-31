import re
import math
from typing import List, Dict, Any, Tuple, Set
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
    Bóc tách insight sâu sắc, áp dụng ánh xạ đồng nghĩa Anh - Việt và khử nhiễu ngữ cảnh công nghệ.
    """

    VIETNAMESE_CHARS_PATTERN = re.compile(
        r"[àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđĐ]",
        re.IGNORECASE
    )

    VI_COMMON_WORDS = {
        "va", "cua", "la", "trong", "cho", "voi", "ve", "tu", "dong", "hoa",
        "huong", "dan", "cach", "lam", "chu", "doanh", "nghiep", "ung", "dung",
        "giai", "phap", "phan", "mem", "tri", "tue", "nhan", "tao", "tro", "ly",
        "kiem", "tien", "nguoi", "viet", "viet", "nam", "danh", "cho", "bai",
        "hoc", "khoa", "hoc", "thuc", "chien", "tong", "quan"
    }

    # Bộ từ khóa nhiễu phần cứng / cơ khí / đồ chơi cần loại trừ khi đánh giá phần mềm tự động hóa
    HARDWARE_EXCLUSION_KEYWORDS = [
        "bốc xếp", "bao tải", "cánh tay robot", "bánh răng", "xích tải",
        "đồ chơi", "lego", "mô hình cơ khí", "robot công nghiệp hàn", "máy gắp"
    ]

    # Bản đồ ánh xạ từ khóa đồng nghĩa Anh - Việt
    SYNONYM_MAP: Dict[str, List[str]] = {
        "ai agent": ["agent ai", "trợ lý ai", "ai tự trị", "agentic ai"],
        "workflow automation": ["tự động hóa quy trình", "tự động hóa workflow", "workflow tự động", "quy trình tự động", "n8n", "make automation"],
        "ai automation": ["tự động hóa ai", "ai tự động hóa", "tự động hóa bằng ai", "ai automation agency"],
        "chatbot ai": ["ai chatbot", "bot chat", "trợ lý ảo chatbot", "bot tự động"],
        "ai agent doanh nghiệp": ["ai agent cho doanh nghiệp", "enterprise ai", "ai agent b2b", "ứng dụng ai trong doanh nghiệp", "tự động hóa doanh nghiệp"],
        "rpa": ["robotic process automation", "rpa tự động hóa", "tự động hóa quy trình nghiệp vụ", "uipath", "power automate", "bot rpa"],
        "n8n": ["n8n automation", "n8n tự động hóa", "workflow n8n", "n8n ai"],
        "mcp ai": ["model context protocol", "mcp claude", "mcp server", "mcp agent"],
        "trợ lý ai": ["ai assistant", "trợ lý ảo ai", "virtual assistant ai", "copilot"],
        "tự động hóa ai": ["ai automation", "tự động hóa với ai", "automation ai", "quy trình ai"],
    }

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
        if not title:
            return False
        if self.VIETNAMESE_CHARS_PATTERN.search(title):
            return True
        words = re.findall(r"\b[a-zA-Z]+\b", title.lower())
        vi_word_count = sum(1 for w in words if w in self.VI_COMMON_WORDS)
        return vi_word_count >= 2

    def _matches_topic(self, title: str, target_kw: str) -> bool:
        """Kiểm tra độ trùng khớp ngữ nghĩa kèm loại trừ nhiễu phần cứng."""
        title_lower = title.lower()
        kw_clean = target_kw.lower().strip()

        # 1. Nếu là RPA, loại bỏ triệt để video cơ khí phần cứng / đồ chơi
        if kw_clean == "rpa":
            for exc in self.HARDWARE_EXCLUSION_KEYWORDS:
                if exc in title_lower:
                    return False

        # 2. Khớp trực tiếp từ khóa
        if kw_clean in title_lower:
            return True

        # 3. Khớp qua danh sách đồng nghĩa
        synonyms = self.SYNONYM_MAP.get(kw_clean, [])
        for syn in synonyms:
            if syn in title_lower:
                return True

        # 4. Khớp từ ghép (ít nhất 2 từ cốt lõi)
        kw_words = [w for w in kw_clean.split() if len(w) > 1]
        if len(kw_words) >= 2:
            match_count = sum(1 for w in kw_words if w in title_lower)
            if match_count >= len(kw_words):
                return True

        return False

    def _discover_market_opportunities(
        self,
        signals: List[TrendSignal],
        target_keywords: List[str],
    ) -> List[MarketOpportunity]:
        opportunities: List[MarketOpportunity] = []
        
        google_interests: Dict[str, float] = {}
        youtube_signals: List[TrendSignal] = []

        for s in signals:
            if s.platform == PlatformType.GOOGLE_TRENDS:
                kw = s.metadata.get("keyword", s.raw_title.replace("Google Search Trends: ", ""))
                google_interests[kw.lower().strip()] = s.metric_value
            elif s.platform == PlatformType.YOUTUBE:
                youtube_signals.append(s)

        for raw_kw in target_keywords:
            kw_clean = raw_kw.lower().strip()
            # 1. Nhu cầu tìm kiếm (Demand Score)
            demand_score = google_interests.get(kw_clean, 65.0)

            # 2. Tìm tất cả video YouTube khớp với chủ đề kw
            matching_videos = [
                s for s in youtube_signals 
                if (s.metadata.get("keyword", "").lower() == kw_clean) or self._matches_topic(s.raw_title, kw_clean)
            ]

            # 3. Lọc video tiếng Việt thực tế
            vn_videos = [v for v in matching_videos if self._is_vietnamese(v.raw_title)]
            vn_views = sum(v.metric_value for v in vn_videos)
            vn_count = len(vn_videos)

            # 4. Tính điểm nguồn cung nội dung (Supply Score) chuẩn hóa theo số video thực tế
            if vn_count == 0:
                supply_score = 0.0
            else:
                # Tuyến tính theo số video (max 80) + Hệ số view logarithmic (max 20)
                base_supply = min(80.0, vn_count * 7.5)
                view_factor = min(20.0, math.log10(max(10.0, vn_views)) * 3.5) if vn_views > 0 else 0.0
                supply_score = round(min(100.0, base_supply + view_factor), 1)

            opportunity_index = round(demand_score - supply_score, 1)

            # 5. Phân loại khoảng trống cơ hội
            if vn_count == 0 or opportunity_index >= 50.0:
                opp_type = "HIGH_DEMAND_LOW_SUPPLY"
                rec = f"Nhu cầu tìm kiếm về '{raw_kw}' đạt {demand_score:.0f}/100 nhưng thị trường Việt Nam có nguồn cung rất mỏng ({vn_count} video). Cơ hội vàng để dẫn đầu thị phần."
            elif "doanh nghiệp" in kw_clean or "enterprise" in kw_clean or "b2b" in kw_clean:
                opp_type = "ENTERPRISE_GAP"
                rec = f"Khoảng trống B2B: Thiếu hụt nghiêm trọng các case-study và giải pháp triển khai thực tế cho tầng Doanh nghiệp tại Việt Nam ({vn_count} video)."
            elif supply_score >= 70.0:
                opp_type = "SATURATED_SEGMENT"
                rec = f"Phân khúc '{raw_kw}' đã có nhiều creator làm nội dung cơ bản ({vn_count} video tiếng Việt). Cần tiếp cận ở góc nhìn nâng cao hoặc giải pháp chuyên sâu."
            else:
                opp_type = "GROWING_OPPORTUNITY"
                rec = f"Phân khúc '{raw_kw}' đang trên đà tăng trưởng ({vn_count} video tiếng Việt), dung lượng thị trường còn rộng mở."

            opportunities.append(
                MarketOpportunity(
                    topic=raw_kw,
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
        
        if how_to_ratio >= 0.4:
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

        # Nhận diện No-code / n8n
        n8n_signals = [s for s in signals if "n8n" in s.raw_title.lower()]
        if len(n8n_signals) >= 3:
            insights.append("Cộng đồng No-code & Workflow Automation (đặc biệt là n8n) chiếm áp đảo về số lượng tutorial và case study thực hành.")
            actionables.append("Cảnh báo rủi ro Shadow Automation khi triển khai workflow tự động hóa không có cơ chế quản lý tập trung trong doanh nghiệp.")

        actionables.append("Thiết lập chu kỳ Ingress định kỳ mỗi 15 phút để phát hiện sớm các case-study mới xuất hiện.")

        return insights, actionables
