"""Generate hashes only for the P04-validated build-identity hook."""
import json
from pathlib import Path
from app.build import runtime_hashes,build_id

def main():
 root=Path(__file__).resolve().parents[1]
 hashes=runtime_hashes()
 protocol=root/'reports/final-protocol.json'
 if protocol.exists():
  frozen=json.loads(protocol.read_text())
  expected={k:v for k,v in frozen['files'].items() if k.startswith('app/') or k in {'uv.lock','pyproject.toml'}}
  if hashes != expected or build_id()!=frozen['build_id']:raise RuntimeError('Frozen P04 runtime mismatch; do not deploy')
  if frozen['model']!='gpt-6.1-sol' or frozen['reasoning']!='medium' or frozen['mode']!='auto':raise RuntimeError('Unexpected frozen protocol')
 (root/'deployment/runtime-manifest.json').write_text(json.dumps(hashes,indent=2,sort_keys=True)+'\n')
 print(json.dumps({'build_id':build_id(),'files':len(hashes),'manifest':'deployment/runtime-manifest.json'}))
if __name__=='__main__':main()
