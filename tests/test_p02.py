from pathlib import Path
import pytest
from app import documents,storage,query,provider
from app.schemas import QueryRequest
SOURCE=Path('data/raw/junction-dataset-preview/data/swiss_dwellings/site1000_bldg2082_floor9385.pdf')
@pytest.fixture(autouse=True)
def isolated(tmp_path,monkeypatch):
 monkeypatch.setattr(storage,'DB',tmp_path/'test.db');monkeypatch.setattr(documents,'ROOT',tmp_path/'documents')
 monkeypatch.setattr(provider,'invoke',lambda *a,**k:pytest.fail('deterministic area route called model'))

def test_combined_area_never_returns_only_first_room():
 doc=documents.ingest(SOURCE.read_bytes())
 result=query.execute(QueryRequest(document_ids=[doc.document_id],question='What is the combined area of room 2.01 and room 2.02?',mode='native'))
 assert result.value==pytest.approx(27.66)
 assert result.status=='answered'
 assert result.metadata['calculation']['included_room_ids']==['2.01','2.02']

@pytest.mark.parametrize('question,expected',[('What is the printed area of room 2.01?',15.61),('Wie gross ist die Fläche von Raum 2.01?',15.61),('Was ist die Summe der Flächen von Raum 2.01 und Raum 2.02?',27.66)])
def test_printed_scope_no_model(question,expected):
 doc=documents.ingest(SOURCE.read_bytes());a=query.execute(QueryRequest(document_ids=[doc.document_id],question=question))
 assert a.status=='answered' and a.value==pytest.approx(expected)
 assert a.metadata['attempts']==0 and a.metadata['cost_usd']==0 and a.metadata['incremental_cost_usd']==0
 assert all(any(ae.role=='room_label' for ae in a.evidence if ae.evidence_id in t['evidence_ids']) and any(ae.role=='area_label' for ae in a.evidence if ae.evidence_id in t['evidence_ids']) for t in a.metadata['calculation']['terms'])

@pytest.mark.parametrize('question',['Compare the area of room 2.01 and room 2.02','What is the difference in area of room 2.01 and room 2.02?','What is the average area of room 2.01?','What is the combined area of room 2.01 and the kitchen?','What is the sum area of room 2.01 excluding room 2.02?','What is the whole floor area excluding room 2.01?'])
def test_unsupported_operations_not_silently_ignored(question):
 doc=documents.ingest(SOURCE.read_bytes());a=query.execute(QueryRequest(document_ids=[doc.document_id],question=question))
 assert a.status=='unsupported' and a.value is None

def test_partial_sum_missing_id():
 doc=documents.ingest(SOURCE.read_bytes());a=query.execute(QueryRequest(document_ids=[doc.document_id],question='What is the combined area of room 2.01 and room 9.99?'))
 assert a.status=='needs_review' and a.value==pytest.approx(15.61)
 assert a.metadata['calculation']['missing_room_ids']==['9.99']
 assert a.metadata['calculation']['scope_complete'] is False

SECOND=SOURCE.with_name('site2293_bldg3380_floor15055.pdf')
def test_unprinted_geometric_room():
 doc=documents.ingest(SECOND.read_bytes());a=query.execute(QueryRequest(document_ids=[doc.document_id],question='Wie gross ist die Nettofläche von Raum 4.23 («Bad») in m²?',page_index=0))
 assert a.status=='answered' and a.value==pytest.approx(4.322159817,rel=.02)
 assert a.verification=='calculated_from_source' and a.basis=='calculated'
 assert {e.role for e in a.evidence}>={'room_boundary','room_label','scale_bar'}
 assert a.metadata['calculation']['calibration']['validated']

def test_floor_scope_candidate_not_indoor_claim():
 doc=documents.ingest(SOURCE.read_bytes());a=query.execute(QueryRequest(document_ids=[doc.document_id],question='What is the total net floor area in m² of all numbered indoor rooms on this floor (excluding balconies, loggias, terraces and other outdoor spaces, shafts and voids)?'))
 assert a.value==pytest.approx(341.447298223,rel=.02)
 assert a.status=='needs_review' and not a.metadata['calculation']['scope_complete']
 assert len(a.metadata['calculation']['included_room_ids'])==31
 assert any('unresolved_room_classification' in issue for issue in a.missing_inputs)

def test_polygon_closure_validity_rectangle_and_competing_family():
 import pymupdf as fitz
 from shapely.geometry import Polygon
 from app.geometry import path_polygon,room_family,GeometryError
 from app.rooms import records
 p=lambda x,y:fitz.Point(x,y)
 path={'type':'fs','fill':(1,1,1),'color':(0,0,0),'width':1,'items':[('l',p(10,10),p(90,10)),('l',p(90,10),p(90,90)),('l',p(90,90),p(10,90)),('l',p(10,90),p(10,10))],'closePath':False}
 assert path_polygon(path,(0,0,100,100)).area==6400
 path['items']=path['items'][:-1];assert path_polygon(path,(0,0,100,100)) is None
 path['closePath']=True;assert path_polygon(path,(0,0,100,100)).area==6400
 path['items']=[('re',fitz.Rect(10,10,90,90),1)];assert path_polygon(path,(0,0,100,100)).area==6400
 path['items']=[('l',p(10,10),p(90,90)),('l',p(90,90),p(90,10)),('l',p(90,10),p(10,90)),('l',p(10,90),p(10,10))];assert path_polygon(path,(0,0,100,100)) is None
 with fitz.open() as d:
  page=d.new_page(width=300,height=300)
  page.insert_text((120,140),'1.01',fontsize=10)
  page.draw_rect(fitz.Rect(50,50,200,200),color=(1,0,0),fill=(1,1,1),width=1)
  page.draw_rect(fitz.Rect(60,60,190,190),color=(0,0,1),fill=(1,1,1),width=2)
  with pytest.raises(GeometryError,match='competing'):room_family(page,records(page))

def test_span_area_is_not_room_identifier():
 import pymupdf as fitz
 from app.rooms import records
 with fitz.open(SOURCE) as d:
  rs=records(d[0]);assert len(rs)==31;assert '15.61' not in {r.room_id for r in rs}

def test_calibration_missing_conflicting():
 import pymupdf as fitz
 from app.geometry import calibrate,GeometryError
 from app.rooms import records
 with fitz.open(SOURCE) as d:
  page=d[0]
  # Remove only visible unit source; retained nominal ratio cannot calibrate.
  from app.ingest import extract_native
  for span in extract_native(page)[1]:
   if span['text'].strip()=='m':page.add_redact_annot(fitz.Rect(span['rect']))
  page.apply_redactions()
  with pytest.raises(GeometryError):calibrate(page,records(page))

def test_geometry_rotated_and_resized_display_alignment():
 import pymupdf as fitz
 from PIL import Image
 with fitz.open(SECOND) as d:
  d[0].set_rotation(90);data=d.tobytes()
 doc=documents.ingest(data);a=query.execute(QueryRequest(document_ids=[doc.document_id],question='What is the area of room 4.23?',page_index=0))
 assert a.status=='answered' and a.value==pytest.approx(4.322159817,rel=.02)
 e=next(e for e in a.evidence if e.role=='room_boundary');pg=doc.pages[0]
 assert e.polygon and all(0<=v<=1 for xy in e.polygon for v in xy)
 matrix=fitz.Matrix(pg.transform['rotation_matrix'])*fitz.Matrix(pg.transform['render_matrix'])
 for native,display in zip(e.polygon_native,e.polygon):
  p=fitz.Point(native)*matrix;assert display==pytest.approx([p.x/pg.width,p.y/pg.height])
 with Image.open(documents.directory(doc.document_id)/'0.png') as im:assert im.size==(pg.width,pg.height)

def test_no_models_for_recognized_area_without_scale():
 import pymupdf as fitz
 with fitz.open() as d:
  p=d.new_page();p.insert_text((100,100),'1.01');p.draw_rect(fitz.Rect(50,50,200,200),color=(.2,.3,.4),fill=(1,1,1));data=d.tobytes()
 doc=documents.ingest(data);a=query.execute(QueryRequest(document_ids=[doc.document_id],question='What is the area of room 1.01?'))
 assert a.status=='unsupported' and a.metadata['attempts']==0

def test_conflicting_graphic_scale_intervals():
 import pymupdf as fitz
 from app.geometry import calibrate,GeometryError
 from app.rooms import records
 with fitz.open() as d:
  page=d.new_page(width=300,height=300);page.insert_text((100,100),'1.01',fontsize=10)
  page.draw_rect(fitz.Rect(20,250,40,254),color=(0,0,0),fill=(0,0,0));page.draw_rect(fitz.Rect(40,250,60,254),color=(0,0,0),fill=(1,1,1))
  for x,t in [(20,'0'),(40,'1'),(60,'3')]:page.insert_text((x-fitz.get_text_length(t,fontsize=10)/2,245),t,fontsize=10)
  page.insert_text((75,254),'m',fontsize=10)
  with pytest.raises(GeometryError,match='inconsistent_scale_intervals'):calibrate(page,records(page))

def test_duplicate_identifier_and_multiple_pages_never_partial_answer():
 import pymupdf as fitz
 with fitz.open(SOURCE) as d:
  copy=fitz.open();copy.insert_pdf(d);copy.insert_pdf(d);data=copy.tobytes();copy.close()
 doc=documents.ingest(data);a=query.execute(QueryRequest(document_ids=[doc.document_id],question='What is the area of room 2.01?'))
 assert a.status=='unsupported' and a.value is None and a.metadata['calculation']['missing_room_ids']==['2.01']

def test_auto_cache_provenance_zero_increment():
 doc=documents.ingest(SOURCE.read_bytes());request=QueryRequest(document_ids=[doc.document_id],question='What is the area of room 2.01?')
 a=query.execute(request);b=query.execute(request)
 assert b.metadata['cache_hit'] and b.metadata['original_run_id']==a.run_id
 assert b.metadata['attempts']==0 and b.metadata['incremental_cost_usd']==0 and b.metadata['route']=='native_printed_area'
 assert b.metadata['elapsed_ms']>=0

def test_material_printed_geometry_disagreement_is_review(monkeypatch):
 import app.area as area
 original=area.records
 def altered(page):
  rooms=original(page)
  for r in rooms:
   if r.room_id=='2.01':r.value*=2  # Synthetic contradictory printed measurement.
  return rooms
 monkeypatch.setattr(area,'records',altered)
 doc=documents.ingest(SOURCE.read_bytes());a=query.execute(QueryRequest(document_ids=[doc.document_id],question='What is the total net floor area of all numbered indoor rooms?'))
 assert a.status=='needs_review' and 'printed_geometry_disagreement:2.01' in a.missing_inputs

def test_crop_excluding_graphic_scale_is_not_measurable():
 import pymupdf as fitz
 with fitz.open(SECOND) as d:
  p=d[0];p.set_cropbox(fitz.Rect(0,0,p.cropbox.width,p.cropbox.height*.85));data=d.tobytes()
 doc=documents.ingest(data);a=query.execute(QueryRequest(document_ids=[doc.document_id],question='What is the area of room 4.23?'))
 assert a.status in ('needs_review','unsupported') and a.metadata['attempts']==0
 assert not a.metadata['calculation']['calibration']['validated']

def test_multiple_floor_scopes_do_not_borrow_single_scale():
 import pymupdf as fitz
 from app.rooms import records
 from app.geometry import calibrate,GeometryError
 with fitz.open(SOURCE) as d:
  p=d[0];p.insert_text((50,50),'9.01')
  with pytest.raises(GeometryError,match='multiple_drawing_scopes'):calibrate(p,records(p))

@pytest.mark.parametrize('question',['What is half the area of room 2.01?','What is the combined area of room 2.01 and room 2.02 and the kitchen?'])
def test_unparsed_extra_operations_and_operands_are_rejected(question):
 doc=documents.ingest(SOURCE.read_bytes());a=query.execute(QueryRequest(document_ids=[doc.document_id],question=question))
 assert a.status=='unsupported' and a.value is None
