import re
import math
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
    Strategic Reasoning Engine for Market Opportunity & White Space Discovery.
    Uses strict title matching to prevent false positive attribution.
    """

    VIETNAMESE_CHARS_PATTERN = re.compile(
        r"[àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđĐ]",
        re.IGNORECASE
    )

    FRENCH_WORDS = {"formation", "complete", "complète", "avec", "cours", "pour", "dans", "tuto", "debutant", "débutant"}

    VI_COMMON_WORDS = {
        "va", "cua", "la", "trong", "cho", "voi", "ve", "tu", "dong", "hoa",
        "huong", "dan", "cach", "lam", "chu", "doanh", "nghiep", "ung", "dung",
        "giai", "phap", "phan", "mem", "tri", "tue", "nhan", "tao", "tro", "ly",
        "kiem", "tien", "nguoi", "viet", "nam", "danh", "bai", "hoc", "khoa",
        "thuc", "chien", "tong", "quan"
    }

    # Danh mục rác tuyệt đối loại trừ khỏi phân tích công nghệ
    GARBAGE_EXCLUSIONS = [
        "khát khao độc chiếm", "audio chiếm hữu", "chanh non", "truyện audio", "đọc truyện",
        "phonegrid", "phone farm", "mmo", "forex", "bóng đá", "ur3", "cánh tay robot",
        "bánh răng", "xích tải", "bốc xếp", "bao tải", "đồ chơi", "lego", "anh khoa hay hỏi",
        "oprah", "the dark side of ai", "talkshow"
    ]

    def analyze_mission(
        self,
        mission: ResearchMission,
        signals: List[TrendSignal],
        clusters: List[TopicCluster],
        scorecard: QualityScorecard,
    ) -> HarnessResearchReport:
        opportunities = self._discover_market_opportunities(signals, mission.keywords)
        maturity_stage, maturity_reasons = self._evaluate_maturity_stage(signals, clusters)
        verified_trends = self._extract_verified_trends(signals, clusters)
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
        title_lower = title.lower()
        words = set(re.findall(r"\b[a-zA-ZàáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđĐ]+\b", title_lower))
        if any(fw in words for fw in self.FRENCH_WORDS):
            return False
        if self.VIETNAMESE_CHARS_PATTERN.search(title):
            return True
        vi_word_count = sum(1 for w in words if w in self.VI_COMMON_WORDS)
        return vi_word_count >= 2

    def _is_garbage(self, title: str) -> bool:
        t_low = title.lower()
        return any(g in t_low for g in self.GARBAGE_EXCLUSIONS)

    def _matches_topic_strictly(self, title: str, kw: str) -> bool:
        """
        Quy tắc so khớp nghiêm ngặt theo tiêu đề:
        Video chỉ được coi là thuộc chủ đề kw nếu tiêu đề thực sự chứa các thành tố cốt lõi.
        """
        if self._is_garbage(title):
            return False

        t = title.lower()
        k = kw.lower().strip()

        if k == "n8n":
            return "n8n" in t
        elif k == "mcp ai":
            return "mcp" in t or "model context protocol" in t
        elif k == "rpa":
            # Chỉ nhận diện phần mềm RPA (UiPath, Power Automate, RPA)
            return "rpa" in t or "uipath" in t or "power automate" in t or "robotic process automation" in t
        elif k == "ai agent doanh nghiệp":
            has_enterprise = any(w in t for w in ["doanh nghiệp", "enterprise", "b2b", "công ty"])
            has_agent = any(w in t for w in ["agent", "trợ lý", "ai", "tự động hóa"])
            return has_enterprise and has_agent
        elif k == "workflow automation":
            has_workflow = any(w in t for w in ["workflow", "quy trình", "n8n", "make.com", "zapier"])
            has_auto = any(w in t for w in ["tự động", "automation", "automate"])
            return has_workflow and has_auto
        elif k == "ai automation":
            has_ai = any(w in t for w in ["ai", "trí tuệ nhân tạo", "gpt", "claude"])
            has_auto = any(w in t for w in ["tự động", "automation", "automate"])
            return has_ai and has_auto
        elif k == "chatbot ai":
            return "chatbot" in t or ("bot" in t and "chat" in t)
        elif k == "trợ lý ai":
            return ("trợ lý" in t or "assistant" in t or "copilot" in t) and ("ai" in t or "ảo" in t)
        elif k == "tự động hóa ai":
            return ("tự động hóa" in t or "automation" in t) and ("ai" in t or "trí tuệ nhân tạo" in t)
        elif k == "ai agent":
            return "agent" in t
        else:
            return k in t

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
            demand_score = google_interests.get(kw_clean, 65.0)

            # 1. Khớp video nghiêm ngặt theo tiêu đề thực tế
            matching_videos = [
                s for s in youtube_signals 
                if self._matches_topic_strictly(s.raw_title, kw_clean)
            ]

            # 2. Lọc video tiếng Việt bản địa hóa thực sự
            vn_videos = [v for v in matching_videos if self._is_vietnamese(v.raw_title)]
            vn_views = sum(v.metric_value for v in vn_videos)
            vn_count = len(vn_videos)

            # 3. Tính điểm nguồn cung (Supply Score) chuẩn hóa toán học
            if vn_count == 0:
                supply_score = 0.0
            else:
                base_supply = min(80.0, vn_count * 7.5)
                view_factor = min(20.0, math.log10(max(10.0, vn_views)) * 3.5) if vn_views > 0 else 0.0
                supply_score = round(min(100.0, base_supply + view_factor), 1)

            opportunity_index = round(demand_score - supply_score, 1)

            # 4. Phân loại khoảng trống và khuyến nghị tiếng Việt mạch lạc, nhất quán logic
            if vn_count == 0 or opportunity_index >= 50.0:
                opp_type = "HIGH_DEMAND_LOW_SUPPLY"
                rec = f"Nhu cầu tìm kiếm về '{raw_kw}' đạt {demand_score:.0f}/100 nhưng nguồn cung video tiếng Việt rất mỏng ({vn_count} video). Cơ hội vàng để dẫn đầu thị phần."
            elif ("doanh nghiệp" in kw_clean or "enterprise" in kw_clean or "b2b" in kw_clean) and supply_score < 70.0:
                opp_type = "ENTERPRISE_GAP"
                rec = f"Khoảng trống B2B Doanh Nghiệp: Nhu cầu cao nhưng thiếu case-study thực chiến triển khai cho tổ chức tại Việt Nam ({vn_count} video)."
            elif supply_score >= 70.0:
                opp_type = "SATURATED_SEGMENT"
                rec = f"Phân khúc '{raw_kw}' đã có nhiều creator làm nội dung cơ bản ({vn_count} video tiếng Việt). Cần tiếp cận ở góc nhìn chuyên sâu hoặc giải pháp đóng gói."
            else:
                opp_type = "GROWING_OPPORTUNITY"
                rec = f"Phân khúc '{raw_kw}' đang trên đà tăng trưởng ({vn_count} video tiếng Việt), dung lượng thị trường còn rộng mở."

            # Đảm bảo supporting_signals nhất quán với số lượng video tiếng Việt thực chứng
            if vn_videos:
                support_sigs = [s.raw_title for s in vn_videos[:3]]
            else:
                support_sigs = ["Chưa ghi nhận video tiếng Việt nào trong timeframe 90 ngày."]

            opportunities.append(
                MarketOpportunity(
                    topic=raw_kw,
                    opportunity_type=opp_type,
                    search_interest_score=round(demand_score, 1),
                    content_supply_score=supply_score,
                    opportunity_index=opportunity_index,
                    strategic_recommendation=rec,
                    supporting_signals=support_sigs,
                )
            )

        return sorted(opportunities, key=lambda x: x.opportunity_index, reverse=True)

    def _evaluate_maturity_stage(
        self,
        signals: List[TrendSignal],
        clusters: List[TopicCluster],
    ) -> Tuple[TrendMaturityStage, List[str]]:
        yt_signals = [s for s in signals if s.platform == PlatformType.YOUTUBE and not self._is_garbage(s.raw_title)]
        how_to_count = sum(1 for s in yt_signals if "hướng dẫn" in s.raw_title.lower() or "là gì" in s.raw_title.lower() or "tutorial" in s.raw_title.lower() or "cơ bản" in s.raw_title.lower())
        total_yt = len(yt_signals)

        reasons = []
        if total_yt == 0:
            return TrendMaturityStage.EMERGING, ["Thị trường mới nổi, nguồn cung nội dung còn ở mức sơ khai."]

        how_to_ratio = how_to_count / float(total_yt)
        
        if how_to_ratio >= 0.4:
            reasons.append(f"{how_to_ratio * 100:.0f}% nội dung tập trung ở tầng nhập môn / kỹ năng cá nhân ('hướng dẫn', 'là gì').")
            reasons.append("Thị trường đang ở giai đoạn phổ cập kỹ năng (Early Adopter Wave).")
            return TrendMaturityStage.EMERGING, reasons
        elif any(c.cross_platform_score >= 70.0 for c in clusters):
            reasons.append("Tín hiệu bùng nổ đồng thời trên nhiều nền tảng với lượng tương tác đột biến.")
            return TrendMaturityStage.HYPING, reasons
        else:
            reasons.append("Hệ sinh thái phân hóa đa dạng và có sự tham gia của các tổ chức chuyên nghiệp.")
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
                if not self._is_garbage(s.raw_title):
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

        insights.append(f"Giai đoạn thị trường: {maturity_stage.value} — {'; '.join(maturity_reasons)}")

        top_gaps = [o for o in opportunities if o.opportunity_type in ["HIGH_DEMAND_LOW_SUPPLY", "ENTERPRISE_GAP"]]
        if top_gaps:
            gap_names = ", ".join([f"'{o.topic}'" for o in top_gaps[:3]])
            insights.append(f"Khoảng trống cơ hội chiến lược lớn nhất tập trung tại: {gap_names}.")
            actionables.append(f"Tập trung nguồn lực vào các chủ đề có nhu cầu cao {gap_names} để đón đầu thị phần.")

        n8n_signals = [s for s in signals if "n8n" in s.raw_title.lower() and not self._is_garbage(s.raw_title)]
        if len(n8n_signals) >= 3:
            insights.append("Cộng đồng No-code & Workflow Automation (đặc biệt là n8n) chiếm tỷ trọng lớn trong thảo luận chuyên môn.")
            actionables.append("Cảnh báo rủi ro Shadow Automation khi triển khai workflow tự động hóa phân tán không kiểm soát trong doanh nghiệp.")

        actionables.append("Thiết lập chu kỳ Ingress định kỳ mỗi 15 phút để phát hiện sớm các case-study mới xuất hiện.")

        return insights, actionables
