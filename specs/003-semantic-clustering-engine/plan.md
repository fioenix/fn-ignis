# Implementation Plan: Semantic Clustering Engine & Cross-Platform Scorer

**Feature Directory**: `specs/003-semantic-clustering-engine`
**Date**: 2026-08-31
**Spec**: [spec.md](./spec.md)

---

## Technical Context

- **Clustering**: Cosine similarity clustering (hoặc Agglomerative / TF-IDF / Embedding)
- **Scoring**: One source-aware implementation: platform bands (40%) + normalized metric volume
  (40%) + average velocity (20%)
- **Target Latency**: Gom cụm < 200ms cho 1000 signals

---

## Structure

```text
src/ignis/
├── domain/
│   └── cross_platform_score.py
├── application/
│   ├── ports/clustering_port.py
│   └── use_cases/cluster_signals.py
└── infrastructure/
    └── clustering/
        └── semantic_clusterer.py
```

## As-built observation contract

- The clusterer and both repository readers call the same domain score function.
- Input aggregation selects one latest observation per canonical source **within each cluster**.
  The deterministic tie-break is latest clock, then larger metric, then larger velocity, then row
  identifier where SQL needs a final stable order.
- Repeated polling in one cluster does not add evidence. A source observed under two clusters still
  contributes once to each; the partition key is `(cluster_id, source_id)`.
- Windowed scoring accepts only `time_provenance=exact_ingestion`. Publication time and unknown
  clocks cannot stand in for ingestion time.
- `first_seen_at` is the earliest exact-ingestion clock in the group and is `NULL` when the group
  contains only legacy observations.
