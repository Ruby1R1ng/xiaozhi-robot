import tempfile
import time
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import web_search


class FakeTavilyClient:
    def __init__(self) -> None:
        self.calls = 0

    def search(self, **kwargs):
        self.calls += 1
        return {
            "answer": "这是 Tavily 快速答案。[1]",
            "results": [
                {
                    "title": "示例来源",
                    "url": "https://example.com/news",
                    "published_date": "2026-08-04",
                    "content": "这是用于测试的网页检索片段。",
                    "score": 0.99,
                }
            ],
            "usage": {"credits": 1},
            "request_id": "search-test",
            "response_time": 0.1,
        }


class FakeResponse:
    def raise_for_status(self) -> None:
        return None

    def json(self):
        return {
            "choices": [{"message": {"content": "这是带来源的总结。[1]"}}],
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 20,
                "total_tokens": 120,
            },
        }


class FakeSummaryClient:
    def __init__(self) -> None:
        self.calls = 0
        self.last_request = None

    def post(self, path, json):
        self.calls += 1
        self.last_request = {"path": path, "json": json}
        return FakeResponse()


with tempfile.TemporaryDirectory() as temporary_directory:
    web_search.usage_store = web_search.UsageStore(
        Path(temporary_directory) / "usage.sqlite3"
    )
    search_client = FakeTavilyClient()
    summary_client = FakeSummaryClient()
    web_search._client = search_client
    web_search._summary_client = summary_client

    first = web_search.web_search("测试 Tavily 到硅基流动的总结链路")

    assert first["success"] is True
    assert first["summary"] == "这是 Tavily 快速答案。[1]"
    assert first["summary_status"] == "siliconflow_processing"
    for _ in range(100):
        completed = web_search.usage_store.get_cached(web_search._cache_key(first["query"]))
        if completed and completed.get("summary_status") == "completed":
            break
        time.sleep(0.01)
    second = web_search.web_search("测试 Tavily 到硅基流动的总结链路")
    assert second["summary"] == "这是带来源的总结。[1]"
    assert second["summary_model"] == "Pro/zai-org/GLM-5.1"
    assert first["sources"][0]["url"] == "https://example.com/news"
    assert "这是用于测试的网页检索片段" in str(summary_client.last_request)
    assert second["cached"] is True
    assert search_client.calls == 1
    assert summary_client.calls == 1

print("SUMMARY_PIPELINE_OK")
