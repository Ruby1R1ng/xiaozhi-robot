"""Live search/cache smoke; background summaries were replaced by awaited failover."""
import asyncio
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import web_search

async def main():
    query = "阿里云轻量应用服务器 官方文档"
    first = await web_search.web_search(query)
    second = await web_search.web_search(query)
    assert first["success"] and first["summary_status"] == "completed"
    assert second["cached"]
    print(json.dumps({"provider": first["provider"], "model": first["summary_model"], "timing": first["timing_seconds"], "cached": second["cached"]}, ensure_ascii=False))

asyncio.run(main())
