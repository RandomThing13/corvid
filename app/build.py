"""Runtime build identity; hashes code/assets only, never evaluation content."""
import hashlib,json,os,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def runtime_hashes():
 files=[p for p in (ROOT/'app').rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix in ('.py','.js','.css','.html','.pdf','.md')]
 manifest_path=os.getenv('STOA_BUILD_MANIFEST')
 if manifest_path:
  expected=json.loads(Path(manifest_path).read_text())
  if not isinstance(expected,dict) or any(not isinstance(v,str) or not re.fullmatch('[0-9a-f]{64}',v) for v in expected.values()):raise ValueError('Invalid build manifest')
  actual={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(files)}
  if {k:v for k,v in expected.items() if k.startswith('app/')}!=actual:raise ValueError('Runtime code/assets differ from build manifest')
  if set(expected)!=set(actual)|{'uv.lock','pyproject.toml'}:raise ValueError('Unexpected build manifest scope')
  for name in ('uv.lock','pyproject.toml'):
   if (ROOT/name).exists() and hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=expected[name]:raise ValueError('Build metadata differs')
  return expected
 files+=[ROOT/'uv.lock',ROOT/'pyproject.toml']
 return {p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(files)}
def build_id():return hashlib.sha256(json.dumps(runtime_hashes(),sort_keys=True).encode()).hexdigest()
