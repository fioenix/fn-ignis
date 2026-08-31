# Implementation Plan: Core TimescaleDB Storage & Stable Ingress Feeds

**Feature Directory**: `specs/001-core-storage-stable-ingress`
**Date**: 2026-08-31
**Spec**: [spec.md](./spec.md)

---

## Summary

Triển khai tầng Core Storage (Postgres + TimescaleDB Hypertable) và 2 Ingress Connectors ổn định (Google Trends RSS & YouTube Data API v3) cho `fn-ignis` theo chuẩn Clean Architecture (Ports & Adapters) và Zero-Token Ingress.

---

## Technical Context

- **Language & Runtime**: Python >= 3.11, Pydantic v2, pydantic-settings
- **Database**: PostgreSQL 16 + TimescaleDB extension + pgvector extension
- **Database Driver**: `psycopg` (v3) + `psycopg-pool` (`AsyncConnectionPool`)
- **Ingress HTTP & Feeds**: `httpx` (async), `feedparser`
- **Testing**: `pytest`, `pytest-asyncio`
- **Constraints**:
  - Truy vấn Time-series & Top clusters: P95 < 50ms
  - Zero-Token Ingress: 0 LLM Tokens trong toàn bộ Ingress flow
  - Lỗi từ một plugin bị cách ly hoàn toàn qua Circuit Breaker

---

## Constitution Check

| Principle | Status | How It Is Satisfied |
|---|---|---|
| I. Zero-Token Ingress | PASS | Google Trends RSS & YouTube Data API v3 chạy thuần code trích xuất dữ liệu, không gọi LLM |
| II. Pluggable & Isolated Connectors | PASS | Kế thừa `IConnectorPlugin`, quản lý qua `ConnectorPluginRegistry` kèm `CircuitBreaker` |
| III. Storage-First & Time-Series Rigor | PASS | Bảng `trend_signals` là TimescaleDB hypertable, lưu trữ batch, đánh index `(platform, geo_code, captured_at DESC)` |
| IV. Builder Pattern for Artifacts | N/A | Tầng UI Artifacts thuộc Pha tiếp theo |
| V. Simplicity & Type Safety | PASS | Python 3.11+ dataclasses, Pydantic settings, typed SQL queries, không abstraction thừa |

---

## Architecture & Component Design

```text
src/ignis/
├── config.py                                      # Settings (DATABASE_URL, YOUTUBE_API_KEY, pool sizes)
├── domain/
│   ├── entities.py                                # TrendSignal, TopicCluster
│   ├── value_objects.py                           # PlatformType, GeoCode, Timeframe
│   └── exceptions.py                              # RepositoryException, ConnectorException
├── application/
│   ├── ports/
│   │   ├── connector_port.py                      # IConnectorPlugin
│   │   └── repository_port.py                     # ITrendRepository
│   └── use_cases/
│       ├── ingest_trends.py                       # IngestTrendsUseCase
│       └── get_top_clusters.py                    # GetTopClustersUseCase
└── infrastructure/
    ├── persistence/
    │   ├── __init__.py
    │   └── postgres_repository.py                 # PostgresTimescaleRepository (AsyncConnectionPool)
    └── connectors/
        ├── registry.py                            # ConnectorPluginRegistry + CircuitBreaker
        ├── google_trends/
        │   ├── __init__.py
        │   └── rss_plugin.py                      # GoogleTrendsRssPlugin
        └── youtube/
            ├── __init__.py
            └── youtube_plugin.py                  # YouTubeDataPlugin
```

---

## Data Flow & Ingress Sequence

1. **Ingest Execution**: `IngestTrendsUseCase` kích hoạt `ConnectorPluginRegistry.fetch_from_all(geo, timeframe)`.
2. **Parallel Fetching**:
   - `GoogleTrendsRssPlugin` tải XML RSS `https://trends.google.com/trending/rss?geo=VN` qua `httpx`, phân tích qua `feedparser`, chuẩn hóa sang `List[TrendSignal]`.
   - `YouTubeDataPlugin` gọi YouTube Data API v3 `videos.list(chart='mostPopular', regionCode='VN')` qua `httpx`, trích xuất views, likes, tags sang `List[TrendSignal]`.
3. **Circuit Breaking**: Nếu một plugin lỗi hoặc timeout, Circuit Breaker tăng `failure_count`, các plugin khác vẫn hoàn thành nhiệm vụ.
4. **Persistence**: `PostgresTimescaleRepository.save_signals()` thực hiện batch insert vào hypertable `trend_signals`.
