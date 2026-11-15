import io,json
from pathlib import Path
from types import SimpleNamespace
import pytest
from PIL import Image
from fastapi.testclient import TestClient
from pydantic import ValidationError
from app import documents,storage,provider,query
from app.schemas import QueryRequest,ProviderAnswer,Evidence,Answer
from app.main import app

@pytest.fixture(autouse=True)
def isolated(tmp_path,monkeypatch):
 monkeypatch.setattr(storage,'DB',tmp_path/'test.db');monkeypatch.setattr(documents,'ROOT',tmp_path/'documents')
 monkeypatch.setenv('STOA_ENABLE_PAID_API','0')
def png(size=(60,40)):
 f=io.BytesIO();Image.new('RGB',size,'white').save(f,format='PNG');return f.getvalue()
def proposed(**kw):
 d={'status':'answered','value':1.,'unit':'count','basis':'model_visual','detections':[{'page_index':0,'bbox':[.1,.1,.3,.3],'category':'window','original_text':None}],'detections_complete':True,'counting_rule':'exclude legend','assumptions':[],'missing_inputs':[]};d.update(kw);return ProviderAnswer(**d)
def test_upload_corruption_limits_scope():
 with TestClient(app) as c:
  assert c.post('/documents',files={'file':('bad.png',b'bad')}).status_code==422
  d=c.post('/documents',files={'file':('image.png',png())}).json();id=d['document_id']
  assert (d['pages'][0]['width'],d['pages'][0]['height'])==(60,40)
  for q in ({'document_ids':[id,id],'question':'x'},{'document_ids':[id],'question':'x','runtime_model':'arbitrary'},{'document_ids':[id],'question':'x','page_indices':[0,1,2,3,4]}):assert c.post('/query',json=q).status_code==422
  assert c.post('/query',json={'document_ids':[id],'question':'x','page_index':4}).status_code==422
  a=c.post('/query',json={'document_ids':[id],'question':'count','mode':'direct_vlm'}).json()
  assert a['missing_inputs']==['runtime_access_blocked']
  assert c.get('/runs/'+a['run_id']).json()==a
  assert '/Users/' not in json.dumps(d)+json.dumps(a)
def test_resized_dimensions():
 d=documents.ingest(png((4000,2200)))
 p=d.pages[0];assert p.width*p.height<=8_000_000
 with Image.open(documents.directory(d.document_id)/'0.png') as im:assert im.size==(p.width,p.height)
def test_model_validation_and_evidence():
 d=documents.ingest(png());pages=d.pages
 a=query.assemble(proposed(value=2.),d,pages,'a',{})
 assert a.status=='needs_review' and a.raw_model_count==2 and a.evidence_tally==1
 assert query.assemble(proposed(detections=[],value=0.),d,pages,'b',{}).status=='needs_review'
 with pytest.raises(ValueError):query.assemble(proposed(value=1.5),d,pages,'a',{})
 with pytest.raises(ValueError):query.assemble(proposed(detections=[{'page_index':1,'bbox':[.1,.1,.2,.2],'category':'x','original_text':None}]),d,pages,'a',{})
 with pytest.raises(ValidationError):query.assemble(proposed(detections=[{'page_index':0,'bbox':[.2,.2,.1,.3],'category':'x','original_text':None}]),d,pages,'a',{})
 with pytest.raises(ValidationError):Answer(run_id='x',status='answered')
def test_budget_survives_restart_and_timeout():
 storage.reserve('timeout',1.5,{'unknown':True})
 assert storage.totals()['unknown_reserved_usd']==1.5
 with pytest.raises(ValueError,match='budget_exhausted'):storage.reserve('next',.6,{})
 storage.settle('timeout',.2,{})
 storage.reserve('next',1.8,{})
 assert storage.totals()['known_usd']==.2
 assert storage.totals()['unknown_reserved_usd']==1.8

def test_cache_separates_question_model_source(monkeypatch):
 calls=[]
 def fake(req,doc,pages,id):calls.append(id);return proposed(),{'attempts':1,'cost_usd':0}
 monkeypatch.setattr(provider,'invoke',fake)
 d=documents.ingest(png());req=QueryRequest(document_ids=[d.document_id],question='count')
 a=query.execute(req);b=query.execute(req)
 assert b.metadata['cache_hit'] and b.metadata['original_run_id']==a.run_id and len(calls)==1
 query.execute(req.model_copy(update={'runtime_model':'gpt-6-luna'}));query.execute(req.model_copy(update={'question':'different'}))
 other=documents.ingest(png((61,40)));query.execute(req.model_copy(update={'document_ids':[other.document_id]}))
 assert len(calls)==4

def test_provider_timeout_refusal_incomplete_and_schema(monkeypatch):
 for flag in ('STOA_ENABLE_PAID_API','STOA_API_BALANCE_VERIFIED'):monkeypatch.setenv(flag,'1')
 monkeypatch.setenv('OPENAI_API_KEY','test-canary-key')
 d=documents.ingest(png());req=QueryRequest(document_ids=[d.document_id],question='x')
 class Responses:
  input_tokens=SimpleNamespace(count=lambda **kw:SimpleNamespace(input_tokens=100))
  def parse(self,**kw):raise TimeoutError('unknown charge')
 r=Responses();monkeypatch.setattr(provider,'OpenAI',lambda **kw:SimpleNamespace(responses=r))
 answer,meta=provider.invoke(req,d,d.pages,'timeout');assert answer is None and meta['attempts']==1 and storage.totals()['unknown_reserved_usd']>0
 for i,status in enumerate(('incomplete','completed')):
  r.parse=lambda **kw:SimpleNamespace(model=req.runtime_model,_request_id='r',id='resp',service_tier='default',status=status,incomplete_details=None,usage=None,output_parsed=None)
  answer,meta=provider.invoke(req,d,d.pages,'refusal'+str(i));assert answer is None and meta['error']=='incomplete_refused_or_unparsed'
 with pytest.raises(ValidationError):ProviderAnswer.model_validate({'value':1})

def test_label_canary_boundary(monkeypatch):
 from scripts.benchmark import outbound
 secret='GOLD-CANARY-DO-NOT-SEND'
 payload=outbound('d','How many windows?','gpt-6.1-sol')
 assert secret not in json.dumps(payload)
 assert set(payload)=={'document_ids','question','mode','runtime_model','use_cache'}
 d=documents.ingest(png());q=QueryRequest(document_ids=[d.document_id],question=payload['question'])
 runtime=provider.payload(q,d,d.pages)
 assert secret not in json.dumps(runtime) and 'answer' not in runtime
 for p in Path('app').glob('*.py'):
  text=p.read_text();assert 'eval_private' not in text and 'questions.jsonl' not in text and 'reports/' not in text and 'from scripts' not in text

def test_transport_body_limit():
 with TestClient(app) as c:
  r=c.post('/documents',content=b'',headers={'content-length':str(26*1024*1024),'content-type':'multipart/form-data; boundary=x'})
  assert r.status_code==413

def test_native_real_query_and_absent_room():
 from app.ingest import DEVELOPMENT_PDF
 doc=documents.ingest(DEVELOPMENT_PDF.read_bytes())
 request=QueryRequest(document_ids=[doc.document_id],question='What is the printed area of room 2.01?',mode='native')
 a=query.execute(request)
 assert a.value==15.61 and a.verification=='native_source'
 assert a.evidence[0].native_rect and a.evidence[0].transform
 assert query.execute(request.model_copy(update={'question':'What is the printed area of room ABSENT-P01-999999?'})).status=='unsupported'

def test_split_isolation_and_group_counts():
 s=json.loads(Path('eval/splits.json').read_text());dev={c['group'] for c in s['dev']};final={c['group'] for c in s['final']}
 assert len(s['dev'])==8 and len(dev)>=6 and len(s['final'])==24 and len(final)>=12
 assert not (set(s['development_groups']) & final)
 assert Counter(c['type'] for c in s['dev'])=={'count':6,'area':2}
 assert set(s['groups'][next(iter(dev))])
 assert 'answer' not in json.dumps(s)
from collections import Counter

def test_gold_field_rejected_before_inference(monkeypatch):
 def forbidden(*args,**kwargs):raise AssertionError('inference must not be reached')
 monkeypatch.setattr(provider,'invoke',forbidden)
 with TestClient(app) as c:
  d=c.post('/documents',files={'file':('x.png',png())}).json()
  r=c.post('/query',json={'document_ids':[d['document_id']],'question':'How many windows?','answer':'GOLD-CANARY-DO-NOT-SEND'})
  assert r.status_code==422

def test_pdf_page_limit_and_explicit_scope():
 import pymupdf as fitz
 with fitz.open() as d:
  for _ in range(21):d.new_page()
  with pytest.raises(documents.InputError,match='20'):documents.ingest(d.tobytes())
 with fitz.open() as d:
  for _ in range(5):d.new_page()
  doc=documents.ingest(d.tobytes())
 with pytest.raises(documents.InputError,match='four'):documents.selected(doc,QueryRequest(document_ids=[doc.document_id],question='x'))
 assert len(documents.selected(doc,QueryRequest(document_ids=[doc.document_id],question='x',page_indices=[0,4])))==2

def test_jpeg_exif_display_coordinates():
 image=Image.new('RGB',(50,30),'white');exif=image.getexif();exif[274]=6
 data=io.BytesIO();image.save(data,format='JPEG',exif=exif)
 doc=documents.ingest(data.getvalue());page=doc.pages[0]
 assert (page.width,page.height)==(30,50)
 assert page.transform['exif_orientation']==6
 assert page.transform['original_size']==[50,30]

def test_exact_cache_accounting_no_reasoning_double_bill(monkeypatch):
 for flag in ('STOA_ENABLE_PAID_API','STOA_API_BALANCE_VERIFIED'):monkeypatch.setenv(flag,'1')
 monkeypatch.setenv('OPENAI_API_KEY','test-canary-key')
 doc=documents.ingest(png());request=QueryRequest(document_ids=[doc.document_id],question='count')
 usage={'input_tokens':100,'input_tokens_details':{'cached_tokens':20,'cache_write_tokens':30,'cache_write_tokens_details':{'ttl_30m_tokens':20,'ttl_12h_tokens':10}},'output_tokens':40,'output_tokens_details':{'reasoning_tokens':30},'total_tokens':140}
 captured={}
 def parse(**kwargs):
  captured.update(kwargs)
  return SimpleNamespace(model=request.runtime_model,_request_id='req',id='resp',service_tier='default',status='completed',incomplete_details=None,usage=SimpleNamespace(model_dump=lambda:usage),output_parsed=proposed())
 def count(**kwargs):
  assert kwargs['text']['format']['type']=='json_schema'
  assert kwargs['input'][0]['content'][2]['detail']=='high'
  return SimpleNamespace(input_tokens=100)
 monkeypatch.setattr(provider,'OpenAI',lambda **kwargs:SimpleNamespace(responses=SimpleNamespace(input_tokens=SimpleNamespace(count=count),parse=parse)))
 answer,meta=provider.invoke(request,doc,doc.pages,'billing')
 expected=(50*2+20*.1+20*2.5+10*5+40*10)/1e6
 assert meta['cost_usd']==pytest.approx(expected)
 assert storage.totals()['known_usd']==pytest.approx(expected)
 assert storage.totals()['unknown_reserved_usd']==0
 assert captured['max_output_tokens']==8192 and captured['store'] is False and captured['service_tier']=='default'
 assert captured['reasoning']=={'effort':'medium'}

def test_missing_value_and_partial_area_are_not_accepted():
 d=documents.ingest(png())
 assert query.assemble(proposed(value=None),d,d.pages,'missing',{}).status=='needs_review'
 assert query.assemble(proposed(unit='m2',basis='printed_area',detections_complete=False),d,d.pages,'partial',{}).status=='needs_review'

def test_numeric_unit_and_zero_evaluation():
 from scripts.benchmark import score
 assert score({'value':10000,'unit':'cm2'},1,'area','m2')
 assert not score({'value':1,'unit':'m'},1,'area','m2')
 assert score({'value':0,'unit':'m2'},0,'area','m2')
 assert not score({'value':.00001,'unit':'m2'},0,'area','m2')
 assert not score({'value':-1,'unit':'count'},-1,'count','count')

@pytest.mark.parametrize('status',[401,403,404,429,500])
def test_http_failures_have_no_retry_and_keep_reservation(status,monkeypatch):
 for flag in ('STOA_ENABLE_PAID_API','STOA_API_BALANCE_VERIFIED'):monkeypatch.setenv(flag,'1')
 monkeypatch.setenv('OPENAI_API_KEY','test-canary-key');calls=[]
 class Failure(Exception):status_code=status
 def parse(**kwargs):calls.append(kwargs);raise Failure()
 def client(**kwargs):
  assert kwargs['max_retries']==0 and kwargs['timeout']==90.0
  return SimpleNamespace(responses=SimpleNamespace(input_tokens=SimpleNamespace(count=lambda **kwargs:SimpleNamespace(input_tokens=100)),parse=parse))
 monkeypatch.setattr(provider,'OpenAI',client)
 d=documents.ingest(png());a,m=provider.invoke(QueryRequest(document_ids=[d.document_id],question='x'),d,d.pages,'failure')
 assert a is None and m['http_status']==status and len(calls)==1
 assert storage.totals()['unknown_reserved_usd']>0
