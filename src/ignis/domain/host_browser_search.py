"""Finite source-bound host-search envelopes with explicit measurement missingness."""

from typing import Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationInfo, model_serializer, model_validator

HostSearchSource = Literal["tiktok", "threads"]
HostExtractorVersion = Literal["tiktok-public-grid-v1", "threads-search-top-v1"]


def _version_for_source(source: HostSearchSource) -> HostExtractorVersion:
    return "threads-search-top-v1" if source == "threads" else "tiktok-public-grid-v1"


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
    # Omit the legacy default on serialization to preserve existing TikTok envelopes.
    source: HostSearchSource = "tiktok"
    extractor_version: HostExtractorVersion = "tiktok-public-grid-v1"
    request_id: str
    host_task_ref: str = Field(min_length=1, max_length=128)
    session_ref: str = Field(min_length=1, max_length=128)
    issued_at: AwareDatetime
    expires_at: AwareDatetime
    queries: tuple[HostSearchQuery, ...] = Field(min_length=1, max_length=32)

    @model_serializer(mode="wrap")
    def serialize_legacy_defaults(self, handler):
        data = handler(self)
        if self.source == "tiktok":
            data.pop("source", None)
            data.pop("extractor_version", None)
        return data

    @model_validator(mode="before")
    @classmethod
    def default_source_version(cls, value):
        if isinstance(value, dict) and "extractor_version" not in value and value.get("source") == "threads":
            return {**value, "extractor_version": "threads-search-top-v1"}
        return value

    @model_validator(mode="after")
    def require_source_version(self) -> Self:
        if self.extractor_version != _version_for_source(self.source):
            raise ValueError("Extractor version does not match the request source")
        return self


class CounterMeasurement(HostEnvelope):
    """One displayed browser action count, without inventing an exact aggregate."""

    kind: Literal["likes", "replies", "reposts", "shares"]
    unit: Literal["count"]
    raw_display: str = Field(max_length=64)
    value: int | None = Field(strict=True, ge=0)
    precision: Literal["exact", "rounded", "unknown"]

    @model_validator(mode="after")
    def require_measurement_knownness(self) -> Self:
        if self.precision == "unknown":
            if self.value is not None:
                raise ValueError("Unknown counter precision requires a null value")
        elif self.value is None or not self.raw_display.strip():
            raise ValueError("Known counters require a value and a nonblank raw display")
        return self


class HostPublicRecord(HostEnvelope):
    source_url: str | None = Field(default=None, min_length=1, max_length=2048)
    excerpt: str = Field(min_length=1, max_length=2000)
    published_at: AwareDatetime | None = None
    counters: tuple[CounterMeasurement, ...] = Field(default=(), max_length=4)

    @model_serializer(mode="wrap")
    def serialize_legacy_record(self, handler):
        data = handler(self)
        if not self.counters:
            data.pop("counters", None)
        return data

    @model_validator(mode="after")
    def require_distinct_counter_kinds(self) -> Self:
        if len({counter.kind for counter in self.counters}) != len(self.counters):
            raise ValueError("Each counter kind may appear only once")
        return self


class HostQueryAnswer(HostEnvelope):
    query_id: str
    query: str = Field(min_length=1, max_length=256)
    page_url: str = Field(min_length=1, max_length=2048)
    captured_at: AwareDatetime
    search_verified: bool = Field(strict=True)
    empty_state_visible: bool = Field(strict=True)
    status: Literal["HEALTHY", "EMPTY_NO_DATA", "DEGRADED"]
    records: tuple[HostPublicRecord, ...] = Field(max_length=100)
    locale: str | None = Field(default=None, max_length=16)

    @model_serializer(mode="wrap")
    def serialize_legacy_locale(self, handler):
        data = handler(self)
        if self.locale is None:
            data.pop("locale", None)
        return data


class HostSearchAnswer(HostEnvelope):
    source: HostSearchSource = "tiktok"
    request_id: str
    host_task_ref: str = Field(min_length=1, max_length=128)
    session_ref: str = Field(min_length=1, max_length=128)
    extractor_version: HostExtractorVersion
    answers: tuple[HostQueryAnswer, ...] = Field(min_length=1, max_length=32)

    @model_serializer(mode="wrap")
    def serialize_legacy_answer(self, handler):
        data = handler(self)
        if self.source == "tiktok":
            data.pop("source", None)
        return data

    @model_validator(mode="after")
    def require_source_version(self, info: ValidationInfo) -> Self:
        if self.extractor_version != _version_for_source(self.source):
            raise ValueError("Extractor version does not match the answer source")
        request = (info.context or {}).get("request")
        if request is not None and (self.source, self.extractor_version) != (request.source, request.extractor_version):
            raise ValueError("Answer source/version does not match the request source")
        return self
