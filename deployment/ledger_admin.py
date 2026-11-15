"""One-shot maintenance app. Stop stoa-evidence before running this, never alongside web."""
from pathlib import Path
import json,subprocess,sys
import modal

root=Path(__file__).resolve().parents[1]
app=modal.App('corvid-public-ledger-maintenance')
volume=modal.Volume.from_name('corvid-public-data-v2',version=2)
image=modal.Image.debian_slim(python_version='3.12').env({'PYTHONPATH':'/srv'}).add_local_file(root/'deployment/ledger.py','/srv/deployment/ledger.py')

@app.function(image=image,cpu=1,memory=2048,max_containers=1,timeout=180,volumes={'/state':volume},include_source=False, serialized=True)
def seed(snapshot):
    from deployment.ledger import seed_empty
    return seed_empty('/state/stoa.db',snapshot,volume.commit)

@app.function(image=image,cpu=1,memory=2048,max_containers=1,timeout=180,
              volumes={'/state':volume.with_mount_options(read_only=True)},include_source=False,serialized=True)
def audit():
    from pathlib import Path
    from deployment.ledger import export_spend,initialized
    db=Path('/state/stoa.db')
    if not db.exists():return {'initialized':False,'totals':None}
    snapshot=export_spend(db)
    import sqlite3,json
    c=sqlite3.connect(db.as_uri()+'?mode=ro',uri=True)
    try:
        import_digest=c.execute('SELECT snapshot_sha256 FROM deployment_ledger_import').fetchone()[0]
        blocked=[]
        for (body,) in c.execute('SELECT body FROM runs ORDER BY rowid DESC LIMIT 1000'):
            a=json.loads(body);m=a.get('metadata',{})
            if 'runtime_access_blocked' in str(a.get('missing_inputs',[])) or m.get('error')=='runtime_access_blocked':blocked.append({'run_id':a['run_id'],'access':m.get('access')})
    finally:c.close()
    return {'initialized':initialized(db),'rows':len(snapshot['rows']),'totals':snapshot['totals'],'recent_blocked_access':blocked[:3],'import_snapshot_sha256':import_digest}

@app.local_entrypoint()
def main(web_stopped: bool = False, inspect_only: bool = False):
    from deployment.gates import require_final
    require_final(root)
    if inspect_only:
        print(audit.remote())
        return
    if not web_stopped:raise RuntimeError('Stop web app and verify zero writers first; then --web-stopped')
    states=json.loads(subprocess.check_output([sys.executable,'-m','modal','app','list','--json'],text=True))
    if any(a.get('description')=='corvid-public-demo' and (a.get('state')!='stopped' or str(a.get('tasks','0'))!='0') for a in states):raise RuntimeError('Web app may still have a writer; import refused')
    snapshot=json.loads((root/'deployment/.env.ledger-transfer.json').read_text())
    print(seed.remote(snapshot))
