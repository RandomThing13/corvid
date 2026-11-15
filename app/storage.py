"""Small single-process SQLite metadata/cache and durable spend ledger."""
import json,sqlite3,os,math
from contextlib import contextmanager
from pathlib import Path
DB=Path(os.environ.get('STOA_DB','data/processed/stoa.db'))
_persistence_callback=lambda:None
def configure_persistence(callback):
 global _persistence_callback
 _persistence_callback=callback if callback is not None else (lambda:None)

@contextmanager
def connection():
 DB.parent.mkdir(parents=True,exist_ok=True)
 c=sqlite3.connect(DB,timeout=30);c.row_factory=sqlite3.Row
 c.executescript('CREATE TABLE IF NOT EXISTS documents(id TEXT PRIMARY KEY, body TEXT); CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY, cache_key TEXT, body TEXT); CREATE TABLE IF NOT EXISTS spend(id TEXT PRIMARY KEY, reserved REAL NOT NULL, charge REAL, details TEXT);')
 try:
  yield c
  c.commit()
 except Exception:
  c.rollback();raise
 finally:c.close()

def put(table,id,body,key=None):
 with connection() as c:
  if table=='runs':c.execute('INSERT OR REPLACE INTO runs VALUES(?,?,?)',(id,key,json.dumps(body)))
  elif table=='documents':c.execute('INSERT OR REPLACE INTO documents VALUES(?,?)',(id,json.dumps(body)))
  else:raise ValueError('Unknown table')
 _persistence_callback()
def get(table,id):
 if table not in ('runs','documents'):raise ValueError('Unknown table')
 with connection() as c:r=c.execute(f'SELECT body FROM {table} WHERE id=?',(id,)).fetchone()
 return json.loads(r[0]) if r else None

def cached(key):
 with connection() as c:r=c.execute('SELECT body FROM runs WHERE cache_key=? ORDER BY rowid LIMIT 1',(key,)).fetchone()
 return json.loads(r[0]) if r else None

def totals():
 with connection() as c:
  r=c.execute('SELECT COALESCE(SUM(charge),0),COALESCE(SUM(CASE WHEN charge IS NULL THEN reserved ELSE 0 END),0) FROM spend').fetchone()
 return {'known_usd':r[0],'unknown_reserved_usd':r[1],'cap_usd':2.0}
def reserve(id,amount,details):
 if not math.isfinite(amount) or amount<=0:raise ValueError('Invalid reservation')
 with connection() as c:
  c.execute('BEGIN IMMEDIATE')
  spent=c.execute('SELECT COALESCE(SUM(COALESCE(charge,reserved)),0) FROM spend').fetchone()[0]
  if spent+amount>2:raise ValueError('budget_exhausted')
  c.execute('INSERT INTO spend VALUES(?,?,NULL,?)',(id,amount,json.dumps(details)))
 _persistence_callback()
def settle(id,charge,details):
 if not math.isfinite(charge) or charge<0:raise ValueError('Invalid charge')
 with connection() as c:c.execute('UPDATE spend SET charge=?,details=? WHERE id=?',(charge,json.dumps(details),id))

 _persistence_callback()
