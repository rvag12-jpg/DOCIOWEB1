import json, sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from app.core.config import settings

DB_PATH=settings.data_dir/'docioweb1.sqlite3'
LEGACY_PATH=settings.data_dir/'docio.json'
COLLECTIONS=('groups','students','assessments','corrections','knowledge','criteria','relations')

def now(): return datetime.now(timezone.utc).isoformat()
@contextmanager
def conn():
 DB_PATH.parent.mkdir(parents=True,exist_ok=True); c=sqlite3.connect(DB_PATH); c.row_factory=sqlite3.Row
 try: yield c; c.commit()
 finally: c.close()
def init_db():
 with conn() as c:
  c.executescript('''CREATE TABLE IF NOT EXISTS records(collection TEXT NOT NULL, record_key TEXT NOT NULL, data TEXT NOT NULL, updated_at TEXT NOT NULL, PRIMARY KEY(collection,record_key)); CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, action TEXT NOT NULL, collection TEXT NOT NULL, record_key TEXT NOT NULL, before_data TEXT, after_data TEXT);''')
  n=c.execute('SELECT COUNT(*) n FROM records').fetchone()['n']
  if n==0 and LEGACY_PATH.exists():
   legacy=json.loads(LEGACY_PATH.read_text(encoding='utf-8'))
   for collection in COLLECTIONS:
    for i,row in enumerate(legacy.get(collection,[])): _put(c,collection,key_for(collection,row,i),row,'migrate')
def key_for(collection,row,index=0):
 fields={'groups':'group_id','students':'student_id','assessments':'assessment_id','knowledge':'knowledge_id','criteria':'criterion_id'}
 if collection in fields:return str(row.get(fields[collection],index))
 if collection=='relations':return f"{row.get('knowledge_id')}::{row.get('criterion_id')}"
 if collection=='corrections':return f"{row.get('assessment_id')}::{row.get('student_id')}"
 return str(index)
def _put(c,collection,key,row,action='upsert'):
 old=c.execute('SELECT data FROM records WHERE collection=? AND record_key=?',(collection,key)).fetchone(); before=old['data'] if old else None; after=json.dumps(row,ensure_ascii=False)
 c.execute('INSERT INTO records(collection,record_key,data,updated_at) VALUES(?,?,?,?) ON CONFLICT(collection,record_key) DO UPDATE SET data=excluded.data,updated_at=excluded.updated_at',(collection,key,after,now()))
 c.execute('INSERT INTO audit(ts,action,collection,record_key,before_data,after_data) VALUES(?,?,?,?,?,?)',(now(),action,collection,key,before,after))
def state():
 init_db(); out={k:[] for k in COLLECTIONS}
 with conn() as c:
  for r in c.execute('SELECT collection,data FROM records ORDER BY collection,record_key'): out[r['collection']].append(json.loads(r['data']))
 return out
def put(collection,row,action='upsert'):
 init_db(); key=key_for(collection,row)
 with conn() as c:_put(c,collection,key,row,action)
 return row
def remove(collection,key):
 init_db()
 with conn() as c:
  old=c.execute('SELECT data FROM records WHERE collection=? AND record_key=?',(collection,key)).fetchone()
  if not old:return False
  c.execute('DELETE FROM records WHERE collection=? AND record_key=?',(collection,key)); c.execute('INSERT INTO audit(ts,action,collection,record_key,before_data,after_data) VALUES(?,?,?,?,?,NULL)',(now(),'delete',collection,key,old['data']))
 return True
def history(limit=100):
 init_db()
 with conn() as c:
  rows=c.execute('SELECT * FROM audit ORDER BY id DESC LIMIT ?',(limit,)).fetchall(); return [dict(r) for r in rows]
