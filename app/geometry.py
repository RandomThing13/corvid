"""Bounded vector-PDF polygons and graphic scale calibration; fail closed."""
from collections import defaultdict
import math,re
import pymupdf as fitz
from shapely.geometry import Polygon,Point,box
from app.ingest import extract_native
class GeometryError(ValueError):pass

def path_polygon(path,visible):
 if path.get('type')!='fs' or path.get('fill') is None or path.get('color') is None:return None
 items=path['items'];vertices=[]
 if len(items)==1 and items[0][0]=='re':
  r=items[0][1];vertices=[(r.x0,r.y0),(r.x1,r.y0),(r.x1,r.y1),(r.x0,r.y1)]
 elif items and all(i[0]=='l' for i in items):
  vertices=[tuple(items[0][1])]
  for _,a,b in items:
   if math.dist(vertices[-1],tuple(a))>1e-3:return None
   vertices.append(tuple(b))
  if math.dist(vertices[0],vertices[-1])>1e-3:
   if not path.get('closePath'):return None
  else:vertices=vertices[:-1]
 else:return None
 if len(vertices)<3:return None
 polygon=Polygon(vertices)
 if not polygon.is_valid or polygon.is_empty or polygon.area<=0:return None
 if not box(*visible).buffer(1e-4).covers(polygon):return None
 return polygon

def room_family(page,rooms):
 # Clipping/group operators are not approximated into room boundaries.
 extended=page.get_drawings(extended=True)
 visible=(0,0,page.cropbox.width,page.cropbox.height)
 families=defaultdict(lambda:defaultdict(list))
 anchors=[(r,Point((r.label['rect'][0]+r.label['rect'][2])/2,(r.label['rect'][1]+r.label['rect'][3])/2)) for r in rooms]
 clips={}
 for path in extended:
  level=path.get('level',0)
  if path.get('type')=='clip':
   clips={k:v for k,v in clips.items() if k<level}
   items=path.get('items',[])
   clips[level]=box(*items[0][1]) if len(items)==1 and items[0][0]=='re' else None
   continue
  clips={k:v for k,v in clips.items() if k<level}
  polygon=path_polygon(path,visible)
  if polygon is not None and any(c is None or not c.buffer(1e-4).covers(polygon) for c in clips.values()):continue
  if polygon is None:continue
  contained=[r for r,point in anchors if polygon.contains(point)]
  if len(contained)!=1:continue
  family=(tuple(round(v,5) for v in path['color']),round(path['width'],5))
  families[family][contained[0].room_id].append(polygon)
 ranked=sorted(((len(mapping),family,mapping) for family,mapping in families.items()),key=lambda x:x[0],reverse=True)
 if not ranked:raise GeometryError('no_eligible_room_polygon_family')
 score,family,mapping=ranked[0]
 if len(ranked)>1 and ranked[1][0]==score:raise GeometryError('competing_polygon_families')
 if any(len(polygons)!=1 for polygons in mapping.values()):raise GeometryError('ambiguous_room_polygon_mapping')
 # Every native ID must map, and each polygon must contain one native anchor.
 if score!=len(rooms):raise GeometryError('incomplete_polygon_family_coverage')
 polygons={key:value[0] for key,value in mapping.items()}
 values=list(polygons.values())
 if any(a.intersection(b).area>1e-3 for i,a in enumerate(values) for b in values[i+1:]):raise GeometryError('overlapping_room_polygons')
 return polygons,{'coverage':score,'family':{'stroke_color':family[0],'stroke_width':family[1]}}

def calibrate(page,rooms):
 if not rooms:raise GeometryError('scale_without_room_scope')
 if len({r.room_id.split('.')[0] for r in rooms})!=1:raise GeometryError('multiple_drawing_scopes_for_scale')
 _,spans=extract_native(page);drawings=page.get_drawings();bars=[]
 # Connected, thin filled rectangle segments supply actual tick x coordinates.
 segments=[]
 for path in drawings:
  if path.get('fill') is None:continue
  if len(path['items'])==1 and path['items'][0][0]=='re':
   r=path['items'][0][1]
   if 0<r.height and r.width>=2*r.height:segments.append(r)
 for unit in [s for s in spans if s['text'].strip()=='m']:
  u=fitz.Rect(unit['rect'])
  nearby=[r for r in segments if abs((r.y0+r.y1)/2-(u.y0+u.y1)/2)<=2*u.height and r.x1<=u.x0+u.height and u.x0-r.x1<35*u.height]
  if len(nearby)<2:continue
  # Bar rows must share vertical bounds and form one uninterrupted chain.
  rows=defaultdict(list)
  for r in nearby:rows[(round(r.y0,2),round(r.y1,2))].append(r)
  for rectangles in rows.values():
   rectangles=sorted(rectangles,key=lambda r:r.x0)
   if len(rectangles)<2 or any(abs(a.x1-b.x0)>.02 for a,b in zip(rectangles,rectangles[1:])):continue
   endpoints=[rectangles[0].x0]+[r.x1 for r in rectangles];bar=fitz.Rect(rectangles[0]);
   for r in rectangles:bar|=r
   labels=[]
   for x in endpoints:
    candidates=[]
    for s in spans:
     if not re.fullmatch(r'\d+(?:[.,]\d+)?',s['text'].strip()):continue
     r=fitz.Rect(s['rect']);cx=(r.x0+r.x1)/2
     if abs(cx-x)<=u.height*.3 and 0<=bar.y0-r.y1<=3*u.height:candidates.append(s)
    if len(candidates)!=1:break
    labels.append(candidates[0])
   if len(labels)!=len(endpoints) or len(labels)<3:continue
   numbers=[float(s['text'].replace(',','.')) for s in labels]
   if any(b<=a for a,b in zip(numbers,numbers[1:])):continue
   if max(fitz.Rect(s['rect']).y0 for s in labels)-min(fitz.Rect(s['rect']).y0 for s in labels)>u.height*.2:continue
   ratios=[(endpoints[i+1]-endpoints[i])/(numbers[i+1]-numbers[i]) for i in range(len(numbers)-1)]
   disagreement=(max(ratios)-min(ratios))/min(ratios)
   if disagreement>.005:raise GeometryError('inconsistent_scale_intervals')
   ppm=(endpoints[-1]-endpoints[0])/(numbers[-1]-numbers[0])
   bounds=fitz.Rect(bar)
   for label in labels:bounds|=fitz.Rect(label['rect'])
   bounds|=u
   bars.append({'points_per_metre':ppm,'interval_relative_disagreement':disagreement,'validated':True,'rect':list(bounds),'text':' / '.join(s['text'] for s in labels)+' m','ticks':[{'point':[x,bar.y0],'value_m':v} for x,v in zip(endpoints,numbers)],'intervals':ratios})
 if len(bars)!=1:raise GeometryError('missing_or_multiple_graphic_scales')
 # One coherent room-label scope on a single selected page is required by caller.
 if not rooms:raise GeometryError('scale_without_room_scope')
 return bars[0]
