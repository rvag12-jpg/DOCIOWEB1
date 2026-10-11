from pathlib import Path
from uuid import uuid4
from threading import Lock
from PIL import Image,ImageOps,UnidentifiedImageError
from fastapi import APIRouter,HTTPException,Request,status
from app.core.config import settings
from app.models import DocumentView,PageView,SegmentUpdate,StudentSegment
from app import repository as repo
from app.services.pdf_renderer import PdfRenderingError,render_pdf
from app.services.segmentation import fixed_size_segments,manual_segments,pending_segment,SegmentationError
from app.storage import store
router=APIRouter(prefix='/documents',tags=['documents'])
image_lock=Lock()
def upload_dir(upload_id):
 if len(upload_id)!=32 or any(c not in '0123456789abcdef' for c in upload_id): raise HTTPException(404,'Subida no encontrada')
 return settings.data_dir/'uploads'/upload_id
@router.get('')
def list_documents():
 result=[]
 for manifest in store.root.glob('*/manifest.json'):
  try:
   doc=store.load_manifest(manifest.parent.name)
   result.append({'document_id':doc.document_id,'original_filename':doc.original_filename,'created_at':doc.created_at.isoformat(),
                  'page_count':doc.page_count,'segments':[{'student_key':s.student_key,'start_page':s.start_page,'end_page':s.end_page} for s in doc.segments]})
  except (ValueError,FileNotFoundError): continue
 return sorted(result,key=lambda d:d['created_at'],reverse=True)[:100]
def process_pdf(i,d,p,filename,pps):
 rendered=render_pdf(p,d/'pages',settings.pdf_dpi); pages=[PageView(page_number=n,image_url=f'/media/{i}/pages/{x.name}') for n,x in enumerate(rendered,1)]; segments=fixed_size_segments(pages,pps) if pps else pending_segment(pages); doc=DocumentView(document_id=i,original_filename=filename,page_count=len(pages),pages=pages,segments=segments); store.save_manifest(doc); return doc
@router.post('/chunked/init')
def init():
 i=uuid4().hex; (settings.data_dir/'uploads'/i).mkdir(parents=True,exist_ok=False); return {'upload_id':i}
@router.post('/chunked/{upload_id}/part/{chunk_index}')
async def part(upload_id:str,chunk_index:int,request:Request):
 d=upload_dir(upload_id)
 if not d.is_dir() or chunk_index<0: raise HTTPException(404,'Subida no encontrada')
 body=await request.body()
 if not body: raise HTTPException(400,'Fragmento vacío')
 if len(body)>1024*1024: raise HTTPException(413,'El fragmento supera 1 MB')
 if sum(x.stat().st_size for x in d.glob('*.part'))+len(body)>settings.max_upload_mb*1024*1024: raise HTTPException(413,'PDF demasiado grande')
 (d/f'{chunk_index:08d}.part').write_bytes(body); return {'chunk_index':chunk_index,'bytes_received':len(body)}
@router.post('/chunked/{upload_id}/complete',response_model=DocumentView,status_code=status.HTTP_201_CREATED)
async def complete(upload_id:str,request:Request):
 d=upload_dir(upload_id)
 if not d.is_dir(): raise HTTPException(404,'Subida no encontrada')
 m=await request.json(); filename=Path(str(m.get('filename') or 'document.pdf')).name; pps=m.get('pages_per_student'); size=int(m.get('size') or 0); chunks=int(m.get('chunks') or 0)
 if Path(filename).suffix.lower()!='.pdf': raise HTTPException(415,'Solo se admiten PDF')
 if pps is not None: pps=int(pps)
 parts=sorted(d.glob('*.part'))
 if len(parts)!=chunks: raise HTTPException(409,f'Fragmentos incompletos: {len(parts)}/{chunks}')
 i,dd=store.create(); pdf=dd/'source.pdf'
 try:
  total=0
  with pdf.open('wb') as out:
   for x in parts: data=x.read_bytes(); total+=len(data); out.write(data)
  if size and total!=size: raise HTTPException(409,f'Tamaño reconstruido incorrecto: {total}/{size}')
  return process_pdf(i,dd,pdf,filename,pps)
 except PdfRenderingError as exc: store.remove(i); raise HTTPException(422,f'No se pudo procesar el PDF: {exc}') from exc
 finally:
  for x in d.glob('*.part'): x.unlink(missing_ok=True)
  if d.exists(): d.rmdir()
@router.post('/chunked/{upload_id}/image-complete',response_model=DocumentView,status_code=status.HTTP_201_CREATED)
async def complete_image(upload_id:str,request:Request):
 d=upload_dir(upload_id)
 if not d.is_dir(): raise HTTPException(404,'Subida no encontrada')
 metadata=await request.json(); sid=metadata.get('student_id'); target=metadata.get('document_id')
 if not isinstance(sid,str) or not repo.get_record('students',sid): raise HTTPException(422,'Seleccione un student_id registrado')
 size=metadata.get('size'); chunks=metadata.get('chunks'); parts=sorted(d.glob('*.part'))
 if not isinstance(size,int) or not 0<size<=20*1024*1024: raise HTTPException(413,'Cada imagen debe ocupar entre 1 byte y 20 MB')
 if not isinstance(chunks,int) or chunks<1 or [p.name for p in parts]!=[f'{n:08d}.part' for n in range(chunks)]: raise HTTPException(409,'Fragmentos de imagen incompletos')
 source=d/'image-upload'; created=None
 try:
  with source.open('wb') as output:
   for part in parts: output.write(part.read_bytes())
  if source.stat().st_size!=size: raise HTTPException(409,'Tamaño reconstruido de imagen incorrecto')
  with Image.open(source) as image:
   if image.format not in ('JPEG','PNG','WEBP'): raise HTTPException(415,'Solo se admiten JPEG, PNG o WebP')
   if image.width*image.height>40_000_000: raise HTTPException(413,'La imagen supera 40 megapíxeles')
   clean=ImageOps.exif_transpose(image).convert('RGB'); clean.thumbnail((3000,3000))
   with image_lock:
    if target:
     doc=store.load_manifest(target)
     if len(doc.segments)!=1 or doc.segments[0].student_key!=sid: raise HTTPException(422,'El documento de destino pertenece a otro alumno o contiene varios segmentos')
     if doc.page_count>=12: raise HTTPException(422,'Máximo de 12 imágenes por alumno')
    else:
     created,directory=store.create(); doc=DocumentView(document_id=created,original_filename=f'Imágenes · {sid}',page_count=0,pages=[],segments=[])
    number=doc.page_count+1; name=f'page-{number:04d}.jpg'
    clean.save(store.document_dir(doc.document_id)/'pages'/name,'JPEG',quality=92)
    doc.pages.append(PageView(page_number=number,image_url=f'/media/{doc.document_id}/pages/{name}')); doc.page_count=number
    doc.segments=[StudentSegment(student_key=sid,label=sid,start_page=1,end_page=number,pages=doc.pages)]
    store.save_manifest(doc)
   return doc
 except FileNotFoundError as error: raise HTTPException(404,'Documento de destino no encontrado') from error
 except (UnidentifiedImageError,Image.DecompressionBombError,OSError) as error:
  if created: store.remove(created)
  raise HTTPException(422,'La imagen no se puede leer con fiabilidad') from error
 finally:
  for part in parts: part.unlink(missing_ok=True)
  source.unlink(missing_ok=True)
  if d.exists(): d.rmdir()
@router.get('/{document_id}',response_model=DocumentView)
def get(document_id:str):
 try:return store.load_manifest(document_id)
 except FileNotFoundError as exc:raise HTTPException(404,'Documento no encontrado') from exc
@router.put('/{document_id}/segments',response_model=DocumentView)
def segments(document_id:str,update:SegmentUpdate):
 try:
  doc=store.load_manifest(document_id); doc.segments=manual_segments(doc.pages,update.ranges); store.save_manifest(doc); return doc
 except FileNotFoundError as exc: raise HTTPException(404,'Documento no encontrado') from exc
 except SegmentationError as exc: raise HTTPException(422,str(exc)) from exc

