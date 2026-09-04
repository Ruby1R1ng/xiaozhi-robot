"""Read-only corpus and retrieval diagnosis."""
import json, sys, sqlite3
from pathlib import Path
from dotenv import load_dotenv
load_dotenv('/etc/xiaozhi-search.env')
sys.path.insert(0,'/opt/xiaozhi-search')
from knowledge_base import KnowledgeBase
db=sqlite3.connect('file:/opt/xiaozhi-search/data/guolei/knowledge.sqlite3?mode=ro',uri=True)
db.row_factory=sqlite3.Row
rows=db.execute("select * from papers where lower(title) like '%how much uncertainty%'").fetchall()
print('PAPERS',json.dumps([dict(r) for r in rows],ensure_ascii=False))
for r in rows:
 if 'how much' in r['title'].lower():
  chunks=db.execute('select id,page_start,section,extraction_method,text from chunks where paper_id=? order by page_start,id',(r['id'],)).fetchall()
  print('TARGET_CHUNKS',json.dumps([dict(c) for c in chunks if c['id']==7120],ensure_ascii=False))
  print('FILE_EXISTS', (Path('/opt/xiaozhi-search/data/guolei')/r['stored_path']).exists(), 'CHUNKS',len(chunks))
for term in ['Xie-Guo','Xie–Guo','谢郭','谢–郭','二分之三']:
 print('ALIAS_COUNT',term,db.execute('select count(*) from chunks where text like ?',('%'+term+'%',)).fetchone()[0])
kb=KnowledgeBase()
for q in ['二分之三加根号二','Xie–Guo constant','谢郭常数','How much uncertainty can be dealt with by feedback?','郭雷院士 二分之三加根号二']:
 r=kb.search(q)
 print('RETRIEVAL',json.dumps({'query':q,'timing':r.get('timing_seconds'),'results':[{k:v for k,v in item.items() if k in ['title','page_start','chunk_id']} for item in r.get('result',[])]},ensure_ascii=False))
