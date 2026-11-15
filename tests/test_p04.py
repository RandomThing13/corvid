from pathlib import Path
import pytest
from app import query,storage,documents,provider
from app.schemas import QueryRequest
REAL_INVOKE=provider.invoke
SOURCE=Path('data/raw/junction-dataset-preview/data/swiss_dwellings/site1000_bldg2082_floor9385.pdf')
SECOND=SOURCE.with_name('site2293_bldg3380_floor15055.pdf')
@pytest.fixture(autouse=True)
def isolate(tmp_path,monkeypatch):
 monkeypatch.setattr(storage,'DB',tmp_path/'test.db');monkeypatch.setattr(documents,'ROOT',tmp_path/'docs')
 monkeypatch.setattr(provider,'invoke',lambda *a,**k:pytest.fail('unsupported area reached model'))
@pytest.mark.parametrize('question',[
 'What is the total area of room 2.01 + room 2.02 - room 2.03?',
 'What is the total area of room 2.01 + room 2.02 − room 2.03?',
 'What is the area of room 2.01 after removing a 2 m² shaft?',
 'What is the area of room 2.01 in square feet?',
 'What is the area of 2.010?',
 'What is the combined area of room A and room B?',
])
def test_reproduced_unsupported_scope(question):
 d=documents.ingest(SOURCE.read_bytes());a=query.execute(QueryRequest(document_ids=[d.document_id],question=question))
 assert a.status=='unsupported' and a.value is None
 assert a.metadata['attempts']==0 and a.missing_inputs

def test_printed_method_cannot_substitute_geometry():
 d=documents.ingest(SECOND.read_bytes());a=query.execute(QueryRequest(document_ids=[d.document_id],question='What is the printed area of room 4.23?'))
 assert a.status in ('unsupported','needs_review') and a.value is None

def test_explicit_geometry_not_printed():
 d=documents.ingest(SOURCE.read_bytes());a=query.execute(QueryRequest(document_ids=[d.document_id],question='Calculate area of room 2.01 from geometry'))
 assert a.status=='answered' and a.metadata['route']=='calibrated_geometry'
 assert a.metadata['calculation']['source_basis']=='calibrated_geometry'

def test_reservation_persistence_precedes_provider_and_failure_blocks(monkeypatch):
 from types import SimpleNamespace
 from app.schemas import ProviderAnswer
 import sqlite3
 for flag in ('STOA_ENABLE_PAID_API','STOA_API_BALANCE_VERIFIED'):monkeypatch.setenv(flag,'1')
 monkeypatch.setenv('OPENAI_API_KEY','test-key')
 d=documents.ingest(SOURCE.read_bytes());request=QueryRequest(document_ids=[d.document_id],question='count')
 events=[];original=sqlite3.connect
 class Tracking(sqlite3.Connection):
  def close(self):events.append('closed');super().close()
 monkeypatch.setattr(storage.sqlite3,'connect',lambda *a,**k:original(*a,**k,factory=Tracking))
 def hook():
  assert events[-1]=='closed'
  with original(storage.DB) as c:assert c.execute('SELECT COUNT(*) FROM spend').fetchone()[0]>0
  events.append('persisted')
 def parse(**kwargs):
  assert events[-1]=='persisted';events.append('provider')
  raise TimeoutError()
 monkeypatch.setattr(provider,'OpenAI',lambda **kw:SimpleNamespace(responses=SimpleNamespace(input_tokens=SimpleNamespace(count=lambda **kw:SimpleNamespace(input_tokens=100)),parse=parse)))
 try:
  storage.configure_persistence(hook)
  a,m=REAL_INVOKE(request,d,d.pages,'durable');assert events.index('persisted')<events.index('provider')
  def fail():raise RuntimeError('durability unavailable')
  storage.configure_persistence(fail);events.clear()
  a,m=REAL_INVOKE(request,d,d.pages,'blocked');assert m['attempts']==0 and 'provider' not in events
  assert storage.totals()['unknown_reserved_usd']>0
 finally:storage.configure_persistence(None)

def test_provenance_terms_and_missing_id():
 d=documents.ingest(SOURCE.read_bytes())
 a=query.execute(QueryRequest(document_ids=[d.document_id],question='What is the combined area of room 2.01 and room 2.02?'))
 assert a.value==pytest.approx(27.66) and a.metadata['calculation']['source_basis']=='printed_area'
 assert all(t['source_method']=='printed_area' for t in a.metadata['calculation']['terms'])
 b=query.execute(QueryRequest(document_ids=[d.document_id],question='What is the combined area of room 2.01 and room 99.99?'))
 assert b.status=='needs_review' and b.metadata['calculation']['missing_room_ids']==['99.99']

@pytest.mark.parametrize('question',['What is the area of 12.01x?','What is the area of 2.010?'])
def test_invalid_id_boundaries(question):
 d=documents.ingest(SOURCE.read_bytes());a=query.execute(QueryRequest(document_ids=[d.document_id],question=question));assert a.status=='unsupported' and a.value is None

def test_sentence_punctuation_and_german_descriptor():
 d=documents.ingest(SOURCE.read_bytes());a=query.execute(QueryRequest(document_ids=[d.document_id],question='What is the area of room 2.01.'));assert a.value==pytest.approx(15.61)
 d=documents.ingest(SECOND.read_bytes());a=query.execute(QueryRequest(document_ids=[d.document_id],question='Wie gross ist die Nettofläche von Raum 4.23 («Bad») in m²?'));assert a.value==pytest.approx(4.322160437,rel=.02)

def test_build_manifest_validates_app_bytes(tmp_path,monkeypatch):
 import json
 from app.build import runtime_hashes
 expected=runtime_hashes();p=tmp_path/'manifest.json';p.write_text(json.dumps(expected));monkeypatch.setenv('STOA_BUILD_MANIFEST',str(p))
 assert runtime_hashes()==expected
 expected['app/rooms.py']='0'*64;p.write_text(json.dumps(expected))
 with pytest.raises(ValueError,match='differ'):runtime_hashes()
