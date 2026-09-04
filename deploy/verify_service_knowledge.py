"""Test MCP inside live mount namespace, as service UID/GID, using service env."""
import asyncio,json,os,subprocess,sys,time,sqlite3
from pathlib import Path

if '--inside' not in sys.argv:
 pid=subprocess.check_output(['systemctl','show','xiaozhi-search','--property=MainPID','--value'],text=True).strip()
 env=dict(entry.split('=',1) for entry in Path('/proc/'+pid+'/environ').read_bytes().decode().split('\0') if '=' in entry)
 code=Path(__file__).read_text()
 # No credentials on argv or stdout. Inherit the already configured environment.
 subprocess.run(['nsenter','-t',pid,'-m','--','setpriv','--reuid=1000','--regid=1000','--clear-groups',
                 '/opt/xiaozhi-search/.venv/bin/python','-c',code,'--inside'],env=env,check=True)
 raise SystemExit()

from mcp import ClientSession,StdioServerParameters
from mcp.client.stdio import stdio_client
async def main():
 dbpath=Path(os.environ['KNOWLEDGE_DB_PATH'])
 db=sqlite3.connect('file:'+str(dbpath)+'?mode=ro',uri=True)
 print(json.dumps({'uid':os.getuid(),'journal_mode':db.execute('pragma journal_mode').fetchone()[0],
                  'papers':db.execute('select count(*) from papers').fetchone()[0],
                  'wal_exists':Path(str(dbpath)+'-wal').exists(),'shm_exists':Path(str(dbpath)+'-shm').exists()}),flush=True)
 assert db.execute('pragma journal_mode').fetchone()[0]=='delete'
 db.close()
 params=StdioServerParameters(command=sys.executable,args=['/opt/xiaozhi-search/web_search.py'],
                             env=os.environ.copy(),cwd='/opt/xiaozhi-search')
 async with stdio_client(params) as (read,write):
  async with ClientSession(read,write) as session:
   await session.initialize()
   for q in ['Convergence and Logarithm Laws of Self-tuning Regulators','二分之三加根号二','郭雷自适应控制有哪些研究']:
    start=time.monotonic()
    response=await session.call_tool('query_information',{'query_text':q,'source':'auto'})
    p=response.structuredContent or {}
    top=(p.get('result') or [{}])[0]
    record={'query':q,'elapsed':round(time.monotonic()-start,4),'success':p.get('success'),
            'route':p.get('route'),'first_title':top.get('title'),'evidence_status':p.get('evidence_status')}
    print(json.dumps(record,ensure_ascii=False),flush=True)
    assert not response.isError and p.get('success') and p.get('route')=='knowledge',record
    if q.startswith('Convergence'): assert top['title'].casefold()==q.casefold(),record
 assert not Path(str(dbpath)+'-wal').exists()
 assert not Path(str(dbpath)+'-shm').exists()
asyncio.run(main())
