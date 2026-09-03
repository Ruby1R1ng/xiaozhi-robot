import asyncio
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main() -> None:
    project_dir = Path(__file__).resolve().parents[1]
    parameters = StdioServerParameters(
        command=sys.executable,
        args=[str(project_dir / "web_search.py")],
        cwd=str(project_dir),
    )
    async with stdio_client(parameters) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            tools = await session.list_tools()
            names = [tool.name for tool in tools.tools]
            expected = {"web_search", "knowledge_search", "query_information"}
            if set(names) != expected:
                raise RuntimeError(f"Unexpected MCP tools: {names}")
            router = next(tool for tool in tools.tools if tool.name == "query_information")
            if router.title != "每问必查：私库或联网":
                raise RuntimeError(f"Unexpected router title: {router.title}")
            print("MCP_TOOLS_OK=query_information,web_search,knowledge_search")


if __name__ == "__main__":
    asyncio.run(main())
