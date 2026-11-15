"""P01 public contracts. No server provenance is model-authored."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
ModelName=Literal['gpt-6.1-sol','gpt-6-luna']
class Strict(BaseModel):
 model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
class Page(Strict):
 page_index:int
 width:int
 height:int
 image_url:str
 render_sha256:str
 transform:dict
class Document(Strict):
 document_id:str
 sha256:str
 media_type:str
 pages:list[Page]
class Evidence(Strict):
 evidence_id:str
 document_id:str
 source_sha256:str
 page_index:int=Field(ge=0)
 bbox:list[float]=Field(min_length=4,max_length=4)
 method:Literal['native','model_proposed']
 original_text:str|None=None
 native_rect:list[float]|None=None
 transform:dict|None=None
 polygon:list[list[float]]|None=None
 polygon_native:list[list[float]]|None=None
 role:Literal['room_boundary','room_label','area_label','scale_bar']|None=None
 @model_validator(mode='after')
 def box(self):
  a,b,c,d=self.bbox
  if not (0<=a<c<=1 and 0<=b<d<=1):raise ValueError('bbox must have positive area within [0,1]')
  if self.polygon is not None:
   if len(self.polygon)<3 or any(len(p)!=2 or not all(0<=v<=1 for v in p) for p in self.polygon):raise ValueError('Invalid normalized polygon')
  return self
class Detection(Strict):
 detection_id:str
 category:str
 evidence_id:str
class QueryRequest(Strict):
 document_ids:list[str]=Field(min_length=1,max_length=1)
 question:str=Field(min_length=1,max_length=4000)
 page_index:int|None=Field(default=None,ge=0)
 page_indices:list[int]|None=Field(default=None,min_length=1,max_length=4)
 mode:Literal['auto','direct_vlm','native']='auto'
 runtime_model:ModelName='gpt-6.1-sol'
 use_cache:bool=True
 @model_validator(mode='after')
 def scope(self):
  if self.page_index is not None and self.page_indices is not None:raise ValueError('Choose page_index or page_indices')
  if self.page_indices and (min(self.page_indices)<0 or len(set(self.page_indices))!=len(self.page_indices)):raise ValueError('Invalid page selection')
  return self
class ProposedBox(Strict):
 page_index:int
 bbox:list[float]=Field(min_length=4,max_length=4)
 category:str
 original_text:str|None
class ProviderAnswer(Strict):
 status:Literal['answered','needs_review','unsupported']
 value:float|str|None
 unit:Literal['count','m2','m','m3','text','unknown']
 basis:Literal['printed_area','model_visual','unknown']
 detections:list[ProposedBox]
 detections_complete:bool
 counting_rule:str
 assumptions:list[str]
 missing_inputs:list[str]
class Answer(Strict):
 run_id:str
 status:Literal['answered','needs_review','unsupported','error']
 value:int|float|str|None=None
 unit:Literal['count','m2','m','m3','text','unknown']='unknown'
 basis:Literal['printed_area','model_visual','native_text','calculated','unknown']='unknown'
 source_evidence_ids:list[str]=Field(default_factory=list)
 evidence:list[Evidence]=Field(default_factory=list)
 detections:list[Detection]=Field(default_factory=list)
 raw_model_count:int|None=None
 evidence_tally:int|None=None
 counting_rule:str=''
 assumptions:list[str]=Field(default_factory=list)
 missing_inputs:list[str]=Field(default_factory=list)
 verification:Literal['native_source','calculated_from_source','model_proposed_unverified','none']='none'
 metadata:dict=Field(default_factory=dict)
 @model_validator(mode='after')
 def references(self):
  ids={e.evidence_id for e in self.evidence}
  if any(i not in ids for i in self.source_evidence_ids) or any(d.evidence_id not in ids for d in self.detections):raise ValueError('Unresolved evidence reference')
  if self.unit=='count' and self.value is not None:
   if not isinstance(self.value,(float,int)) or self.value<0 or not float(self.value).is_integer():raise ValueError('Count must be nonnegative integer')
   self.value=int(self.value)
  if self.status=='answered' and not self.evidence:raise ValueError('Answered requires source evidence')
  return self
