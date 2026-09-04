"""Publish existing knowledge DB for a read-only systemd mount, retaining data."""
import datetime,json,os,sqlite3,subprocess
from pathlib import Path

root=Path('/opt/xiaozhi-search')
dbpath=(root/'data/guolei/knowledge.sqlite3').resolve(strict=True)
assert dbpath.is_relative_to((root/'data').resolve())
backup=root/('backup-readonly-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
backup.mkdir(mode=0o700)
subprocess.run(['systemctl','stop','xiaozhi-search'],check=True)
connection=None
try:
 connection=sqlite3.connect(dbpath,timeout=20)
 before={t:connection.execute('SELECT COUNT(*) FROM '+t).fetchone()[0] for t in ['papers','chunks','reviewed_math']}
 original_mode=connection.execute('PRAGMA journal_mode').fetchone()[0]
 snapshot=sqlite3.connect(backup/'knowledge.sqlite3')
 try: connection.backup(snapshot)
 finally: snapshot.close()
 os.chmod(backup/'knowledge.sqlite3',0o600)
 checkpoint=connection.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()
 assert checkpoint[0]==0, ('Checkpoint busy',checkpoint)
 mode=connection.execute('PRAGMA journal_mode=DELETE').fetchone()[0]
 assert mode=='delete',mode
 assert connection.execute('PRAGMA quick_check').fetchone()[0]=='ok'
 after={t:connection.execute('SELECT COUNT(*) FROM '+t).fetchone()[0] for t in before}
 assert before==after,(before,after)
 connection.close();connection=None
 assert not Path(str(dbpath)+'-wal').exists()
 assert not Path(str(dbpath)+'-shm').exists()
 report={'database':str(dbpath),'backup':str(backup),'before_mode':original_mode,
         'after_mode':mode,'counts':after,'quick_check':'ok'}
 (backup/'repair.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
 print(json.dumps(report),flush=True)
finally:
 if connection is not None: connection.close()
 subprocess.run(['systemctl','start','xiaozhi-search'],check=True)
subprocess.run(['systemctl','is-active','--quiet','xiaozhi-search'],check=True)
