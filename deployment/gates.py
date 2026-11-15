"""Fail closed while P04 is active. Never infer completion from elapsed time."""
from pathlib import Path
import re,json,hashlib

def require_final(root):
    path = Path(root) / 'docs/P04-READY.txt'
    if not path.is_file() or not re.search(r'(?im)^\s*(?:status\s*(?:[:=]\s*)?)?FINAL_COMPLETE\s*$',path.read_text()):
        raise RuntimeError('P04 FINAL_COMPLETE gate has not been observed')

    manifest=json.loads((Path(root)/'deployment/runtime-manifest.json').read_text())
    frozen=json.loads((Path(root)/'reports/final-protocol.json').read_text())
    if __import__('os').getenv('CORVID_RELEASE')=='1':
        release=json.loads((Path(root)/'reports/corvid-release.json').read_text())
        if release.get('checks_passed') is not True:raise RuntimeError('Candidate checks missing')
        if release['historical_p04_sha256']!=hashlib.sha256((Path(root)/'reports/final-protocol.json').read_bytes()).hexdigest():raise RuntimeError('Historical P04 changed')
        for check in release['checks']:
            if check['returncode'] or hashlib.sha256((Path(root)/check['log']).read_bytes()).hexdigest()!=check['sha256']:raise RuntimeError('Candidate checks changed')
        frozen=release
    expected={k:v for k,v in frozen['files'].items() if k.startswith('app/') or k in {'uv.lock','pyproject.toml'}}
    if manifest!=expected:raise RuntimeError('Image does not match P04 protocol')
    for name,sha in manifest.items():
        if hashlib.sha256((Path(root)/name).read_bytes()).hexdigest()!=sha:raise RuntimeError('Frozen file changed: '+name)
