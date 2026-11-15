"""Local development page/evidence endpoints. No general question answering."""
from fastapi import FastAPI, HTTPException, Header
import os
from app.build import build_id
STARTUP_BUILD_ID=build_id()
from fastapi.responses import FileResponse
from app.ingest import build_evidence, DocumentError, Evidence

app = FastAPI(title="Stoa native development slice", version="0.1.0")


@app.get("/health")
def health():
    return {"status": "ok", "scope": "local native PDF development evidence", "build_id": STARTUP_BUILD_ID}


def development_evidence() -> Evidence:
    try:
        return build_evidence()
    except DocumentError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/development/evidence", response_model=Evidence)
def evidence():
    return development_evidence()


@app.get("/development/page")
def page():
    return FileResponse(development_evidence().page_image_path, media_type="image/png")


@app.get("/development/highlight")
def highlight():
    return FileResponse(development_evidence().image_path, media_type="image/png")

# P01 routes preserve the historical P00 contract above.
from fastapi import UploadFile, File
from app import documents, storage, query
from app.schemas import Document, QueryRequest, Answer

@app.post('/documents', response_model=Document)
def upload(file: UploadFile = File(...)):
    data=file.file.read(documents.MAX_BYTES+1)
    try:return documents.ingest(data)
    except documents.InputError as exc:raise HTTPException(status_code=422,detail={'status':'unsupported','code':str(exc)}) from exc

@app.post('/query',response_model=Answer)
def ask(request:QueryRequest, x_stoa_evaluation: str | None = Header(default=None)):
    if os.getenv('STOA_FINAL_EVALUATION')=='1' and x_stoa_evaluation!='final':
        raise HTTPException(status_code=409,detail='Final evaluation in progress; interactive queries are paused.')
    try:return query.execute(request)
    except documents.InputError as exc:raise HTTPException(status_code=422,detail={'status':'unsupported','code':str(exc)}) from exc

@app.get('/runs/{run_id}',response_model=Answer)
def run(run_id:str):
    result=storage.get('runs',run_id)
    if not result:raise HTTPException(status_code=404,detail='run_not_found')
    return result

@app.get('/documents/{document_id}/pages/{page_index}/image')
def document_image(document_id:str,page_index:int):
    try:
        doc=documents.load(document_id)
        if not 0<=page_index<len(doc.pages):raise documents.InputError('page_out_of_scope')
        return FileResponse(documents.directory(document_id)/f'{page_index}.png',media_type='image/png')
    except documents.InputError as exc:raise HTTPException(status_code=404,detail=str(exc)) from exc

@app.get('/runs/{run_id}/pages/{page_index}/overlay')
def overlay(run_id:str,page_index:int):
    result=run(run_id)
    if f'/runs/{run_id}/pages/{page_index}/overlay' not in result['metadata'].get('overlay_urls',[]):raise HTTPException(status_code=404,detail='overlay_not_found')
    return FileResponse(documents.ROOT.parent/'overlays'/f'{run_id}-{page_index}.png',media_type='image/png')

from app.limits import BodyLimit
app.add_middleware(BodyLimit)

# The frontend agent owns static files; imports work before they arrive.
from pathlib import Path
from fastapi.staticfiles import StaticFiles
STATIC_ROOT = Path(__file__).resolve().parent / 'static'
app.mount('/static', StaticFiles(directory=str(STATIC_ROOT), check_dir=False), name='static')

@app.get('/')
def index():
    path = STATIC_ROOT / 'index.html'
    if not path.is_file():
        raise HTTPException(status_code=503, detail='Frontend is being prepared; API routes are available.')
    return FileResponse(path, media_type='text/html')
