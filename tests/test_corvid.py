from pathlib import Path
from decimal import Decimal
import pytest
from app import documents,storage,query,provider
from app.rooms import parse_scope,resolve_references,Room,records
from app.schemas import QueryRequest
ROOT=Path('data/raw/junction-dataset-preview/data/swiss_dwellings')
@pytest.fixture(autouse=True)
def isolation(tmp_path,monkeypatch):
 monkeypatch.setattr(storage,'DB',tmp_path/'test.db');monkeypatch.setattr(documents,'ROOT',tmp_path/'docs');monkeypatch.setenv('STOA_ENABLE_PAID_API','0')
 monkeypatch.setattr(provider,'invoke',lambda *a,**k:pytest.fail('native route invoked provider'))
def ask(q,name='site1000_bldg2082_floor9385.pdf'):
 d=documents.ingest((ROOT/name).read_bytes());return query.execute(QueryRequest(document_ids=[d.document_id],page_index=0,question=q))
@pytest.mark.parametrize('q',[
 'Could you add the areas of rooms 2.01 and 2.02 in sqm, please?',
 'What is the total area of rooms 2.02 and 2.01 in m2?',
 'What is the combined area of 2.01 + 2.02 in square metres?',
 'What is the area of 2.01 and 2.02 in m^2, thanks?',
])
def test_paraphrases(q):
 a=ask(q);assert a.status=='answered' and a.value==27.66
 assert len(a.metadata['calculation']['terms'])==2
 assert all(t['source_measurement'] and t['source_unit']=='m2' for t in a.metadata['calculation']['terms'])
@pytest.mark.parametrize('ids,total',[('2.01 and 2.03',18.70),('2.02 and 2.05',30.41)])
def test_other_combinations(ids,total):
 assert ask('What is the combined printed area of '+ids+'?').value==total
def test_source_names_outside_demo():
 a=ask('What is the total floor area of the kitchen and living room?','site4085_bldg6548_floor26706.pdf')
 assert a.status=='answered' and a.metadata['calculation']['included_room_ids']==['3.02','3.01']
 assert a.metadata['calculation']['scope']['operation']=='sum'
 assert all(t['source_name'] for t in a.metadata['calculation']['terms'])
def test_repeated_names_ambiguous():
 a=ask('What is the area of the kitchen?');assert a.status=='unsupported' and a.value is None
 assert len(a.metadata['calculation']['resolution_candidates']['kitchen'])==4
@pytest.mark.parametrize('q',['What is the area of these two rooms?','What is the sum area of 2.01 and 2.01?','What is the combined area of room A and room B?'])
def test_no_guessing(q):assert ask(q).status=='unsupported'
def test_missing_and_duplicate_alias():
 a=ask('What is the combined area of 2.01 and 99.99?');assert a.status=='needs_review' and a.value==15.61
 b=ask('What is the combined area of 2.05 and living room?');assert b.status=='unsupported' and b.value is None
 assert parse_scope('How many rooms have area labels?') is None
def test_disabled_operational_guard(monkeypatch):
 from unittest.mock import Mock
 monkeypatch.setenv('OPENAI_API_KEY','test-key');monkeypatch.setenv('STOA_API_BALANCE_VERIFIED','1')
 client=Mock(side_effect=AssertionError('must not construct provider'));monkeypatch.setattr(provider,'OpenAI',client)
 d=documents.ingest((ROOT/'site1000_bldg2082_floor9385.pdf').read_bytes())
 a,m=provider._invoke(QueryRequest(document_ids=[d.document_id],question='count'),d,d.pages,'blocked')
 assert a is None and m['error']=='runtime_access_blocked' and m['attempts']==0
 assert storage.totals()['known_usd']==0 and storage.totals()['unknown_reserved_usd']==0
 assert ask('What is the printed area of room 2.01?').value==15.61

def test_cached_original():
 a=ask('What is the printed area of room 2.01?');b=ask('What is the printed area of room 2.01?')
 assert b.metadata['original_run_id']==a.run_id and b.evidence[0].evidence_id==a.evidence[0].evidence_id

@pytest.mark.parametrize('unit',['m2','sqm','square metres'])
def test_source_room_A_and_decimal_comma(unit):
 import pymupdf as f
 from app.ingest import locate_printed_area
 with f.open() as d:
  p=d.new_page();p.insert_text((100,90),'Kitchen');p.insert_text((100,105),'Room A');p.insert_text((120-f.get_text_length('12,50 '+unit,fontsize=11)/2,120),'12,50 '+unit)
  rs=records(p);assert len(rs)==1 and rs[0].room_id=='A' and rs[0].value==12.5
  assert resolve_references(['A'],rs)[0]==['A']
