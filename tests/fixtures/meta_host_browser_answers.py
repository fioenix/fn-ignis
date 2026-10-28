"""Synthetic source answers and a transport-only double for Spec 020 contracts."""
from datetime import datetime, timezone


class NoSocketRelay:
    url = "http://127.0.0.1:0/synthetic-relay"
    tab_script = "synthetic transport"

    def __init__(self, *args):
        self.closed = False

    def close(self):
        self.closed = True


def host_answer(request, *, empty=False, degraded=False, context=False):
    source = request.get("source", "tiktok")
    answers = []
    for index, query in enumerate(request["queries"]):
        record = dict(source_url=(f"https://www.threads.com/@synthetic.header/post/Synthetic020Q{index}/media"
                                  if source == "threads" else
                                  f"https://www.tiktok.com/@synthetic.header/video/{7417820067028536584 + index}"),
                      excerpt="Synthetic body @synthetic.mention", published_at="2026-10-27T01:02:03.123456Z")
        if context:
            record["source_url"] = None
        if source == "threads":
            record["excerpt"] += " Photo by Synthetic Other Person on October 27"
            record["counters"] = [dict(kind="likes", unit="count", raw_display="1.4K", value=1400, precision="rounded"),
                                  dict(kind="shares", unit="count", raw_display="", value=None, precision="unknown")]
        answer = dict(query_id=query["query_id"], query=query["query"], page_url=query["search_url"],
                      captured_at=datetime.now(timezone.utc).isoformat(), search_verified=not degraded,
                      empty_state_visible=empty, status="DEGRADED" if degraded else "EMPTY_NO_DATA" if empty else "HEALTHY",
                      records=[] if empty or degraded else [record])
        if source == "threads":
            answer["locale"] = "en"
        answers.append(answer)
    result = dict(request_id=request["request_id"], host_task_ref=request["host_task_ref"], session_ref=request["session_ref"],
                  extractor_version=request["extractor_version"], answers=answers)
    if source == "threads":
        result["source"] = source
    return result
