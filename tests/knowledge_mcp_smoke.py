"""Call knowledge_search through the same stdio MCP path used by Xiaozhi."""

import asyncio
import json
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main() -> None:
    project_root = Path(__file__).resolve().parents[1]
    query = sys.argv[1] if len(sys.argv) > 1 else "鲁棒随机自适应控制器的主要工作是什么"
    parameters = StdioServerParameters(
        command=sys.executable,
        args=[str(project_root / "web_search.py")],
        cwd=str(project_root),
        env=os.environ.copy(),
    )
    async with stdio_client(parameters) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            tools = await session.list_tools()
            names = [tool.name for tool in tools.tools]
            response = await session.call_tool("knowledge_search", {"query_text": query})
            structured = getattr(response, "structuredContent", None) or {}
            print(
                json.dumps(
                    {
                        "tools": names,
                        "is_error": bool(response.isError),
                        "success": structured.get("success"),
                        "count": structured.get("count"),
                        "citations": structured.get("citations"),
                        "timing_seconds": structured.get("timing_seconds"),
                        "warning": structured.get("warning"),
                    },
                    ensure_ascii=False,
                )
            )
            if "knowledge_search" not in names or response.isError or not structured.get("success"):
                raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
