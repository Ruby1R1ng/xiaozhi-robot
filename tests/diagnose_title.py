"""Read-only production title retrieval diagnostic."""
import asyncio,json,os,sqlite3,sys,time
from pathlib import Path
from dotenv import load_dotenv
load_dotenv('/etc/xiaozhi-search.env')
sys.path.insert(0,'/opt/xiaozhi-search')
os.environ['KNOWLEDGE_DB_PATH']='/opt/xiaozhi-search/data/guolei/knowledge.sqlite3'
os.environ['TAVILY_USAGE_DB']='/var/lib/xiaozhi-search/usage.sqlite3'
import web_search as w
from knowledge_base import KnowledgeBase,_fts_query,connect_database
q='Convergence and Logarithm Laws of Self-tuning Regulators'
db=sqlite3.connect('file:'+os.environ['KNOWLEDGE_DB_PATH']+'?mode=ro',uri=True)
db.row_factory=sqlite3.Row
rows=db.execute("select id,sequence,title,year,authors,doi,stored_path,extraction_method from papers where lower(title) like '%logarithm%' or lower(title) like '%self-tuning%'").fetchall()
print('PAPERS',json.dumps([dict(r) for r in rows],ensure_ascii=False))
print('AUTO_ROUTE',w._automatic_route(q),'FTS',_fts_query(q))
kb=KnowledgeBase()
for query in [q,'请介绍论文 '+q,'Convergence and logarithm laws of self-tuning regulators']:
 r=kb.search(query)
 print('KB',json.dumps({'query':query,'success':r.get('success'),'status':r.get('evidence_status'),'terms':r.get('relevance_terms'),'timing':r.get('timing_seconds'),'results':[{k:v for k,v in x.items() if k in ['title','year','page_start','chunk_id','excerpt','doi']} for x in r.get('result',[])]},ensure_ascii=False))
db.close()
async def main():
 from mcp import ClientSession,StdioServerParameters
 from mcp.client.stdio import stdio_client
 params=StdioServerParameters(command=sys.executable,args=['/opt/xiaozhi-search/web_search.py'],cwd='/opt/xiaozhi-search',env=os.environ.copy())
 async with stdio_client(params) as (read,write):
  async with ClientSession(read,write) as session:
   await session.initialize()
   start=time.monotonic()
   res=await session.call_tool('query_information',{'query_text':q,'source':'auto'})
   p=res.structuredContent or {}
   print('MCP',json.dumps({'elapsed':time.monotonic()-start,'error':res.isError,'success':p.get('success'),'route':p.get('route'),'evidence_status':p.get('evidence_status'),'summary':p.get('summary'),'first':(p.get('result') or [None])[0]},ensure_ascii=False))
asyncio.run(main())
