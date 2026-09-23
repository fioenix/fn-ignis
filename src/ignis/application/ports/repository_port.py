from abc import ABC, abstractmethod
from datetime import datetime
from typing import Dict, Any, List, Optional, TypedDict
from uuid import UUID
from ignis.domain.entities import TrendSignal, TopicCluster, ResearchMission
from ignis.domain.value_objects import GeoCode, Timeframe


class PlatformCredentialSummary(TypedDict):
    """What `list_platform_credentials` answers: which platforms are connected, never the secret.

    Both backends return exactly these keys. Timestamps are UTC ISO-8601 strings or None, so a
    caller never has to know which backend produced them.
    """

    platform: str
    auth_type: str
    is_active: bool
    expires_at: Optional[str]
    updated_at: Optional[str]


class PlatformCredentialRecord(PlatformCredentialSummary):
    """What `get_platform_credentials` answers: the summary plus the decrypted credential."""

    credentials_data: Dict[str, Any]


class ITrendRepository(ABC):
    """Port interface for storing and querying Trend signals, Research Missions, and System Audit Logs."""

    @abstractmethod
    async def save_signals(self, signals: List[TrendSignal]) -> int:
        """Save a batch of trend signals into the database. Returns the number of inserted records."""
        pass

    async def prune_empty_clusters(self) -> int:
        """Delete clusters that no longer have a single signal, returning how many were removed.

        Re-clustering moves a signal from the cluster it was in to the one it now belongs to, so a
        stale cluster can be left holding nothing. Those rows are invisible to every read path
        (which joins signals) yet keep growing, and their canonical_name is a copy of the text that
        formed them. Cluster ids are derived from the canonical name, so a topic that comes back is
        stored under the same id again.
        """
        return 0

    @abstractmethod
    async def save_clusters(self, clusters: List[TopicCluster]) -> None:
        """Upsert topic clusters and their metadata."""
        pass

    @abstractmethod
    async def get_top_clusters(
        self, 
        geo: GeoCode = GeoCode.VN, 
        timeframe: Timeframe = Timeframe.LAST_24H, 
        limit: int = 10
    ) -> List[TopicCluster]:
        """Query top topic clusters ordered by momentum score."""
        pass

    @abstractmethod
    async def get_cluster_signals(
        self, 
        cluster_id: UUID, 
        timeframe: Timeframe = Timeframe.LAST_7D
    ) -> List[TrendSignal]:
        """Retrieve time-series signal history for a given topic cluster."""
        pass

    @abstractmethod
    async def create_mission(self, mission: ResearchMission) -> ResearchMission:
        """Create a new research mission record."""
        pass

    @abstractmethod
    async def save_mission(self, mission: ResearchMission) -> ResearchMission:
        """Upsert a research mission record."""
        pass

    @abstractmethod
    async def get_mission(self, mission_id: UUID) -> Optional[ResearchMission]:
        """Retrieve research mission details by UUID, shortcode, or session ID."""
        pass

    @abstractmethod
    async def update_mission(self, mission: ResearchMission) -> None:
        """Update research mission status, summary, and metadata."""
        pass

    @abstractmethod
    async def list_missions(self, limit: int = 20) -> List[ResearchMission]:
        """List the most recent research missions."""
        pass

    @abstractmethod
    async def get_mission_signals(self, mission_id: UUID) -> List[TrendSignal]:
        """Retrieve all multi-platform signals captured for a research mission."""
        pass

    @abstractmethod
    async def delete_mission_signals(self, mission_id: UUID) -> int:
        """Withdraw a mission's claims before a new targeted run.

        The name predates the model. Sources and observations are shared with every other
        mission that observed them, so only the association rows go.
        """
        pass

    @abstractmethod
    async def assign_observation_clusters(self, signals: List[TrendSignal]) -> int:
        """Set the cluster on observations that were already written.

        For any path that clusters after persisting. Putting the signals back through
        save_signals would record each of them as a second collection event.
        """
        pass

    @abstractmethod
    async def prune_mission_evidence(self, mission_id: UUID, retained_observation_ids) -> int:
        """Drop this mission's claims on anything outside the set it now stands on.

        Called after the new evidence is written, so a pass that fails earlier leaves the
        mission holding what it already had. Passing an empty set withdraws everything, which is
        what a pass that collected nothing means.
        """
        pass

    @abstractmethod
    async def attach_mission_evidence(self, mission_id: UUID, signals: List[TrendSignal]) -> int:
        """Record that a mission used observations that already exist.

        For the quota fallback: a mission keeps the evidence it had when a connector returns
        nothing, without the harness claiming to have polled a platform it could not reach.
        """
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
        """Record system diagnostic events and connector failures to the database."""
        pass

    @abstractmethod
    async def get_recent_logs(
        self,
        level: Optional[str] = None,
        component: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Query recent system audit logs with optional filtering."""
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
        """Save or update platform authentication tokens / session cookies."""
        pass

    @abstractmethod
    async def get_platform_credentials(self, platform: str) -> Optional[PlatformCredentialRecord]:
        """Retrieve active authentication credentials for a given platform."""
        pass

    @abstractmethod
    async def list_platform_credentials(self) -> List[PlatformCredentialSummary]:
        """List connected authentication sessions across all platforms."""
        pass

    @abstractmethod
    async def delete_platform_credentials(self, platform: str) -> bool:
        """Permanently delete locally stored credential or session data for a platform.

        This does not revoke access at the upstream provider. Implementations must remove the
        stored row rather than deactivate it, so no encrypted payload is retained, and must
        return False when there was nothing to delete.
        """
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

    @abstractmethod
    async def get_runtime_config(self, key: str) -> Optional[str]:
        """Retrieve dynamic runtime configuration value by key."""
        pass

    @abstractmethod
    async def get_all_runtime_configs(self, category: Optional[str] = None) -> List[Dict[str, Any]]:
        """Retrieve all stored runtime configurations, optionally filtered by category."""
        pass

    @abstractmethod
    async def set_runtime_config(
        self,
        key: str,
        value: str,
        category: str = "connector",
        description: Optional[str] = None,
        updated_by: str = "system",
    ) -> None:
        """Upsert dynamic runtime configuration parameter."""
        pass

    @abstractmethod
    async def delete_runtime_config(self, key: str) -> bool:
        """Delete a dynamic runtime configuration parameter."""
        pass



