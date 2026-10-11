import hmac
import os
from fastapi import APIRouter, Header, HTTPException
from PIL import Image,ImageDraw,ImageFont
from app import repository as repo
from app.storage import store
from app.models import DocumentView,PageView,StudentSegment
from app.services import ai_jobs,ai_provider
from app.services.corrector import VERSION,framework_template

router=APIRouter(prefix='/ai',tags=['corrector'])


def require_access(authorization):
    if not ai_provider.configuration()['access_required']: return
    token=os.getenv('DOCIO_AI_ACCESS_TOKEN','')
    if not ai_provider.configuration()['access_configured']: raise HTTPException(503,'El acceso a la corrección IA no está configurado en el servidor')
    if not authorization or not hmac.compare_digest(authorization,'Bearer '+token):
        raise HTTPException(401,'Introduzca el código de acceso a la corrección IA')


@router.get('/config')
def config():
    return {**ai_provider.configuration(),'corrector_version':VERSION,'max_pages_per_student':12,'max_students':int(os.getenv('DOCIO_AI_MAX_STUDENTS','40')),
            'teacher_validation_required':True}


@router.get('/framework/{assessment_id}')
def framework(assessment_id:str):
    assessment=repo.get_record('assessments',assessment_id)
    if not assessment: raise HTTPException(404,'Plantilla no encontrada')
    group=repo.get_record('groups',assessment['group_id']) or {}
    return framework_template(assessment,group,ai_provider.configuration()['simulated'] and repo.DEMO_MODE)


@router.post('/jobs',status_code=201)
def create(item:ai_jobs.JobIn,authorization:str|None=Header(default=None)):
    require_access(authorization)
    job=ai_jobs.create_job(item)
    if job['status']=='queued': ai_jobs.enqueue(job['job_id'])
    return ai_jobs.summary(job)


@router.get('/jobs')
def jobs(authorization:str|None=Header(default=None)):
    require_access(authorization)
    return [ai_jobs.summary(job) for job in repo.list_records('ai_jobs',30)]


@router.get('/jobs/{job_id}')
def job(job_id:str,authorization:str|None=Header(default=None)):
    require_access(authorization)
    found=repo.get_record('ai_jobs',job_id)
    if not found: raise HTTPException(404,'Lote no encontrado')
    if found['status']=='queued': ai_jobs.enqueue(job_id)
    return ai_jobs.summary(found)


@router.post('/jobs/{job_id}/retry')
def retry(job_id:str,authorization:str|None=Header(default=None)):
    require_access(authorization)
    found=ai_jobs.retry_job(job_id)
    ai_jobs.enqueue(job_id)
    return ai_jobs.summary(found)


@router.post('/demo-images',status_code=201)
def demo_images():
    if not repo.DEMO_MODE: raise HTTPException(404,'Solo disponible en demostración')
    document_id,directory=store.create()
    pages,segments=[],[]
    for number in range(1,4):
        sid=f'DEMO-{number:03d}'
        image=Image.new('RGB',(900,1200),'white'); draw=ImageDraw.Draw(image)
        font=ImageFont.load_default(size=26)
        draw.multiline_text((60,70),f'DOCIOWEB1 - EJEMPLO FICTICIO\n\nAlumno: {sid}\n\nEsta imagen sirve para comprobar el flujo.\nNo contiene una prueba ni datos reales.\n\nQ1. Respuesta inventada de demostracion.\nQ2. Segunda respuesta inventada.\n\nSIMULACION - SIN VALOR ACADEMICO',font=font,fill='black',spacing=20)
        name=f'page-{number:04d}.jpg'; image.save(directory/'pages'/name,'JPEG',quality=92)
        page=PageView(page_number=number,image_url=f'/media/{document_id}/pages/{name}'); pages.append(page)
        segments.append(StudentSegment(student_key=sid,label=sid,start_page=number,end_page=number,pages=[page]))
    document=DocumentView(document_id=document_id,original_filename='Lote de imágenes ficticias',page_count=3,pages=pages,segments=segments)
    store.save_manifest(document)
    return document
