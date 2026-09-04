import asyncio,json,os,sqlite3,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from formula_evidence import normalize_alias,lookup,relevance

class FormulaTests(unittest.TestCase):
 def test_normalization(self):
  for q in ['二分之三加根号二','二分之三+根号2','3/2＋√2','3/2+sqrt(2)',r'\frac{3}{2}+\sqrt{2}']:
   self.assertEqual(normalize_alias(q),'3/2+sqrt2')
 def test_missing_table(self):
  with tempfile.TemporaryDirectory() as td:
   p=Path(td)/'db.sqlite'; sqlite3.connect(p).close()
   self.assertIsNone(lookup(p,'3/2+√2'))
 def test_gate(self):
  self.assertEqual(relevance('二分之三加根号二',[{'title':'Random paper','excerpt':'unrelated'}])[0],'insufficient')
  self.assertEqual(relevance('自适应控制',[{'title':'adaptive control','excerpt':'feedback'}])[0],'candidate')

class GatewayTests(unittest.IsolatedAsyncioTestCase):
 async def test_verified_fastpath(self):
  import web_search as w
  async def no_web(*args,**kwargs): raise AssertionError('unexpected web')
  with patch.object(w,'knowledge_search',return_value={'success':True,'evidence_status':'verified','summary':'verified','result':[]}),patch.object(w,'resilient_web_search',no_web):
   for q in ['二分之三加根号二','Xie–Guo constant','谢–郭常数']:
    r=await w.query_information(q)
    self.assertEqual(r['route'],'knowledge'); self.assertTrue(r['success'])
 async def test_insufficient_calls_web(self):
  import web_search as w
  async def fake_web(q,store,**kwargs):
   self.assertLessEqual(kwargs['budget_seconds'],4)
   return {'success':True,'data_source':'user_zhipu_web_search','summary':'web','result':[]}
  with patch.object(w,'knowledge_search',return_value={'success':True,'evidence_status':'insufficient','result':[]}),patch.object(w,'resilient_web_search',fake_web):
   r=await w.query_information('郭雷某个未知常数')
   self.assertEqual(r['route'],'web');self.assertEqual(r['data_source'],'user_zhipu_web_search')
 async def test_deadline(self):
  import web_search as w
  async def slow(*args,**kwargs): await asyncio.sleep(1)
  with patch.dict(os.environ,{'KNOWLEDGE_GATEWAY_BUDGET_SECONDS':'0.15'}),patch.object(w,'knowledge_search',return_value={'success':False,'result':[]}),patch.object(w,'resilient_web_search',slow):
   r=await w.query_information('郭雷未知理论')
   self.assertFalse(r['success']);self.assertLess(r['timing_seconds']['gateway_total'],0.3)

if __name__=='__main__':unittest.main()
