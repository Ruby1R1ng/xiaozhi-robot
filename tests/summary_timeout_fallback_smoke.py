import sys
import tempfile
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import web_search


class FakeTavilyClient:
    def search(self, **kwargs):
        return {
            "results": [
                {
                    "title": "来源一",
                    "url": "https://example.com/one",
                    "content": "这是模型超时时需要立即返回的网页检索摘录。",
                    "score": 0.9,
                }
            ],
            "usage": {"credits": 1},
            "request_id": "fallback-test",
            "response_time": 0.1,
        }


class TimeoutSummaryClient:
    def post(self, *args, **kwargs):
        raise httpx.ReadTimeout("test timeout")


with tempfile.TemporaryDirectory() as temporary_directory:
    web_search.usage_store = web_search.UsageStore(
        Path(temporary_directory) / "usage.sqlite3"
    )
    web_search._client = FakeTavilyClient()
    web_search._summary_client = TimeoutSummaryClient()

    first = web_search.web_search("测试快速降级")
    time.sleep(0.05)
    second = web_search.web_search("测试快速降级")

    assert first["success"] is True
    assert first["summary_model"] == "extractive-fast-fallback"
    assert "网页检索摘录" in first["summary"]
    assert second["cached"] is True
    assert second["summary_status"] == "background_failed"
    assert second["summary_warning"]

print("SUMMARY_TIMEOUT_FALLBACK_OK")
