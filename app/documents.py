"""Bounded content-addressed document ingest and page rendering."""
import hashlib,io,math,warnings,os
from pathlib import Path
import pymupdf as fitz
from PIL import Image,ImageOps
from app.schemas import Document,Page
from app import storage
ROOT=Path(os.environ.get('STOA_DOCUMENT_ROOT','data/processed/documents'))
MAX_BYTES=25*1024*1024
class InputError(ValueError):pass
def digest(data):return hashlib.sha256(data).hexdigest()
def directory(id):
 if len(id)!=64 or any(c not in '0123456789abcdef' for c in id):raise InputError('invalid_document_id')
 return ROOT/id
def ingest(data):
 if len(data)>MAX_BYTES:raise InputError('upload_limit_25_MiB')
 sha=digest(data);folder=directory(sha);pages=[]
 try:
  if data.startswith(b'%PDF-'):
   with fitz.open(stream=data,filetype='pdf') as d:
    if d.needs_pass or not 1<=len(d)<=20:raise InputError('PDF_must_have_1_to_20_unencrypted_pages')
    # Preflight all dimensions before generating artifacts.
    for p in d:
     if p.rect.is_empty or p.rect.is_infinite:raise InputError('invalid_page_geometry')
    folder.mkdir(parents=True,exist_ok=True);(folder/'source.pdf').write_bytes(data)
    for p in d:
     scale=min(2,math.sqrt(7_900_000/(p.rect.width*p.rect.height)))
     pix=p.get_pixmap(matrix=fitz.Matrix(scale,scale),alpha=False,annots=False)
     if pix.width*pix.height>8_000_000:raise InputError('render_limit_8_MP')
     image=pix.tobytes('png');(folder/f'{p.number}.png').write_bytes(image)
     pages.append(Page(page_index=p.number,width=pix.width,height=pix.height,image_url=f'/documents/{sha}/pages/{p.number}/image',render_sha256=digest(image),transform={'native_space':'PyMuPDF unrotated CropBox-relative points','cropbox':list(p.cropbox),'mediabox':list(p.mediabox),'cropbox_position':list(p.cropbox_position),'raw_pdf_to_native':list(p.transformation_matrix),'rotation':p.rotation,'rotation_matrix':list(p.rotation_matrix),'render_matrix':[scale,0,0,scale,0,0],'pixmap_origin':[pix.x,pix.y]}))
   media='application/pdf'
  else:
   with warnings.catch_warnings():
    warnings.simplefilter('error',Image.DecompressionBombWarning)
    with Image.open(io.BytesIO(data)) as im:
     if im.format not in ('PNG','JPEG'):raise InputError('supported_formats_PDF_PNG_JPEG')
     if im.width*im.height>30_000_000:raise InputError('decoded_image_limit_30_MP')
     if getattr(im,'n_frames',1)!=1:raise InputError('multi_frame_image_unsupported')
     original=list(im.size);orientation=int(im.getexif().get(274,1));im=ImageOps.exif_transpose(im).convert('RGB');oriented=list(im.size)
     im.thumbnail((int(im.width*min(1,math.sqrt(7_900_000/(im.width*im.height)))),int(im.height*min(1,math.sqrt(7_900_000/(im.width*im.height))))))
     folder.mkdir(parents=True,exist_ok=True);im.save(folder/'0.png');image=(folder/'0.png').read_bytes()
     pages=[Page(page_index=0,width=im.width,height=im.height,image_url=f'/documents/{sha}/pages/0/image',render_sha256=digest(image),transform={'original_size':original,'exif_orientation':orientation,'exif_oriented_size':oriented,'display_size':list(im.size),'coordinate_space':'normalized top-left displayed image'})]
   media='image/png'
 except InputError:raise
 except Exception as exc:raise InputError('corrupt_or_unsupported_document') from exc
 result=Document(document_id=sha,sha256=sha,media_type=media,pages=pages);storage.put('documents',sha,result.model_dump());return result

def load(id):
 directory(id);body=storage.get('documents',id)
 if not body:raise InputError('document_not_found')
 return Document.model_validate(body)
def selected(doc,request):
 indices=request.page_indices if request.page_indices is not None else ([request.page_index] if request.page_index is not None else list(range(len(doc.pages))))
 if len(indices)>4:raise InputError('select_up_to_four_pages_explicitly')
 if any(i>=len(doc.pages) for i in indices):raise InputError('page_out_of_scope')
 return [doc.pages[i] for i in indices]
