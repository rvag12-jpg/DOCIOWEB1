from pathlib import Path
from uuid import uuid4
from fastapi import APIRouter,HTTPException,Request,status
from app.core.config import settings
from app.models import DocumentView,PageView,SegmentUpdate
from app.services.pdf_renderer import PdfRenderingError,render_pdf
from app.services.segmentation import fixed_size_segments,manual_segments,pending_segment,SegmentationError
from app.storage import store
router=APIRouter(prefix='/documents',tags=['documents'])
def process_pdf(i,d,p,filename,pps):
 rendered=render_pdf(p,d/'pages',settings.pdf_dpi); pages=[PageView(page_number=n,image_url=f'/media/{i}/pages/{x.name}') for n,x in enumerate(rendered,1)]; segments=fixed_size_segments(pages,pps) if pps else pending_segment(pages); doc=DocumentView(document_id=i,original_filename=filename,page_count=len(pages),pages=pages,segments=segments); store.save_manifest(doc); return doc
@router.post('/chunked/init')
def init():
 i=uuid4().hex; (settings.data_dir/'uploads'/i).mkdir(parents=True,exist_ok=False); return {'upload_id':i}
@router.post('/chunked/{upload_id}/part/{chunk_index}')
async def part(upload_id:str,chunk_index:int,request:Request):
 d=settings.data_dir/'uploads'/upload_id
 if not d.is_dir() or chunk_index<0: raise HTTPException(404,'Subida no encontrada')
 body=await request.body()
 if not body: raise HTTPException(400,'Fragmento vacío')
 if sum(x.stat().st_size for x in d.glob('*.part'))+len(body)>settings.max_upload_mb*1024*1024: raise HTTPException(413,'PDF demasiado grande')
 (d/f'{chunk_index:08d}.part').write_bytes(body); return {'chunk_index':chunk_index,'bytes_received':len(body)}
@router.post('/chunked/{upload_id}/complete',response_model=DocumentView,status_code=status.HTTP_201_CREATED)
async def complete(upload_id:str,request:Request):
 d=settings.data_dir/'uploads'/upload_id
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
