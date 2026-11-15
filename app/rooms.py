"""Native room labels and conservative full-question area scope parsing."""
from dataclasses import dataclass
import re
import unicodedata
import pymupdf as fitz
from app.ingest import extract_native,locate_printed_area,DocumentError
ID_PATTERN=r'\d+\.\d{2}'
@dataclass
class Room:
 room_id:str
 page_index:int
 label:dict
 name:dict|None
 printed:dict|None
 value:float|None

def records(page):
 words,spans=extract_native(page);result=[]
 for label in spans:
  text=label['text'].strip()
  named=re.fullmatch(r'(?:Room|Raum)\s+([A-Za-z][\w-]*)',text,re.I)
  if not re.fullmatch(ID_PATTERN,text) and not named:continue
  identifier=named[1] if named else text
  rect=fitz.Rect(label['rect']);cx=(rect.x0+rect.x1)/2
  names=[]
  for s in spans:
   r=fitz.Rect(s['rect']);gap=rect.y0-r.y1
   if re.search(r'[A-Za-zÀ-ÿ]',s['text']) and not re.search(r'm[²2]|\d',s['text']) and -.1*rect.height<=gap<=rect.height and r.x0<=cx<=r.x1:names.append((abs(gap),s))
  name=min(names,key=lambda x:x[0])[1] if names else None
  try:_,printed,value=locate_printed_area(words if not named else [{'text':text,'rect':label['rect']}],spans,text)
  except DocumentError:printed,value=None,None
  result.append(Room(identifier,page.number,label,name,printed,value))
 return result

ID_TOKEN = r'(?<![\w.])\d+\.\d{2}(?![\w]|\.\d)'

def legacy_scope(question):
 q=question.lower()
 if not re.search(r'area|size|fläche|flaeche|gross|groß|square met|quadratmeter|m²',q):return None
 printed=bool(re.search(r'printed|gedruck|aufgedruck|beschrift',q))
 geometric=bool(re.search(r'geometr|polygon',q))
 method='printed' if printed else 'geometry' if geometric else 'auto'
 def unsupported(reason,ids=None):return {'operation':'unsupported','ids':ids or [],'requested_method':method,'reason':reason}
 if printed and geometric:return unsupported('conflicting_requested_methods')
 if re.search(r'compar|differen|subtract|minus|average|mean\b|ratio|larger|smaller|größer|grösser|kleiner|vergleich|durchschnitt|unterschied|umfang|volume|perimeter|divid|multipl|\btimes\b|double|twice|half|halve|percent|prozent|geteilt|\bmal\b|doppelt|halb|remov|deduct|abzieh|entfern|[*/%−–—-]',q):return unsupported('unsupported_area_operation_or_modifier')
 if re.search(r'square feet|square foot|sq\.?\s*ft|feet|foot|ft[²2]|inch|cm[²2]|mm[²2]|convert|conversion|umrechn',q):return unsupported('unsupported_area_unit_conversion')
 ids=re.findall(ID_TOKEN,question)
 # Bare numeric tokens and explicit named operands must have the entire ID shape.
 decimals=re.findall(r'(?<![\w.])\d+\.\w+(?:\.\w+)*',question)
 if any(not re.fullmatch(ID_PATTERN,t) for t in decimals):return unsupported('invalid_room_identifier_token')
 explicit=re.findall(r'\b(?:room|raum)\s+([^\s,;?]+)',question,re.I)
 for token in explicit:
  token=token.rstrip('.?!:;')
  if not re.fullmatch(ID_PATTERN,token):return unsupported('unsupported_room_identifier',ids)
 if len(set(ids))!=len(ids):return unsupported('duplicate_requested_operands',list(dict.fromkeys(ids)))
 total=bool(re.search(r'all\b|whole|entire|alle[nr]?\b|gesamt.*(?:geschoss|etage)|total.*floor',q))
 if total and ids and re.search(r'floor|page|geschoss|etage|seite',q):return unsupported('unresolved_floor_exclusion_or_subset',ids)
 if not ids and total:return {'operation':'indoor_floor_total','ids':[],'requested_method':method,'indoor':bool(re.search(r'indoor|net\b|netto|excluding|ohne|innen',q))}
 if ids and re.search(r'exclud|except|without|ohne|außer|ausser|not\b',q):return unsupported('unsupported_explicit_room_exclusion',ids)
 if len(ids)==1 and re.search(r'\band\b|\bund\b|\bplus\b|\+',q):return unsupported('missing_room_operand',ids)
 if not ids:return unsupported('explicit_room_ids_or_complete_floor_scope_required')
 if re.search(r'(?:room|raum)\s*[?.,]?\s*$',q):return unsupported('missing_room_operand',ids)
 if len(ids)>1 and not re.search(r'combin|sum\b|total|add|gesamt|summe|zusammen|\+',q):return unsupported('explicit_sum_operation_required',ids)
 first=re.search(ID_TOKEN,question)
 if first is None:return unsupported('invalid_room_identifier_token')
 tail=question[first.start():].lower()
 tail=re.sub(ID_TOKEN,' ',tail)
 tail=re.sub(r'\b(?:rooms?|raum|räume|räumen|and|und|plus|together|zusammen)\b',' ',tail)
 tail=re.sub(r'(?:\bin\s+)?(?:m[²2]|square\s+met(?:er|re)s?|quadratmetern?)',' ',tail)
 tail=re.sub(r'\b(?:from|using|aus|mit)\s+(?:geometry|geometrie|polygons?)\b',' ',tail)
 # A quoted source room-name descriptor is allowed; it is not another operand.
 tail=re.sub(r'\(\s*[«“\"]?[^()0-9]+?[»”\"]?\s*\)',' ',tail)
 if re.search(r'[\wÀ-ÿ]',tail):return unsupported('unparsed_area_operand_or_modifier',ids)
 return {'operation':'sum' if len(ids)>1 else 'single_room','ids':ids,'requested_method':method}


AREA_UNIT = r'(?:m²|m\^?2|sqm|square\s+met(?:er|re)s?|quadratmetern?)'
def normalize_name(text):
 return ' '.join(unicodedata.normalize('NFKC',text).casefold().strip(' .?!:;«»"').split())
ALIASES = {'kitchen':{'küche','cuisine','cucina'},'living room':{'wohnen','wohnen/essen','séjour','soggiorno'},'bathroom':{'bad','bagno','salle de bain'},'bedroom':{'schlafzimmer'},'corridor':{'korridor','flur'}}

def parse_scope(question):
 q=question.casefold()
 if re.search(r'how many|count\b|kuinka monta|wie viele',q):return None
 if not re.search(r'area|size|fläche|flaeche|gross|groß|'+AREA_UNIT,q):return None
 method='printed' if re.search(r'printed|gedruck|aufgedruck|beschrift',q) else 'geometry' if re.search(r'geometr|polygon',q) else 'auto'
 def fail(reason,ids=None):return {'operation':'unsupported','ids':ids or [],'references':[],'requested_method':method,'requested_units':'m2','reason':reason}
 if re.search(r'printed|gedruck',q) and re.search(r'geometr|polygon',q):return fail('conflicting_requested_methods')
 if re.search(r'compar|differen|subtract|minus|average|mean\b|ratio|larger|smaller|größer|kleiner|vergleich|durchschnitt|unterschied|umfang|volume|perimeter|divid|multipl|\btimes\b|double|twice|half|percent|prozent|geteilt|\bmal\b|doppelt|halb|remov|deduct|abzieh|entfern|[*/%−–—-]',q):return fail('unsupported_area_operation_or_modifier')
 if re.search(r'square feet|square foot|sq\.?\s*ft|feet|foot|ft[²2]|inch|cm[²2]|mm[²2]|convert|conversion|umrechn',q):return fail('unsupported_area_unit_conversion')
 if re.search(r'these (?:two|selected) rooms|selected rooms|diese.*räume',q):return fail('selection_context_missing_use_explicit_room_ids_or_names')
 # Preserve source IDs verbatim, including decimal points.
 if any(not re.fullmatch(ID_PATTERN,t.rstrip('.')) for t in re.findall(r'(?<![\w.])\d+\.\w+(?:\.\w+)*',question)):return fail('invalid_room_identifier_token')
 body=None
 m=re.search(r'(?:areas?|size|fläche|flächen|flaeche|'+AREA_UNIT+r')\s+(?:of|for|von|der)\s+(.+)',q)
 if m:body=m[1]
 elif re.search(ID_TOKEN,q):body=q[re.search(ID_TOKEN,q).start():]
 if body is None:
  # Whole floor is considered only after no explicit subset was found.
  old=legacy_scope(question)
  return old if old and old['operation']=='indoor_floor_total' else fail('explicit_room_ids_or_names_required')
 if re.search(r'^(?:all|whole|entire|alle[nr]?)\b',body):return legacy_scope(question)
 if re.search(r'exclud|except|without|ohne|außer|ausser|\bnot\b',q):return fail('unsupported_explicit_room_exclusion')
 body=re.sub(r'\([^()]*\)','',body)
 body=re.sub(r'\b(?:from|using|aus|mit)\s+(?:geometry|geometrie|polygons?)','',body)
 body=re.sub(r'(?:[,;.!?]\s*)?(?:please|thanks|thank you|bitte|danke)[.!?\s]*$','',body).strip()
 body=body.rstrip(' ,;.!?')
 body=re.sub(r'(?:\s+in)?\s+'+AREA_UNIT+r'[.!?\s]*$','',body).strip(' .?!:;')
 parts=re.split(r'\s+(?:and|und|plus|together with)\s+|\s*\+\s*|\s*,\s*',body)
 refs=[]
 for part in parts:
  part=re.sub(r'^(?:the\s+)?(?:rooms?|raum|räume|räumen)\s+','',part.strip())
  part=re.sub(r'^the\s+','',part).strip(' .?!:;')
  part=re.sub(r'\s+(?:together|zusammen)$','',part)
  if not part:return fail('missing_room_operand')
  if len(part)>60 or re.search(r'\b(?:please|after|before|excluding)\b',part):return fail('unparsed_area_operand_or_modifier')
  refs.append(part)
 if len(set(refs))!=len(refs):return fail('duplicate_requested_operands',list(dict.fromkeys(refs)))
 return {'operation':'sum' if len(refs)>1 else 'single_room','ids':[r for r in refs if re.fullmatch(ID_PATTERN,r)],'references':refs,'requested_method':method,'requested_units':'m2','requested_scope':'selected_pages'}

def resolve_references(refs,rooms):
 resolved=[];problems=[];candidates={}
 for ref in refs:
  exact=[r for r in rooms if normalize_name(r.room_id)==normalize_name(ref)]
  matches=exact or [r for r in rooms if r.name and normalize_name(r.name['text'])==normalize_name(ref)]
  if not matches:
   aliases=ALIASES.get(normalize_name(ref),set())
   matches=[r for r in rooms if r.name and normalize_name(r.name['text']) in aliases]
  if len(matches)!=1:
   problems.append(('ambiguous_room_reference:' if matches else 'missing_room_reference:')+ref)
   candidates[ref]=[r.room_id for r in matches]
  elif matches[0].room_id in resolved:problems.append('duplicate_resolved_room:'+matches[0].room_id)
  else:resolved.append(matches[0].room_id)
 return resolved,problems,candidates
