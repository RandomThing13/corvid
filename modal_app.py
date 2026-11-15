"""CPU-only Stoa deployment. Deploy only with --strategy recreate."""
from pathlib import Path
import os
import modal

ROOT = Path(__file__).resolve().parent
APP_NAME = 'corvid-public-demo'
VOLUME_NAME = 'corvid-public-data-v2'
SECRET_NAME = 'corvid-public-runtime-access'
SAMPLES = ('site1000_bldg2082_floor9385.pdf', 'site2293_bldg3380_floor15055.pdf')
volume = modal.Volume.from_name(VOLUME_NAME, create_if_missing=True, version=2)
image = modal.Image.debian_slim(python_version='3.12').pip_install_from_requirements(str(ROOT / 'deployment/requirements.txt'))
image = image.env({'PYTHONPATH': '/srv', 'STOA_DB': '/state/stoa.db', 'STOA_DOCUMENT_ROOT': '/state/documents', 'STOA_ENABLE_PAID_API': '0', 'STOA_BUILD_MANIFEST': '/srv/deployment/runtime-manifest.json'})
# Explicit file allowlist: never mount the checkout or a dataset directory wholesale.
for path in sorted((ROOT / 'app').rglob('*')):
    if path.is_file() and (path.suffix == '.py' or (path.parent == ROOT / 'app/static' and path.suffix in {'.html', '.css', '.js', '.svg'}) or (path.parent == ROOT / 'app/static/examples' and path.name in {*SAMPLES, 'LICENSE.md'})):
        if path.is_symlink():
            raise RuntimeError('Symlink in image allowlist')
        image = image.add_local_file(path, '/srv/app/' + path.relative_to(ROOT / 'app').as_posix())
for name in ('runtime.py', 'ledger.py', 'sample-guide.html', 'runtime-manifest.json'):
    image = image.add_local_file(ROOT / 'deployment' / name, '/srv/deployment/' + name)
source = ROOT / 'data/raw/junction-dataset-preview/data/swiss_dwellings'
for name in (*SAMPLES, 'LICENSE.md'):
    image = image.add_local_file(source / name, '/srv/samples/' + name)
paid = os.getenv('STOA_CLOUD_PAID') == '1'
if paid:
    from deployment.gates import require_final
    require_final(ROOT)
app = modal.App(APP_NAME)

@app.function(image=image, cpu=1, memory=2048, max_containers=1,
              timeout=180, scaledown_window=60, volumes={'/state': volume},
              secrets=[modal.Secret.from_name(SECRET_NAME)] if paid else [],
              include_source=False, serialized=True)
@modal.asgi_app()
def web():
    # Secret flags may enable paid access only in an explicitly gated deployment.
    if paid:
        if not os.environ.get('OPENAI_API_KEY') or os.environ.get('STOA_API_BALANCE_VERIFIED') != '1':
            raise RuntimeError('Scoped runtime secret missing verified access')
        os.environ['STOA_ENABLE_PAID_API'] = '1'
    else:
        os.environ['STOA_ENABLE_PAID_API'] = '0'
    from deployment.runtime import create_app
    return create_app(volume.commit)
