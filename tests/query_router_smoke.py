"""Verify that the unified MCP gateway routes every query to one custom source."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import web_search


def main() -> None:
    original_knowledge = web_search.knowledge_search
    original_web = web_search.web_search
    calls: list[tuple[str, str]] = []

    def fake_knowledge(query: str) -> dict:
        calls.append(("knowledge", query))
        return {"success": True, "result": [{"title": "private paper"}]}

    def fake_web(query: str) -> dict:
        calls.append(("web", query))
        return {"success": True, "result": [{"title": "web page"}]}

    try:
        web_search.knowledge_search = fake_knowledge
        web_search.web_search = fake_web
        private_result = web_search.query_information("郭雷院士关于自适应控制有哪些论文？")
        web_result = web_search.query_information("今天北京有什么重要新闻？")
        forced_result = web_search.query_information("解释一个一般概念", source="knowledge")

        assert private_result["route"] == "knowledge"
        assert private_result["data_source"] == "private_guolei_knowledge_base"
        assert web_result["route"] == "web"
        assert web_result["data_source"] == "user_tavily_web_search"
        assert forced_result["route"] == "knowledge"
        assert calls == [
            ("knowledge", "郭雷院士关于自适应控制有哪些论文？"),
            ("web", "今天北京有什么重要新闻？"),
            ("knowledge", "解释一个一般概念"),
        ]
    finally:
        web_search.knowledge_search = original_knowledge
        web_search.web_search = original_web

    print("QUERY_ROUTER_OK")


if __name__ == "__main__":
    main()
