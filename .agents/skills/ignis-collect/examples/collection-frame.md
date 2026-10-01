# Collection frame example

A request for one Vietnamese retail question declares Google and YouTube as required surfaces.
The plan records the query, geography, window, permitted authority, and stop condition.

| Surface | State | Meaning for the requester |
|---|---|---|
| Google | `HEALTHY` | Collected observations retain their source and query. |
| YouTube | `AUTH_REQUIRED` | The query was not measured; ask for authority or narrow the task. |
| TikTok | `NOT_REQUESTED` | Outside the declared frame. |

If YouTube later runs the exact declared query and returns no qualifying observation, that completed
outcome may be `EMPTY_NO_DATA`. The frame digest changes when its evidence or outcome changes.
Collection alone does not produce a Market verdict.
