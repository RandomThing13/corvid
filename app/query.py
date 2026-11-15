"""Source-scoped query assembly. No label or evaluation imports."""
import re,time,uuid
from PIL import Image,ImageDraw
import pymupdf as fitz
from app import documents,storage,provider,ingest
from app.schemas import Answer,Evidence,Detection

def assemble(proposed,doc,pages,id,meta):
 meta={**meta,'raw_provider_candidate':{'status':proposed.status,'value':proposed.value,'unit':proposed.unit}}
 evidence=[];detections=[];allowed={p.page_index:p for p in pages}
 for i,box in enumerate(proposed.detections):
  if box.page_index not in allowed:raise ValueError('model_page_out_of_scope')
  eid=f'{id}-e{i}'
  e=Evidence(evidence_id=eid,document_id=doc.document_id,source_sha256=doc.sha256,page_index=box.page_index,bbox=box.bbox,method='model_proposed',original_text=box.original_text)
  evidence.append(e);detections.append(Detection(detection_id=f'd{i}',category=box.category,evidence_id=eid))
 status=proposed.status;raw=None;tally=None
 if not proposed.detections_complete and status=='answered':status='needs_review'
 if proposed.unit=='count' and proposed.value is not None:
  if not isinstance(proposed.value,(float,int)) or proposed.value<0 or not float(proposed.value).is_integer():raise ValueError('invalid_integer_count')
  raw=int(proposed.value);tally=len(detections)
  if tally!=raw or not proposed.detections_complete or tally==0:status='needs_review'
 if (not evidence or proposed.value is None or proposed.unit=='unknown') and status=='answered':status='needs_review'
 answer=Answer(run_id=id,status=status,value=proposed.value,unit=proposed.unit,basis=proposed.basis,evidence=evidence,source_evidence_ids=[e.evidence_id for e in evidence],detections=detections,raw_model_count=raw,evidence_tally=tally,counting_rule=proposed.counting_rule,assumptions=proposed.assumptions,missing_inputs=proposed.missing_inputs,verification='model_proposed_unverified' if evidence else 'none',metadata=meta)
 return answer

def native(request,doc,pages,id):
 from app.area import route
 answer=route(request,doc,pages,id)
 return answer if answer is not None else Answer(run_id=id,status='unsupported',missing_inputs=['native_supports_area_scope_only'],metadata={'route':'native_unsupported','attempts':0,'cost_usd':0,'incremental_cost_usd':0})

def execute(request):
 start=time.monotonic();id=uuid.uuid4().hex;doc=documents.load(request.document_ids[0]);pages=documents.selected(doc,request)
 key=provider.hash_json({'request':request.model_dump(exclude={'use_cache'}),'source':doc.sha256,'pages':[p.model_dump() for p in pages],'version':provider.VERSION,'routing_version':'Corvid-area-v1','schema':Answer.model_json_schema(),'provider_schema':provider.ProviderAnswer.model_json_schema(),'prompt':provider.PROMPT,'effort':'medium'})
 old=storage.cached(key) if request.use_cache else None
 if old:
  answer=Answer.model_validate(old);origin=answer.run_id;answer.run_id=id;answer.metadata={**answer.metadata,'cache_hit':True,'original_run_id':origin,'incremental_cost_usd':0,'attempts':0}
 else:
  answer=None
  if request.mode in ('auto','native'):
   from app.area import route
   answer=route(request,doc,pages,id)
   if answer is None and request.mode=='native':answer=native(request,doc,pages,id)
  if answer is None:
   answer=visual(request,doc,pages,id)
 answer.metadata.update({'cache_hit':bool(old),'elapsed_ms':(time.monotonic()-start)*1000,'selected_pages':[p.page_index for p in pages],'document_id':doc.document_id,'budget':storage.totals()})
 # Overlays are already in normalized displayed-page coordinates.
 urls=[]
 for p in pages:
  boxes=[e for e in answer.evidence if e.page_index==p.page_index]
  if not boxes:continue
  with Image.open(documents.directory(doc.document_id)/f'{p.page_index}.png') as im:
   im=im.convert('RGB');draw=ImageDraw.Draw(im)
   for i,e in enumerate(boxes):
    if e.polygon:
     draw.line([(x*im.width,y*im.height) for x,y in e.polygon]+[(e.polygon[0][0]*im.width,e.polygon[0][1]*im.height)],fill='red',width=3)
    else:
     a,b,c,d=e.bbox;draw.rectangle([a*im.width,b*im.height,c*im.width,d*im.height],outline='red',width=2)
    draw.text((e.bbox[0]*im.width,e.bbox[1]*im.height),str(i+1),fill='blue')
   folder=documents.ROOT.parent/'overlays';folder.mkdir(exist_ok=True);im.save(folder/f'{id}-{p.page_index}.png')
  urls.append(f'/runs/{id}/pages/{p.page_index}/overlay')
 answer.metadata['overlay_urls']=urls
 storage.put('runs',id,answer.model_dump(),key if answer.status=='answered' and not old else None)
 return answer

def visual(request,doc,pages,id):
  proposed,meta=provider.invoke(request,doc,pages,id)
  if proposed is None:answer=Answer(run_id=id,status='error',missing_inputs=[meta.get('error','provider_failure')],metadata=meta)
  else:
   try:answer=assemble(proposed,doc,pages,id,meta)
   except ValueError:answer=Answer(run_id=id,status='error',missing_inputs=['invalid_model_evidence_or_value'],metadata=meta)
  answer.metadata.setdefault('route','direct_vlm')
  return answer
