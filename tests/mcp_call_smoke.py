import asyncio
import json
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main() -> None:
    query = sys.argv[1] if len(sys.argv) > 1 else "Tavily 官方文档"
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["/opt/xiaozhi-search/web_search.py"],
        cwd="/opt/xiaozhi-search",
        env=os.environ.copy(),
    )
    async with stdio_client(parameters) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            tools = await session.list_tools()
            tool = next(item for item in tools.tools if item.name == "web_search")
            response = await session.call_tool(
                "web_search",
                {"query_text": query},
            )
            structured = getattr(response, "structuredContent", None) or {}
            error_text = ""
            if response.isError:
                error_text = " ".join(
                    str(getattr(item, "text", "")) for item in response.content
                )[:1000]
            print(
                json.dumps(
                    {
                        "tool_name": tool.name,
                        "tool_title": tool.title,
                        "input_schema": tool.inputSchema,
                        "is_error": bool(response.isError),
                        "content_types": [item.type for item in response.content],
                        "structured_success": structured.get("success"),
                        "cached": structured.get("cached"),
                        "summary_model": structured.get("summary_model"),
                        "summary_preview": str(structured.get("summary") or "")[:160],
                        "source_count": len(structured.get("sources") or []),
                        "model_usage": structured.get("model_usage"),
                        "timing_seconds": structured.get("timing_seconds"),
                        "error_text": error_text,
                    },
                    ensure_ascii=False,
                )
            )


if __name__ == "__main__":
    asyncio.run(main())
