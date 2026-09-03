import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import web_search


query = "Tavily 官方搜索接口快速响应架构验证 20260804-1640"
started = time.monotonic()
first = web_search.web_search(query)
first_elapsed = time.monotonic() - started

completed = None
deadline = time.monotonic() + 25
while time.monotonic() < deadline:
    candidate = web_search.usage_store.get_cached(web_search._cache_key(query))
    if candidate and candidate.get("summary_status") in {
        "completed",
        "background_failed",
    }:
        completed = candidate
        break
    time.sleep(0.25)

print(
    json.dumps(
        {
            "first_success": first.get("success"),
            "first_elapsed_seconds": round(first_elapsed, 2),
            "first_summary_model": first.get("summary_model"),
            "first_status": first.get("summary_status"),
            "first_sources": len(first.get("sources") or []),
            "background_status": (completed or {}).get("summary_status"),
            "background_model": (completed or {}).get("summary_model"),
            "background_timing": (completed or {}).get("timing_seconds"),
        },
        ensure_ascii=False,
    )
)
