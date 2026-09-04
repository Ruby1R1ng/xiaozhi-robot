"""Staged smoke: genuine APIs, failure injection only in this test process."""
import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile
from dotenv import load_dotenv
import httpx

load_dotenv('/etc/xiaozhi-search.env')
if '--key-stdin' in sys.argv:
    os.environ['ZHIPU_API_KEY'] = json.loads(sys.stdin.readline())['zhipu']
os.environ['SILICONFLOW_MODEL'] = 'zai-org/GLM-5.2'
os.environ['TAVILY_USAGE_DB'] = '/var/lib/xiaozhi-search/usage.sqlite3'
sys.path.insert(0,'/opt/xiaozhi-search')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import resilient_search
from web_search import usage_store

class Inject(httpx.AsyncBaseTransport):
    def __init__(self, host):
        self.host=host; self.real=httpx.AsyncHTTPTransport()
    async def handle_async_request(self, request):
        if request.url.host==self.host:
            return httpx.Response(503,request=request)
        return await self.real.handle_async_request(request)
    async def aclose(self): await self.real.aclose()

async def main():
    for label,query,host in [
        ('primary','中国科学院数学与系统科学研究院郭雷的研究方向是什么',None),
        ('search_failure','郭雷 反馈 最大能力 临界值','api.tavily.com'),
        ('summary_failure','中科院郭雷院士主要研究什么领域','api.siliconflow.cn')]:
        # Bypass cache without bypassing accounting.
        class NoCache:
            reserve=usage_store.reserve
            refund=usage_store.refund
            current_usage=usage_store.current_usage
            def get_cached(self,key): return None
            def set_cached(self,key,value): pass
        result=await resilient_search.search(query,NoCache(),Inject(host) if host else None)
        print(json.dumps({'test':label,**result},ensure_ascii=False),flush=True)
        assert result['success'], label
        assert result['provider']==('zhipu' if host else 'tavily_siliconflow'), label

if __name__=='__main__': asyncio.run(main())
