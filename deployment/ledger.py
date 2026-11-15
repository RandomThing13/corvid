"""Spend-only transfer, preserving IDs and unknown reservations. No app imports."""
import hashlib
import json
import math
import sqlite3
from pathlib import Path
from contextlib import closing

SCHEMA = 'CREATE TABLE IF NOT EXISTS spend(id TEXT PRIMARY KEY,reserved REAL NOT NULL,charge REAL,details TEXT)'
SAFE = {'model_requested','model','effort','prompt_schema_hash','payload_hash','attempts','input_token_count','reserved_usd','cost_usd','charge_upper_bound_usd','error','error_type','http_status','response_status','service_tier','duration_ms'}

def totals(rows):
    return {'known_usd':sum(r['charge'] for r in rows if r['charge'] is not None),
            'unknown_reserved_usd':sum(r['reserved'] for r in rows if r['charge'] is None), 'cap_usd':2.0}

def validate(data):
    rows = data['rows']
    if len({r['id'] for r in rows}) != len(rows):
        raise ValueError('duplicate_spend_ids')
    for r in rows:
        if not isinstance(r['id'], str) or not r['id'] or not math.isfinite(r['reserved']) or r['reserved'] <= 0:
            raise ValueError('invalid_reservation')
        if r['charge'] is not None and (not math.isfinite(r['charge']) or r['charge'] < 0):
            raise ValueError('invalid_charge')
        if set(r['details']) - SAFE:
            raise ValueError('unsafe_details')
    if totals(rows) != data['totals']:
        raise ValueError('snapshot_totals_mismatch')
    return rows

def export_spend(db):
    with closing(sqlite3.connect(Path(db).resolve().as_uri() + '?mode=ro', uri=True)) as c:
        rows = [{'id':i,'reserved':r,'charge':v,'details':{k:x for k,x in json.loads(d or '{}').items() if k in SAFE and isinstance(x,(str,int,float,bool,type(None)))}}
                for i,r,v,d in c.execute('SELECT id,reserved,charge,details FROM spend ORDER BY id')]
    data={'version':1,'rows':rows,'totals':totals(rows)}
    validate(data)
    return data

def digest(data):
    return hashlib.sha256(json.dumps(data,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()

def seed_empty(db, data, commit):
    rows=validate(data)
    Path(db).parent.mkdir(parents=True,exist_ok=True)
    c=sqlite3.connect(db)
    try:
        c.execute('BEGIN IMMEDIATE')
        c.execute(SCHEMA)
        c.execute('CREATE TABLE IF NOT EXISTS deployment_ledger_import(snapshot_sha256 TEXT PRIMARY KEY, body TEXT NOT NULL)')
        if c.execute('SELECT COUNT(*) FROM spend').fetchone()[0] or c.execute('SELECT COUNT(*) FROM deployment_ledger_import').fetchone()[0]:
            raise ValueError('refuse_nonempty_or_previously_imported_ledger')
        c.executemany('INSERT INTO spend VALUES(?,?,?,?)',[(r['id'],r['reserved'],r['charge'],json.dumps(r['details'])) for r in rows])
        c.execute('INSERT INTO deployment_ledger_import VALUES(?,?)',(digest(data),json.dumps(data)))
        actual=c.execute('SELECT COALESCE(SUM(charge),0),COALESCE(SUM(CASE WHEN charge IS NULL THEN reserved ELSE 0 END),0) FROM spend').fetchone()
        for a,b in zip(actual,(data['totals']['known_usd'],data['totals']['unknown_reserved_usd'])):
            if not math.isclose(a,b,rel_tol=1e-12,abs_tol=1e-12):raise ValueError('import_totals_mismatch')
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()
    # Callback runs after closing SQLite. Failed commit never authorizes paid access.
    commit()
    return {'snapshot_sha256':digest(data),'rows':len(rows),'totals':data['totals']}

def initialized(db):
    if not Path(db).is_file():return False
    try:
        with closing(sqlite3.connect(Path(db).resolve().as_uri()+'?mode=ro',uri=True)) as c:
            marker=c.execute('SELECT body FROM deployment_ledger_import').fetchall()
            if len(marker)!=1:return False
            original=json.loads(marker[0][0])
            for row in validate(original):
                actual=c.execute('SELECT reserved FROM spend WHERE id=?',(row['id'],)).fetchone()
                if actual is None or actual[0]!=row['reserved']:return False
        return True
    except (sqlite3.Error,ValueError,KeyError):return False
