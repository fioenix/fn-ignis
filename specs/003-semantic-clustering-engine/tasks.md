# Tasks: Semantic Clustering Engine

## Phase 1: Port & Clustering Implementation
- [x] T001 Tạo port `IClusteringEngine` trong `src/ignis/application/ports/clustering_port.py`
- [x] T002 [P] Viết unit tests cho `SemanticClusterer` trong `tests/unit/test_semantic_clusterer.py`
- [x] T003 Cài đặt `SemanticClusterer` trong `src/ignis/infrastructure/clustering/semantic_clusterer.py`

## Phase 2: Cluster Signals Use Case
- [x] T004 [P] Viết unit tests cho `ClusterSignalsUseCase` trong `tests/unit/test_cluster_signals_use_case.py`
- [x] T005 Cài đặt `ClusterSignalsUseCase` trong `src/ignis/application/use_cases/cluster_signals.py`

## Phase 3: As-Built Observation-Aware Scoring (2026-09-13)

- [x] T006 Centralize score calculation in `src/ignis/domain/cross_platform_score.py`
- [x] T007 Select one latest observation per `(cluster_id, source_id)` in both repository readers
- [x] T008 Exclude non-exact clocks from windowed scoring without substituting publication time
- [x] T009 Persist cluster membership by updating recorded observations; keep `save_clusters()`
  free of source/observation writes
- [x] T010 Add dual-backend contracts for repeated polling, multi-cluster membership, provenance
  filtering, and deterministic tie-breaking
