from abc import ABC, abstractmethod
from datetime import datetime
from typing import Dict, Any, List, Optional
from uuid import UUID
from ignis.domain.entities import TrendSignal, TopicCluster, ResearchMission
from ignis.domain.value_objects import PlatformType, GeoCode, Timeframe


class ITrendRepository(ABC):
    """Giao diện cổng lưu trữ và truy vấn dữ liệu Trends, Missions & System Audit Logs."""

    @abstractmethod
    async def save_signals(self, signals: List[TrendSignal]) -> int:
        """Lưu danh sách signals vào cơ sở dữ liệu. Trả về số lượng đã lưu."""
        pass

    @abstractmethod
    async def save_clusters(self, clusters: List[TopicCluster]) -> None:
        """Lưu hoặc cập nhật thông tin các Topic Clusters."""
        pass

    @abstractmethod
    async def get_top_clusters(
        self, 
        geo: GeoCode = GeoCode.VN, 
        timeframe: Timeframe = Timeframe.LAST_24H, 
        limit: int = 10
    ) -> List[TopicCluster]:
        """Truy vấn các chủ đề có điểm momentum cao nhất."""
        pass

    @abstractmethod
    async def get_cluster_signals(
        self, 
        cluster_id: UUID, 
        timeframe: Timeframe = Timeframe.LAST_7D
    ) -> List[TrendSignal]:
        """Lấy toàn bộ lịch sử tín hiệu chuỗi thời gian của một cụm chủ đề."""
        pass

    @abstractmethod
    async def create_mission(self, mission: ResearchMission) -> ResearchMission:
        """Tạo mới một nhiệm vụ nghiên cứu."""
        pass

    @abstractmethod
    async def get_mission(self, mission_id: UUID) -> Optional[ResearchMission]:
        """Lấy thông tin chi tiết một nhiệm vụ nghiên cứu."""
        pass

    @abstractmethod
    async def update_mission(self, mission: ResearchMission) -> None:
        """Cập nhật thông tin/trạng thái nhiệm vụ nghiên cứu."""
        pass

    @abstractmethod
    async def list_missions(self, limit: int = 20) -> List[ResearchMission]:
        """Liệt kê các nhiệm vụ nghiên cứu gần nhất."""
        pass

    @abstractmethod
    async def get_mission_signals(self, mission_id: UUID) -> List[TrendSignal]:
        """Lấy tất cả các tín hiệu đa kênh đã cào được cho một nhiệm vụ nghiên cứu."""
        pass

    @abstractmethod
    async def delete_mission_signals(self, mission_id: UUID) -> int:
        """Xóa toàn bộ tín hiệu cũ của một nhiệm vụ nghiên cứu để nạp mới (Replace mode)."""
        pass

    @abstractmethod
    async def log_event(
        self,
        component: str,
        event_type: str,
        message: str,
        level: str = "INFO",
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Ghi vết sự kiện hệ thống / lỗi kết nối vào database."""
        pass

    @abstractmethod
    async def get_recent_logs(
        self,
        level: Optional[str] = None,
        component: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Truy vấn danh sách audit logs gần nhất."""
        pass

    @abstractmethod
    async def save_platform_credentials(
        self,
        platform: str,
        auth_type: str,
        credentials_data: Dict[str, Any],
        is_active: bool = True,
        expires_at: Optional[datetime] = None,
    ) -> None:
        """Lưu hoặc cập nhật thông tin phiên/token xác thực của mạng xã hội."""
        pass

    @abstractmethod
    async def get_platform_credentials(self, platform: str) -> Optional[Dict[str, Any]]:
        """Truy vấn phiên xác thực đang hoạt động của một nền tảng."""
        pass

    @abstractmethod
    async def list_platform_credentials(self) -> List[Dict[str, Any]]:
        """Liệt kê trạng thái kết nối tài khoản của tất cả các nền tảng."""
        pass

    @abstractmethod
    async def delete_platform_credentials(self, platform: str) -> bool:
        """Xóa hoặc vô hiệu hóa phiên xác thực của một nền tảng."""
        pass

    @abstractmethod
    async def get_domain_lexicons(self, domain: Optional[str] = None) -> List[Dict[str, Any]]:
        """Retrieve dynamic market lexicons, keywords, and slang terms from database."""
        pass

    @abstractmethod
    async def register_lexicon_terms(
        self,
        domain: str,
        terms: List[str],
        category: str = "vernacular",
        created_by: str = "agent",
    ) -> int:
        """Register or expand domain vocabulary and slang terms dynamically."""
        pass

    @abstractmethod
    async def get_industry_taxonomies(self) -> List[Dict[str, Any]]:
        """Retrieve all active industry taxonomies and category keyword mappings."""
        pass


