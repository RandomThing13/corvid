"""Deterministic printed-area and bounded calibrated vector measurement routes."""
from collections import Counter
import re
from decimal import Decimal
import pymupdf as fitz
from app import documents,ingest
from app.rooms import records,parse_scope,resolve_references
from app.geometry import room_family,calibrate,GeometryError
from app.schemas import Answer,Evidence


def calculation(scope):
 return {'operation':scope['operation'],'source_basis':None,'scope':scope,'terms':[],'included_room_ids':[],'excluded_rooms':[],'missing_room_ids':[],'scope_complete':False,'calibration':{'points_per_metre':None,'scale_evidence_ids':[],'interval_relative_disagreement':None,'validated':False}}

def classify(room):
 name=room.name['text'].lower() if room.name else ''
 if re.search(r'balkon|balcon|balcone|loggia|terrass|terrace|schacht|shaft|void|luftraum',name):return 'excluded'
 if re.fullmatch(r'zimmer|schlafzimmer|küche|korridor|wohnen(?:/essen)?|essen|reduit|treppenhaus|bad|wc|dusche|flur|entrée|chambre|cuisine|séjour|salle de bain|camera|cucina|bagno',name):return 'indoor'
 return 'unresolved'

def route(request,doc,pages,run_id):
 scope=parse_scope(request.question)
 if scope is None:return None
 calc=calculation(scope);evidence=[];issues=[]
 metadata={'raw_provider_candidate':None,'route':'native_area','attempts':0,'cost_usd':0,'incremental_cost_usd':0,'calculation':calc}
 def result(status,value=None,basis='unknown',verification='none'):
  return Answer(run_id=run_id,status=status,value=value,unit='m2',basis=basis,source_evidence_ids=[e.evidence_id for e in evidence],evidence=evidence,verification=verification,metadata=metadata,missing_inputs=issues,counting_rule='Source-derived terms summed once per requested room. '+('Complete requested scope.' if calc['scope_complete'] else 'Partial/candidate subtotal only; requested scope is unresolved.'))
 if scope['operation']=='unsupported':issues.append(scope['reason']);return result('unsupported')
 if doc.media_type!='application/pdf':issues.append('recognized_area_requires_native_PDF_evidence');return result('unsupported')
 with fitz.open(documents.directory(doc.document_id)/'source.pdf') as pdf:
  page_info={p.page_index:p for p in pages};all_rooms=[r for p in pages for r in records(pdf[p.page_index])]
  multiplicity=Counter(r.room_id for r in all_rooms)
  byid={r.room_id:r for r in all_rooms if multiplicity[r.room_id]==1}
  requested=scope['ids'] if scope['operation']!='indoor_floor_total' else list(multiplicity)
  if scope.get('references'):
   requested,problems,candidates=resolve_references(scope['references'],all_rooms)
   if problems:
    issues.extend(problems);calc['resolution_candidates']=candidates
    # A named operand failure must not masquerade as a complete subtotal.
    if any('ambiguous_' in p or 'duplicate_' in p for p in problems):
     calc['missing_room_ids']=[r for r in scope['references'] if r in candidates]
     return result('unsupported')
   calc['missing_room_ids']=[r for r in scope['references'] if r in candidates and not candidates[r]]
  if not requested:issues.append('no_native_room_identifiers');return result('unsupported')
  calc['missing_room_ids']+= [id for id in requested if id not in byid]
  if calc['missing_room_ids']:issues.append('missing_or_duplicate_room_identifiers')
  selected=[byid[id] for id in requested if id in byid]
  whole=scope['operation']=='indoor_floor_total'
  if whole and len(pages)!=1:issues.append('whole_floor_scope_requires_one_explicit_page')
  method=scope.get('requested_method','auto')
  geometry_needed=method=='geometry' or (method=='auto' and (whole or any(r.value is None for r in selected)))
  polygons={};scale=None;families={}
  if geometry_needed:
   if len(pages)!=1:issues.append('geometry_requires_one_selected_page')
   else:
    p=pdf[pages[0].page_index]
    try:
     polygons,families=room_family(p,all_rooms);scale=calibrate(p,all_rooms)
     metadata['polygon_family']=families
    except GeometryError as exc:issues.append(str(exc))
  def add(room,rect,role,text=None,polygon=None):
   info=page_info[room.page_index];t=info.transform
   pix=ingest.rect_to_pixels(rect,fitz.Matrix(t['rotation_matrix']),fitz.Matrix(t['render_matrix']),t['pixmap_origin'])
   vertices=None;native=None
   if polygon is not None:
    native=[list(x) for x in list(polygon.exterior.coords)[:-1]];vertices=[]
    for x,y in native:
     point=fitz.Point(x,y)*fitz.Matrix(t['rotation_matrix'])*fitz.Matrix(t['render_matrix'])
     vertices.append([(point.x-t['pixmap_origin'][0])/info.width,(point.y-t['pixmap_origin'][1])/info.height])
   eid=f'{run_id}-e{len(evidence)}'
   evidence.append(Evidence(evidence_id=eid,document_id=doc.document_id,source_sha256=doc.sha256,page_index=room.page_index,bbox=ingest.normalized(pix,info.width,info.height),method='native',original_text=text,native_rect=list(rect),transform=t,role=role,polygon=vertices,polygon_native=native))
   return eid
  if scale and selected:
   sid=add(selected[0],scale['rect'],'scale_bar',scale['text'])
   calc['calibration']={**{k:scale[k] for k in ('points_per_metre','interval_relative_disagreement','validated')},'scale_evidence_ids':[sid],'ticks':scale['ticks'],'intervals':scale['intervals']}
  used_geometry=False
  for room in selected:
   label_id=add(room,room.label['rect'],'room_label',room.label['text']);refs=[label_id]
   if room.name:refs.append(add(room,room.name['rect'],'room_label',room.name['text']))
   classification=classify(room)
   if whole and scope.get('indoor') and classification=='excluded':
    calc['excluded_rooms'].append({'room_id':room.room_id,'reason':'Source label: '+room.name['text'],'evidence_ids':refs});continue
   if whole and (not scope.get('indoor') or classification=='unresolved'):
    issues.append('unresolved_room_classification:'+room.room_id)
   value=room.value
   # Whole-floor route uses one consistent geometric basis, avoiding a mixed subtotal.
   geometric=method=='geometry' or (method=='auto' and (whole or value is None))
   if method=='printed' and value is None:
    calc['missing_room_ids'].append(room.room_id);issues.append('requested_printed_area_missing:'+room.room_id);continue
   if room.printed:refs.append(add(room,room.printed['rect'],'area_label',room.printed['text']))
   if geometric:
    poly=polygons.get(room.room_id)
    if poly is None or scale is None:
     calc['missing_room_ids'].append(room.room_id);continue
    value=poly.area/scale['points_per_metre']**2;used_geometry=True
    refs.append(add(room,poly.bounds,'room_boundary',polygon=poly))
    refs+=calc['calibration']['scale_evidence_ids']
    if room.value is not None and abs(value-room.value)>max(.02*abs(room.value),.01):issues.append('printed_geometry_disagreement:'+room.room_id)
   calc['terms'].append({'room_id':room.room_id,'source_name':room.name['text'] if room.name else None,'source_measurement':room.printed['text'] if room.printed and not geometric else None,'source_unit':'m2','normalized_value':value,'page_index':room.page_index,'value_m2':value,'source_method':'calibrated_geometry' if geometric else 'printed_area','evidence_ids':refs})
   calc['included_room_ids'].append(room.room_id)
  methods={t['source_method'] for t in calc['terms']}
  calc['source_basis']=next(iter(methods)) if len(methods)==1 else 'mixed' if methods else None
  calc['missing_room_ids']=list(dict.fromkeys(calc['missing_room_ids']))
  calc['scope_complete']=bool(calc['terms']) and not issues and not calc['missing_room_ids']
  subtotal=(float(sum((Decimal(str(t['value_m2'])) for t in calc['terms']),Decimal('0'))) if not used_geometry else sum(t['value_m2'] for t in calc['terms'])) if calc['terms'] else None
  metadata['route']='calibrated_geometry' if used_geometry else ('native_printed_sum' if len(requested)>1 else 'native_printed_area')
  basis='calculated' if used_geometry or len(requested)>1 else 'printed_area'
  verification='calculated_from_source' if used_geometry or len(requested)>1 else ('native_source' if calc['terms'] else 'none')
  return result('answered' if calc['scope_complete'] else ('needs_review' if calc['terms'] else 'unsupported'),subtotal,basis,verification)
