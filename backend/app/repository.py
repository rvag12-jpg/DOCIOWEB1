import json, os, sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from app.core.config import settings

DATABASE_URL=os.getenv('DATABASE_URL','').strip()
DB_PATH=settings.data_dir/'docioweb1.sqlite3'; LEGACY_PATH=settings.data_dir/'docio.json'
COLLECTIONS=('groups','students','assessments','corrections','knowledge','criteria','relations')
POSTGRES=DATABASE_URL.startswith(('postgres://','postgresql://'))

def now(): return datetime.now(timezone.utc).isoformat()
def ph(sql): return sql.replace('?', '%s') if POSTGRES else sql
@contextmanager
def conn():
 if POSTGRES:
  import psycopg
  c=psycopg.connect(DATABASE_URL,autocommit=False)
 else:
  DB_PATH.parent.mkdir(parents=True,exist_ok=True); c=sqlite3.connect(DB_PATH); c.row_factory=sqlite3.Row
 try: yield c; c.commit()
 except Exception: c.rollback(); raise
 finally: c.close()
def rowget(row,key,index):
 try:return row[key]
 except (TypeError,KeyError,IndexError):return row[index]
def init_db():
 with conn() as c:
  cur=c.cursor()
  cur.execute('CREATE TABLE IF NOT EXISTS records(collection TEXT NOT NULL, record_key TEXT NOT NULL, data TEXT NOT NULL, updated_at TEXT NOT NULL, PRIMARY KEY(collection,record_key))')
  cur.execute('CREATE TABLE IF NOT EXISTS audit(id '+('BIGSERIAL' if POSTGRES else 'INTEGER')+' PRIMARY KEY'+('' if POSTGRES else ' AUTOINCREMENT')+', ts TEXT NOT NULL, action TEXT NOT NULL, collection TEXT NOT NULL, record_key TEXT NOT NULL, before_data TEXT, after_data TEXT)')
  cur.execute('SELECT COUNT(*) FROM records'); n=rowget(cur.fetchone(),'count',0)
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
 cur=c.cursor(); cur.execute(ph('SELECT data FROM records WHERE collection=? AND record_key=?'),(collection,key)); old=cur.fetchone(); before=rowget(old,'data',0) if old else None; after=json.dumps(row,ensure_ascii=False)
 cur.execute(ph('INSERT INTO records(collection,record_key,data,updated_at) VALUES(?,?,?,?) ON CONFLICT(collection,record_key) DO UPDATE SET data=excluded.data,updated_at=excluded.updated_at'),(collection,key,after,now()))
 cur.execute(ph('INSERT INTO audit(ts,action,collection,record_key,before_data,after_data) VALUES(?,?,?,?,?,?)'),(now(),action,collection,key,before,after))
def state():
 init_db(); out={k:[] for k in COLLECTIONS}
 with conn() as c:
  cur=c.cursor(); cur.execute('SELECT collection,data FROM records ORDER BY collection,record_key')
  for r in cur.fetchall(): out[rowget(r,'collection',0)].append(json.loads(rowget(r,'data',1)))
 return out
def put(collection,row,action='upsert'):
 init_db(); key=key_for(collection,row)
 with conn() as c:_put(c,collection,key,row,action)
 return row
def remove(collection,key):
 init_db()
 with conn() as c:
  cur=c.cursor(); cur.execute(ph('SELECT data FROM records WHERE collection=? AND record_key=?'),(collection,key)); old=cur.fetchone()
  if not old:return False
  before=rowget(old,'data',0); cur.execute(ph('DELETE FROM records WHERE collection=? AND record_key=?'),(collection,key)); cur.execute(ph('INSERT INTO audit(ts,action,collection,record_key,before_data,after_data) VALUES(?,?,?,?,?,NULL)'),(now(),'delete',collection,key,before))
 return True
def history(limit=100):
 init_db()
 with conn() as c:
  cur=c.cursor(); cur.execute(ph('SELECT id,ts,action,collection,record_key,before_data,after_data FROM audit ORDER BY id DESC LIMIT ?'),(limit,)); cols=['id','ts','action','collection','record_key','before_data','after_data']; return [{cols[i]:v for i,v in enumerate(r)} for r in cur.fetchall()]
def backend(): return 'postgresql' if POSTGRES else 'sqlite'


def counts():
 init_db(); result={name:0 for name in COLLECTIONS}
 with conn() as c:
  cur=c.cursor(); cur.execute('SELECT collection,COUNT(*) FROM records GROUP BY collection')
  for row in cur.fetchall(): result[rowget(row,'collection',0)]=rowget(row,'count',1)
 return result
