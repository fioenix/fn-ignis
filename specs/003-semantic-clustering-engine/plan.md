# Implementation Plan: Semantic Clustering Engine & Cross-Platform Scorer

**Feature Directory**: `specs/003-semantic-clustering-engine`
**Date**: 2026-08-31
**Spec**: [spec.md](./spec.md)

---

## Technical Context

- **Clustering**: Cosine similarity clustering (hoặc Agglomerative / TF-IDF / Embedding)
- **Scoring**: Platform diversity weight (40%) + Metric Volume Normalized (40%) + Velocity (20%)
- **Target Latency**: Gom cụm < 200ms cho 1000 signals

---

## Structure

```text
src/ignis/
├── application/
│   ├── ports/clustering_port.py
│   └── use_cases/cluster_signals.py
└── infrastructure/
    └── clustering/
        └── semantic_clusterer.py
```
