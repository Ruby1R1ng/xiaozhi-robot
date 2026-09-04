import os,sqlite3,sys,subprocess
from pathlib import Path
p=Path('/opt/xiaozhi-search/data/guolei/knowledge.sqlite3')
if '--sandbox' in sys.argv:
 pid=subprocess.check_output(['systemctl','show','xiaozhi-search','--property=MainPID','--value'],text=True).strip()
 code=Path(__file__).read_text()
 subprocess.run(['nsenter','-t',pid,'-m','--','/opt/xiaozhi-search/.venv/bin/python','-c',code],check=True)
 raise SystemExit()
print('UID',os.getuid())
for suffix in ['?mode=ro','?mode=ro&immutable=1']:
 try:
  db=sqlite3.connect('file:'+str(p)+suffix,uri=True)
  print(suffix,db.execute("select count(*) from papers").fetchone(),db.execute('pragma journal_mode').fetchone())
  db.close()
 except Exception as e: print(suffix,type(e).__name__,str(e))
