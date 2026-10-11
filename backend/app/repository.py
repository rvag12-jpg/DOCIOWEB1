import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from app.core.config import settings

DATABASE_URL = os.getenv('DATABASE_URL', '').strip()
DB_PATH = settings.data_dir / 'docioweb1.sqlite3'
LEGACY_PATH = settings.data_dir / 'docio.json'
COLLECTIONS = ('groups', 'students', 'assessments', 'corrections', 'knowledge', 'criteria', 'relations')
POSTGRES = DATABASE_URL.startswith(('postgres://', 'postgresql://'))
DEMO_MODE = settings.demo_mode


def tables():
    # Fixed identifiers, never influenced by HTTP input. Demo data has its own tables.
    return ('demo_records', 'demo_audit') if DEMO_MODE else ('records', 'audit')


def now():
    return datetime.now(timezone.utc).isoformat()


def ph(sql):
    return sql.replace('?', '%s') if POSTGRES else sql


@contextmanager
def conn():
    if POSTGRES:
        import psycopg
        connection = psycopg.connect(DATABASE_URL, autocommit=False, connect_timeout=10)
    else:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(DB_PATH)
        connection.row_factory = sqlite3.Row
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def rowget(row, key, index):
    try:
        return row[key]
    except (TypeError, KeyError, IndexError):
        return row[index]


def init_db():
    records, audit = tables()
    with conn() as connection:
        cursor = connection.cursor()
        cursor.execute(f'CREATE TABLE IF NOT EXISTS {records}(collection TEXT NOT NULL, record_key TEXT NOT NULL, data TEXT NOT NULL, updated_at TEXT NOT NULL, PRIMARY KEY(collection,record_key))')
        audit_id = 'BIGSERIAL PRIMARY KEY' if POSTGRES else 'INTEGER PRIMARY KEY AUTOINCREMENT'
        cursor.execute(f'CREATE TABLE IF NOT EXISTS {audit}(id {audit_id}, ts TEXT NOT NULL, action TEXT NOT NULL, collection TEXT NOT NULL, record_key TEXT NOT NULL, before_data TEXT, after_data TEXT)')
        cursor.execute(f'SELECT COUNT(*) FROM {records}')
        count = rowget(cursor.fetchone(), 'count', 0)
        if count == 0 and DEMO_MODE:
            from app.services.demo_data import dataset
            for collection, rows in dataset().items():
                for row in rows:
                    _put(connection, collection, key_for(collection, row), row, 'demo-seed')
        elif count == 0 and LEGACY_PATH.exists():
            legacy = json.loads(LEGACY_PATH.read_text(encoding='utf-8'))
            for collection in COLLECTIONS:
                for index, row in enumerate(legacy.get(collection, [])):
                    _put(connection, collection, key_for(collection, row, index), row, 'migrate')


def key_for(collection, row, index=0):
    fields = {'groups': 'group_id', 'students': 'student_id', 'assessments': 'assessment_id',
              'knowledge': 'knowledge_id', 'criteria': 'criterion_id', 'ai_jobs':'job_id'}
    if collection in fields:
        return str(row.get(fields[collection], index))
    if collection == 'relations':
        return f"{row.get('knowledge_id')}::{row.get('criterion_id')}"
    if collection == 'corrections':
        return f"{row.get('assessment_id')}::{row.get('student_id')}"
    return str(index)


def _put(connection, collection, key, row, action='upsert'):
    records, audit = tables()
    cursor = connection.cursor()
    cursor.execute(ph(f'SELECT data FROM {records} WHERE collection=? AND record_key=?'), (collection, key))
    old = cursor.fetchone()
    before = rowget(old, 'data', 0) if old else None
    after = json.dumps(row, ensure_ascii=False)
    cursor.execute(ph(f'INSERT INTO {records}(collection,record_key,data,updated_at) VALUES(?,?,?,?) ON CONFLICT(collection,record_key) DO UPDATE SET data=excluded.data,updated_at=excluded.updated_at'), (collection, key, after, now()))
    cursor.execute(ph(f'INSERT INTO {audit}(ts,action,collection,record_key,before_data,after_data) VALUES(?,?,?,?,?,?)'), (now(), action, collection, key, before, after))


def _state(connection):
    records, _ = tables()
    out = {name: [] for name in COLLECTIONS}
    cursor = connection.cursor()
    cursor.execute(f"SELECT collection,data FROM {records} WHERE collection!='ai_jobs' ORDER BY collection,record_key")
    for row in cursor.fetchall():
        out[rowget(row, 'collection', 0)].append(json.loads(rowget(row, 'data', 1)))
    return out


def state():
    init_db()
    with conn() as connection:
        return _state(connection)


@contextmanager
def atomic():
    """Short write transaction; external API calls must stay outside this lock."""
    init_db()
    with conn() as connection:
        records, _ = tables()
        connection.cursor().execute(f'LOCK TABLE {records} IN SHARE ROW EXCLUSIVE MODE' if POSTGRES else 'BEGIN IMMEDIATE')
        yield connection


def _get(connection, collection, key):
    records,_=tables()
    cursor=connection.cursor()
    cursor.execute(ph(f'SELECT data FROM {records} WHERE collection=? AND record_key=?'),(collection,key))
    row=cursor.fetchone()
    return json.loads(rowget(row,'data',0)) if row else None


def get_record(collection,key):
    init_db()
    with conn() as connection:
        return _get(connection,collection,key)


def list_records(collection,limit=50):
    init_db()
    records,_=tables()
    with conn() as connection:
        cursor=connection.cursor()
        cursor.execute(ph(f'SELECT data FROM {records} WHERE collection=? ORDER BY updated_at DESC LIMIT ?'),(collection,limit))
        return [json.loads(rowget(row,'data',0)) for row in cursor.fetchall()]


def import_corrections(prepare):
    """Validate, check the preview and write the batch under one write lock."""
    with atomic() as connection:
        rows, report = prepare(_state(connection))
        for row in rows:
            _put(connection, 'corrections', key_for('corrections', row), row, 'import')
    return {**report, 'imported': len(rows)}


def put(collection, row, action='upsert'):
    init_db()
    with conn() as connection:
        _put(connection, collection, key_for(collection, row), row, action)
    return row


def remove(collection, key):
    init_db()
    records, audit = tables()
    with conn() as connection:
        cursor = connection.cursor()
        cursor.execute(ph(f'SELECT data FROM {records} WHERE collection=? AND record_key=?'), (collection, key))
        old = cursor.fetchone()
        if not old:
            return False
        cursor.execute(ph(f'DELETE FROM {records} WHERE collection=? AND record_key=?'), (collection, key))
        cursor.execute(ph(f'INSERT INTO {audit}(ts,action,collection,record_key,before_data,after_data) VALUES(?,?,?,?,?,NULL)'), (now(), 'delete', collection, key, rowget(old, 'data', 0)))
    return True


def history(limit=100):
    init_db()
    _, audit = tables()
    columns = ['id', 'ts', 'action', 'collection', 'record_key', 'before_data', 'after_data']
    with conn() as connection:
        cursor = connection.cursor()
        cursor.execute(ph(f'SELECT id,ts,action,collection,record_key,before_data,after_data FROM {audit} ORDER BY id DESC LIMIT ?'), (limit,))
        return [dict(zip(columns, row)) for row in cursor.fetchall()]


def backend():
    return 'postgresql' if POSTGRES else 'sqlite'


def counts():
    init_db()
    records, _ = tables()
    result = {name: 0 for name in COLLECTIONS}
    with conn() as connection:
        cursor = connection.cursor()
        cursor.execute(f'SELECT collection,COUNT(*) FROM {records} GROUP BY collection')
        for row in cursor.fetchall():
            collection=rowget(row,'collection',0)
            if collection in result:
                result[collection] = rowget(row, 'count', 1)
    return result
