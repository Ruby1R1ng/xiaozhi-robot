import logging
import sys
from typing import Any

from mcp.server.fastmcp import FastMCP
from zhipuai import ZhipuAI

from config_manager import load_config


logger = logging.getLogger("web_search")

# Fix UTF-8 encoding for Windows console
if sys.platform == 'win32':
    sys.stderr.reconfigure(encoding='utf-8')
    sys.stdout.reconfigure(encoding='utf-8')

# 创建 MCP 服务
mcp = FastMCP("mcps")


def _result_value(result: Any, field: str) -> str:
    """同时兼容 SDK 对象和字典形式的搜索结果。"""
    if isinstance(result, dict):
        value = result.get(field, "")
    else:
        value = getattr(result, field, "")
    return "" if value is None else str(value)


@mcp.tool()
def 联网查询(query_text: str) -> dict:
    """
    通过智谱 AI Web Search API 进行全网查询。
    适用于新闻、人物、机构、政策、论文、价格和其他需要联网核实的信息。

    :param query_text: 客户端传来的查询文字
    :return: 包含标题、链接、来源、发布日期和摘要的结构化查询结果
    """
    query = query_text.strip()
    if not query:
        return {"success": False, "query": query, "error": "查询内容不能为空", "result": []}

    try:
        config = load_config()
        client = ZhipuAI(api_key=config["ZHIPU_API_KEY"])

        response = client.web_search.web_search(
            search_engine="search_std",
            search_query=query,
            count=15,
            search_recency_filter="noLimit",
            content_size="high",
        )

        raw_results = getattr(response, "search_result", None) or []
        results = [
            {
                "title": _result_value(result, "title"),
                "url": _result_value(result, "link"),
                "source": _result_value(result, "media"),
                "publish_date": _result_value(result, "publish_date"),
                "content": _result_value(result, "content"),
            }
            for result in raw_results
        ]

        logger.info("联网查询完成，查询词=%r，结果数=%d", query, len(results))
        return {
            "success": True,
            "query": query,
            "count": len(results),
            "result": results,
        }
    except Exception as exc:
        logger.exception("联网查询失败，查询词=%r", query)
        return {
            "success": False,
            "query": query,
            "error": f"{type(exc).__name__}: {exc}",
            "result": [],
        }


if __name__ == "__main__":
    mcp.run(transport="stdio")
