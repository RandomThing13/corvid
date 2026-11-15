"""Explicit new release record. Historical P04 protocol remains immutable."""
import hashlib,json,subprocess,os
from pathlib import Path
from app.build import runtime_hashes,build_id
root=Path(__file__).resolve().parents[1]
def main():
 env={**os.environ,'STOA_ENABLE_PAID_API':'0'}
 commands=[['.venv/bin/python','-m','pytest','-q'],['node','--check','app/static/app.js'],['.tools/bin/uv','tool','run','--offline','--from','modal==1.6.4','--with-requirements','deployment/requirements.txt','--with','httpx==0.28.1','python','-m','unittest','discover','-s','deployment/tests','-v']]
 checks=[]
 env.update(UV_CACHE_DIR='/private/tmp/stoa-modal-cache',UV_TOOL_DIR='/private/tmp/stoa-modal-tools')
 for i,cmd in enumerate(commands):
  r=subprocess.run(cmd,env=env,capture_output=True,text=True)
  path=root/f'reports/corvid-gate-{i}.txt';path.write_text(r.stdout+r.stderr)
  checks.append({'command':cmd,'returncode':r.returncode,'log':str(path.relative_to(root)),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
  if r.returncode:raise RuntimeError('Release gate failed: '+str(cmd))
 hashes=runtime_hashes()
 (root/'deployment/runtime-manifest.json').write_text(json.dumps(hashes,indent=2,sort_keys=True)+'\n')
 release={'release':'Corvid-area-v1','build_id':build_id(),'files':hashes,'checks':checks,'checks_passed':True,'historical_p04_sha256':hashlib.sha256((root/'reports/final-protocol.json').read_bytes()).hexdigest()}
 (root/'reports/corvid-release.json').write_text(json.dumps(release,indent=2)+'\n')
 print(json.dumps({'build_id':release['build_id'],'checks_passed':True}))
if __name__=='__main__':main()
