"""Ensure future corpus builds persist a sidecar-free readable SQLite mode."""
import sqlite3,sys,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from knowledge_ingest import _connect_writable

with tempfile.TemporaryDirectory() as directory:
 path=Path(directory)/'knowledge.sqlite3'
 db=_connect_writable(path)
 db.execute('create table probe(value integer)')
 db.execute('insert into probe values(173)');db.commit();db.close()
 for _ in range(3):
  db=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)
  assert db.execute('pragma journal_mode').fetchone()[0]=='delete'
  assert db.execute('select value from probe').fetchone()[0]==173
  db.close()
 assert not Path(str(path)+'-wal').exists()
 assert not Path(str(path)+'-shm').exists()
print('READONLY_PUBLICATION_OK')
