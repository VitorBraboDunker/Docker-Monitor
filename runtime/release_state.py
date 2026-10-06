"""Persistent status, transitions, telemetry exports and exclusion audit."""
import csv, io, json, os, sqlite3, threading, time
from pathlib import Path
ROOT=Path(os.environ.get('DNK_CONFIG','/etc/dunker'))
DB=Path(os.environ.get('DNK_HISTORY',str(ROOT/'history/monitor-history.sqlite3')))
LOCK=threading.RLock()
def connect():
    DB.parent.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(DB,timeout=30);db.row_factory=sqlite3.Row
    db.executescript('''CREATE TABLE IF NOT EXISTS states(id TEXT PRIMARY KEY, data TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS events(ts REAL, category TEXT, id TEXT, action TEXT, data TEXT);
    CREATE TABLE IF NOT EXISTS samples(ts REAL, category TEXT, id TEXT, data TEXT);
    CREATE INDEX IF NOT EXISTS sample_lookup ON samples(category,id,ts);
    CREATE INDEX IF NOT EXISTS event_lookup ON events(category,id,ts);''')
    os.chmod(DB,0o600);return db
def event(category,ident,action,data=None):
    with LOCK,connect() as db:db.execute('INSERT INTO events VALUES(?,?,?,?,?)',(time.time(),category,ident,action,json.dumps(data or {},ensure_ascii=False)))
def reset(ident):
    with LOCK,connect() as db:db.execute('DELETE FROM states WHERE id=?',(ident,))

def previous(ident):
    with LOCK,connect() as db:r=db.execute('SELECT data FROM states WHERE id=?',(ident,)).fetchone()
    return json.loads(r[0]) if r else {}
def save(asset):
    with LOCK,connect() as db:
        old=db.execute('SELECT data FROM states WHERE id=?',(asset['asset_id'],)).fetchone()
        old=json.loads(old[0]) if old else {}
        if old.get('status')!=asset['status']:
            db.execute('INSERT INTO events VALUES(?,?,?,?,?)',(asset['checked_at'],asset['category'],asset['asset_id'],'status',json.dumps(asset,ensure_ascii=False)))
        db.execute('INSERT OR REPLACE INTO states VALUES(?,?)',(asset['asset_id'],json.dumps(asset,ensure_ascii=False)))
        db.execute('INSERT INTO samples VALUES(?,?,?,?)',(asset['checked_at'],asset['category'],asset['asset_id'],json.dumps(asset,ensure_ascii=False)))
def prune():
    with LOCK,connect() as db:db.execute('DELETE FROM samples WHERE ts<?',(time.time()-365*86400,))
def export(category,ident=None):
    # Configuration actions and all state transitions are kept indefinitely.
    with LOCK,connect() as db:
        where='category=?'+(' AND id=?' if ident else '')
        args=(category,ident) if ident else (category,)
        events=[dict(r) for r in db.execute('SELECT * FROM events WHERE '+where+' ORDER BY ts',args)]
        samples=[dict(r) for r in db.execute('SELECT * FROM samples WHERE '+where+' ORDER BY ts',args)]
    for record in events+samples:record['data']=json.loads(record['data'])
    return {'category':category,'asset_id':ident,'retention_days':365,'events':events,'samples':samples}
