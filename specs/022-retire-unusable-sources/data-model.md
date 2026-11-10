# Data model

No persisted schema changes or migrations.

- **Retired surface**: immutable policy identifiers `google`, `tiktok_creative_center`,
  `tiktok_video_grid`, `reels`. Runtime admission metadata, not a replacement platform enum.
- **MissionManifest**: existing required/optional resources and digest unchanged. Historical
  manifests remain constructible and readable. Creation/execution rejects any retired resource
  with `SURFACE_RETIRED` and its exact name before collection or mission mutation.
- **Watchlist run request**: a request-local reduced resource list. Response gains
  `retired_resources: [{surface, reason_code: SURFACE_RETIRED}]`; a mixed request creates a mission
  for survivors only. An all-retired request is `BLOCKED` and creates no run. Stored versions and
  previous manifests remain untouched.
- **Observation, channel outcome, session**: existing storage/read representation and provenance
  unchanged. Retirement creates no zero metrics, rewrite, deletion or automatic session refresh.
- **Tool catalog**: eleven entries removed; all survivor names and parameter schemas unchanged.
