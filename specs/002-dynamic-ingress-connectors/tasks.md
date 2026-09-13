# Tasks: Dynamic Ingress Connectors

## Phase 1: TikTok Plugin
- [x] T001 [P] Viết unit tests cho `TikTokPlugin` trong `tests/unit/test_tiktok_plugin.py`
- [x] T002 Cài đặt `TikTokPlugin` trong `src/ignis/infrastructure/connectors/tiktok/tiktok_plugin.py`

## Phase 2: Threads Plugin
- [x] T003 [P] Viết unit tests cho `ThreadsPlugin` trong `tests/unit/test_threads_plugin.py`
- [x] T004 Cài đặt `ThreadsPlugin` trong `src/ignis/infrastructure/connectors/threads/threads_plugin.py`

## Phase 3: Instagram Reels Plugin
- [x] T005 [P] Viết unit tests cho `ReelsPlugin` trong `tests/unit/test_reels_plugin.py`
- [x] T006 Cài đặt `ReelsPlugin` trong `src/ignis/infrastructure/connectors/reels/reels_plugin.py`

## Phase 4: Integration & Registry Update
- [x] T007 Cập nhật integration tests và đăng ký 3 plugins vào `tests/integration/test_all_connectors.py`

## Phase 5: As-Built Identity Contract (2026-09-13)

- [x] T008 Route connector sightings through the shared platform-object identity resolver
- [x] T009 Converge TikTok tag/video and Google keyword identities across metadata and URL routes
- [ ] T010 Reconcile Threads/Reels numeric primary keys with permalink shortcodes after connectors
  expose both values or an explicit alias ledger is designed
