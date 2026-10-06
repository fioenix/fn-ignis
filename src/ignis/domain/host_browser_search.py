"""Finite host-search envelopes with explicit measurement missingness."""

from typing import Literal
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class HostEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class HostSearchQuery(HostEnvelope):
    query_id: str
    query: str = Field(min_length=1, max_length=256)
    search_url: str
    result_limit: int = Field(ge=1, le=100, strict=True)


class HostSearchRequest(HostEnvelope):
    protocol_version: Literal[1] = 1
    mode: Literal["TACTICAL", "MISSION"] = "TACTICAL"
    request_id: str
    host_task_ref: str = Field(min_length=1, max_length=128)
    session_ref: str = Field(min_length=1, max_length=128)
    issued_at: AwareDatetime
    expires_at: AwareDatetime
    queries: tuple[HostSearchQuery, ...] = Field(min_length=1, max_length=32)


class HostPublicRecord(HostEnvelope):
    source_url: str = Field(min_length=1, max_length=2048)
    excerpt: str = Field(min_length=1, max_length=2000)
    published_at: AwareDatetime | None = None


class HostQueryAnswer(HostEnvelope):
    query_id: str
    query: str = Field(min_length=1, max_length=256)
    page_url: str = Field(min_length=1, max_length=2048)
    captured_at: AwareDatetime
    search_verified: bool = Field(strict=True)
    empty_state_visible: bool = Field(strict=True)
    status: Literal["HEALTHY", "EMPTY_NO_DATA", "DEGRADED"]
    records: tuple[HostPublicRecord, ...] = Field(max_length=100)


class HostSearchAnswer(HostEnvelope):
    request_id: str
    host_task_ref: str = Field(min_length=1, max_length=128)
    session_ref: str = Field(min_length=1, max_length=128)
    extractor_version: Literal["tiktok-public-grid-v1"]
    answers: tuple[HostQueryAnswer, ...] = Field(min_length=1, max_length=32)
