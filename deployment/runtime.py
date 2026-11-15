"""Cloud adapter around the unchanged application."""
import os
from pathlib import Path

def create_app(commit):
    from app import storage, documents, provider
    from app.main import app
    from starlette.responses import JSONResponse, FileResponse
    from deployment.ledger import initialized
    db = Path(os.environ['STOA_DB'])
    root = Path(os.environ['STOA_DOCUMENT_ROOT'])
    if not db.is_absolute() or not root.is_absolute():
        raise RuntimeError('Persistence paths must be absolute')
    storage.DB = db
    documents.ROOT = root
    if not callable(getattr(storage, 'configure_persistence', None)):
        raise RuntimeError('P04 persistence callback is required before cloud startup')
    storage.configure_persistence(commit)
    original_access = provider.access
    def guarded_access():
        flags = original_access()
        flags['paid_enabled'] = flags['paid_enabled'] and initialized(db)
        return flags
    provider.access = guarded_access

    @app.middleware('http')
    async def private_routes(request, call_next):
        path = request.url.path
        if path == '/development' or path.startswith('/development/') or path in {'/docs','/redoc','/openapi.json','/debug'} or path.startswith('/docs/') or path.startswith('/redoc/') or path.startswith('/debug/'):
            return JSONResponse({'detail':'not_found'}, status_code=404)
        response = await call_next(request)
        # Flush filesystem-only overlay writes too, after response assembly.
        if request.method == 'POST' and path in {'/documents','/query'}:
            commit()
        return response

    @app.get('/samples', include_in_schema=False)
    def guide():
        return FileResponse('/srv/deployment/sample-guide.html', media_type='text/html')

    @app.get('/samples/{name}', include_in_schema=False)
    def sample(name: str):
        if name not in {'site1000_bldg2082_floor9385.pdf','site2293_bldg3380_floor15055.pdf','LICENSE.md'}:
            return JSONResponse({'detail':'not_found'},status_code=404)
        return FileResponse(Path('/srv/samples') / name)
    return app
