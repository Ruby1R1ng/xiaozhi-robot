"""Backup current code and database; additive evidence migration and deployment."""
import datetime,os,shutil,sqlite3,subprocess,sys
from pathlib import Path
root=Path('/opt/xiaozhi-search'); stage=Path('/tmp/formula-repair')
backup=root/('backup-formula-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
backup.mkdir(mode=0o700)
files=['web_search.py','knowledge_base.py','resilient_search.py','formula_evidence.py']
for name in files:
 if (root/name).exists(): shutil.copy2(root/name,backup/name)
dbpath=root/'data/guolei/knowledge.sqlite3'
source=sqlite3.connect(dbpath); dest=sqlite3.connect(backup/'knowledge.sqlite3')
source.backup(dest); dest.close();source.close()
try:
 subprocess.run([sys.executable,str(stage/'repair_reviewed_math.py'),str(dbpath)],check=True)
 for name in files:
  shutil.copy2(stage/name,root/name);os.chmod(root/name,0o644)
 subprocess.run(['systemctl','restart','xiaozhi-search'],check=True)
 subprocess.run(['systemctl','is-active','--quiet','xiaozhi-search'],check=True)
except BaseException:
 for name in files:
  if (backup/name).exists(): shutil.copy2(backup/name,root/name)
 # Additive table can stay: old code never queries it; original DB remains intact.
 subprocess.run(['systemctl','restart','xiaozhi-search'])
 raise
print('BACKUP='+str(backup))
