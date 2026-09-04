"""Installed-corpus benchmark and actual MCP requests, without changing live config."""
import asyncio,json,os,sys,time,statistics
from pathlib import Path
from dotenv import load_dotenv
load_dotenv('/etc/xiaozhi-search.env')
sys.path.insert(0,'/opt/xiaozhi-search')
os.environ['KNOWLEDGE_DB_PATH']='/opt/xiaozhi-search/data/guolei/knowledge.sqlite3'
os.environ['TAVILY_USAGE_DB']='/var/lib/xiaozhi-search/usage.sqlite3'
import web_search as w
from mcp import ClientSession,StdioServerParameters
from mcp.client.stdio import stdio_client

async def main():
 results=[]
 for q in ['二分之三加根号二','Xie–Guo constant','谢–郭常数','3/2+sqrt(2)','郭雷的3/2+√2常数是什么','How much uncertainty can be dealt with by feedback?']:
  elapsed=[]
  for i in range(5):
   start=time.perf_counter();r=await w.query_information(q);elapsed.append(time.perf_counter()-start)
   assert r['success'] and r['evidence_status']=='verified' and r['route']=='knowledge'
   assert r['result'][0]['printed_page']==2205
   assert '等于' in r['summary']
  results.append({'query':q,'median':statistics.median(elapsed),'max':max(elapsed),'summary':r['summary']})
 params=StdioServerParameters(command=sys.executable,args=['/opt/xiaozhi-search/web_search.py'],env=os.environ.copy(),cwd='/opt/xiaozhi-search')
 async with stdio_client(params) as (read,write):
  async with ClientSession(read,write) as session:
   await session.initialize()
   start=time.perf_counter();res=await session.call_tool('query_information',{'query_text':'二分之三加根号二是什么常数'})
   p=res.structuredContent
   assert p['success'] and p['evidence_status']=='verified'
   print('MCP',json.dumps({'elapsed':time.perf_counter()-start,'payload':p},ensure_ascii=False))
 print('BENCHMARK',json.dumps(results,ensure_ascii=False))
 for q in ['郭雷自适应控制有哪些研究','郭雷关于量子引力的1234567常数是什么']:
  start=time.perf_counter();r=await w.query_information(q)
  print('GENERAL',json.dumps({'query':q,'elapsed':time.perf_counter()-start,'success':r.get('success'),'status':r.get('evidence_status'),'route':r.get('route'),'supplement':r.get('web_supplement_status'),'timing':r.get('timing_seconds')},ensure_ascii=False))
 Path('/tmp/formula-repair/benchmark.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
asyncio.run(main())
