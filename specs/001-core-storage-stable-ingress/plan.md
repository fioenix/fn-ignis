# Implementation Plan: Core TimescaleDB Storage & Stable Ingress Feeds

**Feature Directory**: `specs/001-core-storage-stable-ingress`
**Date**: 2026-08-31
**Spec**: [spec.md](./spec.md)

---

## Summary

Implement dual-backend core storage and stable Google Trends/YouTube ingress under Clean
Architecture. The as-built storage model separates canonical external sources, immutable
observations, and mission evidence; legacy `trend_signals`/`signal_metrics` remain read-only
migration inputs rather than runtime sources of truth.

---

## Technical Context

- **Language & Runtime**: Python >= 3.11, Pydantic v2, pydantic-settings
- **Database**: SQLite default; PostgreSQL 16 with optional TimescaleDB and pgvector
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
| III. Storage-First & Time-Series Rigor | PASS | `sources` enforces canonical identity; `observations` preserves every sighting and its clock provenance; `mission_evidence` preserves the exact evidence ledger on both backends |
| IV. Builder Pattern for Artifacts | N/A | Tầng UI Artifacts thuộc Pha tiếp theo |
| V. Simplicity & Type Safety | PASS | Python 3.11+ dataclasses, Pydantic settings, typed SQL queries, không abstraction thừa |

---

## Architecture & Component Design

```text
src/ignis/
├── config.py                                      # Settings (DATABASE_URL, YOUTUBE_API_KEY, pool sizes)
├── domain/
│   ├── entities.py                                # Observation-shaped TrendSignal, TopicCluster
│   ├── source_identity.py                         # Canonical external-object resolver
│   ├── cross_platform_score.py                    # One score implementation
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
    │   ├── postgres_repository.py                 # PostgreSQL source/observation repository
    │   ├── sqlite_repository.py                   # Zero-config parity implementation
    │   ├── migration_state.py                     # Refuse schema-created/backfill-missing state
    │   └── ../migration/legacy_projection.py      # Shared audit/backfill/verifier projection
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
4. **Persistence**: `save_signals()` resolves each sighting through the canonical identity resolver,
   upserts one `sources` row, inserts one `observations` row, and attaches mission evidence.
5. **Clustering**: cluster rows are saved before observation membership is assigned. Saving a
   cluster never creates another observation.
6. **Reading and scoring**: readers query `observations → sources`; an analysis window accepts only
   `exact_ingestion` observations and selects the latest observation per `(cluster_id, source_id)`.

## Existing PostgreSQL corpus cutover

The runtime must not start in the state where `sql/016` exists but the new tables are empty. The
canonical operating sequence lives in
[`docs/migrations/2026-09-10-source-observation-baseline.md`](../../docs/migrations/2026-09-10-source-observation-baseline.md#production-cutover-runbook):
merge, quiesce, snapshot, generate a fresh baseline from that snapshot, apply `sql/016`, dry-run and
apply the deterministic backfill, obtain `VERIFIED`, then start the new runtime and reopen ingress.
That sequence completed on the existing PostgreSQL corpus on 20/09/2026. The runbook remains the
recovery and repeat-execution contract. Each invocation must create its journal atomically at a
unique path so that a second process can never replace evidence from an earlier run.
