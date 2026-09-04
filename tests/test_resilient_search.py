import asyncio
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
import httpx
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import resilient_search as module


class Store:
    def __init__(self, allowed=True):
        self.cache = {}; self.used = 0; self.allowed = allowed
    def reserve(self, n):
        if self.allowed: self.used += n
        return self.allowed, self.used
    def refund(self, n): self.used -= n
    def current_usage(self): return self.used
    def get_cached(self, key): return self.cache.get(key)
    def set_cached(self, key, value): self.cache[key] = value


class Tests(unittest.IsolatedAsyncioTestCase):
    async def run_case(self, failure=None, both=False, allowed=True):
        calls = []
        async def handler(request):
            import json
            body = json.loads(request.content)
            calls.append((request.url.host, request.url.path, body))
            zp = request.url.host == 'open.bigmodel.cn'
            searching = request.url.path.endswith(('search', 'web_search'))
            if (both and zp) or (not zp and failure == 'search' and searching):
                return httpx.Response(503)
            if not zp and failure == 'timeout' and searching:
                await asyncio.sleep(1)
            if searching:
                rows = [] if not zp and failure == 'empty' else [{'title':'source', 'url':'https://example.com', 'link':'https://example.com', 'content':'材料'}]
                return httpx.Response(200, json={'search_result' if zp else 'results': rows, 'usage':{'credits':1}})
            if zp:
                self.assertEqual(body['thinking'], {'type':'disabled'})
                self.assertEqual(body['model'], 'glm-5.1')
            else:
                self.assertFalse(body['enable_thinking'])
                self.assertEqual(body['model'], 'zai-org/GLM-5.2')
            if not zp and failure == 'summary': return httpx.Response(429)
            return httpx.Response(200, json={'choices':[{'finish_reason':'length' if not zp and failure=='truncated' else 'stop', 'message':{'content':'' if not zp and failure=='blank' else '回答[1]'}}]})
        store = Store(allowed)
        with patch.dict(os.environ, {'TAVILY_API_KEY':'test', 'SILICONFLOW_API_KEY':'test', 'ZHIPU_API_KEY':'test', 'SILICONFLOW_MODEL':'zai-org/GLM-5.2', 'ZHIPU_MODEL':'glm-5.1', 'PRIMARY_PIPELINE_TIMEOUT_SECONDS':'0.1', 'BACKUP_PIPELINE_TIMEOUT_SECONDS':'0.5'}):
            result = await module.search('测试', store, httpx.MockTransport(handler))
            if result['success']:
                count = len(calls)
                cached = await module.search('测试', store, httpx.MockTransport(handler))
                self.assertTrue(cached['cached']); self.assertEqual(len(calls), count)
        return result, calls, store

    async def test_primary(self):
        r,c,s = await self.run_case()
        self.assertTrue(r['success']); self.assertFalse(r['fallback_used'])
        self.assertEqual(len(c),2); self.assertEqual(s.used,1)
        self.assertFalse(c[0][2]['include_answer'])

    async def test_failovers(self):
        for failure in ['search','summary','empty','blank','truncated','timeout']:
            with self.subTest(failure=failure):
                r,c,s = await self.run_case(failure)
                self.assertTrue(r['success']); self.assertEqual(r['provider'],'zhipu')
                self.assertEqual(r['data_source'],'user_zhipu_web_search')
                self.assertEqual(s.used,1)
                self.assertEqual(c[-2][1],'/api/paas/v4/web_search')

    async def test_budget(self):
        r,c,s=await self.run_case(allowed=False)
        self.assertTrue(r['success']); self.assertTrue(r['fallback_used'])
        self.assertEqual(len(c),2); self.assertEqual(s.used,0)

    async def test_both_fail(self):
        r,c,s=await self.run_case('search',True)
        self.assertFalse(r['success']); self.assertEqual(len(r['failed_attempts']),2)
        self.assertFalse(s.cache)

    async def test_invalid(self):
        for q in ['', 'a'*401]:
            self.assertFalse((await module.search(q,Store()))['success'])

if __name__=='__main__': unittest.main()
