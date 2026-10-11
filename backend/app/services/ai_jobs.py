"""One student per API request, with durable per-student checkpoints."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from threading import Lock
from time import time
from uuid import uuid4
import copy
import hashlib
import os
from fastapi import HTTPException
from pydantic import BaseModel, Field, StrictBool
from app import repository as repo
from app.storage import store
from app.services import ai_provider
from app.services.corrector import Framework, VERSION, correction_from_result, digest, validate_framework
from app.services.evaluation import Evaluation

pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='docio-corrector')
submitted={}
submit_lock=Lock()


class Assignment(BaseModel):
    student_id:str
    document_id:str


class JobIn(BaseModel):
    request_id:str=Field(pattern=r'^[a-zA-Z0-9-]{8,64}$')
    source_assessment_id:str
    title:str=Field(min_length=1,max_length=200)
    evaluation:Evaluation
    assessment_date:date
    framework:Framework
    framework_confirmed:StrictBool
    assignments:list[Assignment]=Field(min_length=1,max_length=40)


def selected_images(assignment):
    try:
        document=store.load_manifest(assignment.document_id)
        pages={p.page_number:p for segment in document.segments if segment.student_key==assignment.student_id for p in segment.pages}
        if not pages or len(pages)>12:
            raise HTTPException(422,f'{assignment.student_id}: asigne entre 1 y 12 páginas al alumno')
        result=[]
        directory=store.document_dir(assignment.document_id)
        for number,page in sorted(pages.items()):
            path=directory/'pages'/Path(page.image_url).name
            if not path.is_file() or not path.resolve().is_relative_to(directory.resolve()):
                raise HTTPException(422,f'{assignment.student_id}: falta una imagen del documento')
            result.append({'page_number':number,'path':str(path.relative_to(store.root)),
                           'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
        return result
    except (FileNotFoundError,ValueError) as error:
        raise HTTPException(404,'Documento o imágenes no encontrados') from error


def create_job(item):
    if not item.framework_confirmed or not item.title.strip():
        raise HTTPException(422,'Confirme la ficha maestra y el título antes de corregir')
    if len({a.student_id for a in item.assignments})!=len(item.assignments):
        raise HTTPException(422,'Seleccione un único documento por alumno; cada documento puede contener varias páginas')
    config=ai_provider.configuration()
    if not config['ready']:
        raise HTTPException(503,'El servicio IA no está configurado; active la simulación o configure OpenAI en el servidor')
    if len(item.assignments)>int(os.getenv('DOCIO_AI_MAX_STUDENTS','40')):
        raise HTTPException(422,'El lote supera el máximo de alumnos configurado')
    job_id='AI-'+item.request_id
    signature=digest({'request':item.model_dump(mode='json'),'provider':config['provider']})
    with repo.atomic() as connection:
        existing=repo._get(connection,'ai_jobs',job_id)
        if existing:
            if existing['request_signature']!=signature:
                raise HTTPException(409,'El identificador de solicitud ya corresponde a otro lote')
            return existing
        db=repo._state(connection)
        source=next((a for a in db['assessments'] if a['assessment_id']==item.source_assessment_id),None)
        if not source: raise HTTPException(404,'Plantilla de prueba no encontrada')
        validate_framework(item.framework,source,db)
        students={s['student_id']:s for s in db['students']}
        entries=[]
        for assignment in item.assignments:
            student=students.get(assignment.student_id)
            if not student or student['group_id']!=source['group_id']:
                raise HTTPException(422,f'{assignment.student_id}: alumno ajeno al grupo de la plantilla')
            entries.append({'student_id':assignment.student_id,'document_id':assignment.document_id,
                            'images':selected_images(assignment),'status':'pending','attempts':0,'error':None,
                            'final_score':None,'review_reasons':[]})
        # Keep API work out of this transaction. Only the new assessment and queue entry are committed here.
        assessment={**copy.deepcopy(source),'assessment_id':'ASM-'+uuid4().hex[:12],
                    'source_assessment_id':source['assessment_id'],'title':item.title.strip(),
                    'evaluation':item.evaluation,'assessment_date':item.assessment_date.isoformat(),
                    'corrector_framework':{'version':VERSION,'locked':True,'confirmed_at':repo.now(),
                                          'hash':digest(item.framework.model_dump()),'rubric':item.framework.model_dump()},
                    'ai_job_id':job_id}
        job={'job_id':job_id,'assessment_id':assessment['assessment_id'],'request_signature':signature,
             'created_at':repo.now(),'updated_at':repo.now(),'status':'queued','provider':config['provider'],
             'simulated':config['simulated'],'model':config['model'],'source_assessment_id':source['assessment_id'],
             'assessment_snapshot':assessment,'framework':item.framework.model_dump(),'students':entries,
             'lease_until':0,'run_id':None,'error':None}
        repo._put(connection,'assessments',assessment['assessment_id'],assessment,'ai-create')
        repo._put(connection,'ai_jobs',job_id,job,'ai-queue')
    return job


def summary(job):
    return {k:v for k,v in job.items() if k not in ('request_signature','framework','assessment_snapshot','run_id')} | {
        'students':[{k:v for k,v in s.items() if k!='images'} for s in job['students']],
        'completed':sum(s['status'] in ('completed','review_required') for s in job['students']),
        'total':len(job['students']), 'retry_available':job['status'] in ('partial','failed','interrupted') or
                     (job['status']=='running' and job.get('lease_until',0)<time())}


def enqueue(job_id):
    with submit_lock:
        for key,future in list(submitted.items()):
            if future.done(): submitted.pop(key,None)
        current=submitted.get(job_id)
        if current is not None and not current.done(): return
        submitted[job_id]=pool.submit(run_job,job_id)


def retry_job(job_id):
    with repo.atomic() as connection:
        job=repo._get(connection,'ai_jobs',job_id)
        if not job: raise HTTPException(404,'Lote no encontrado')
        expired=job['status']=='running' and job.get('lease_until',0)<time()
        if job['status'] not in ('partial','failed','interrupted') and not expired:
            raise HTTPException(409,'El lote no tiene alumnos pendientes de reintento o sigue en ejecución')
        for student in job['students']:
            if student['status'] in ('failed','running','pending'):
                student.update(status='pending',error=None)
        job.update(status='queued',lease_until=0,run_id=None,error=None,updated_at=repo.now())
        repo._put(connection,'ai_jobs',job_id,job,'ai-retry')
    return job


def verified_images(student):
    images=[]
    for reference in student['images']:
        path=(store.root/reference['path']).resolve()
        if not path.is_relative_to(store.root.resolve()) or not path.is_file():
            raise ValueError('Las imágenes ya no están disponibles; vuelva a cargarlas antes de crear otro lote')
        if hashlib.sha256(path.read_bytes()).hexdigest()!=reference['sha256']:
            raise ValueError('Una imagen ha cambiado desde la confirmación del lote')
        images.append((reference['page_number'],path))
    return images


def mark_student(job_id,run_id,sid,change,correction=None):
    with repo.atomic() as connection:
        job=repo._get(connection,'ai_jobs',job_id)
        if job['run_id']!=run_id or job['status']!='running':
            return False
        student=next(s for s in job['students'] if s['student_id']==sid)
        if correction:
            key=repo.key_for('corrections',correction)
            if repo._get(connection,'corrections',key):
                raise ValueError('Ya existe una corrección en la prueba nueva; se ha conservado sin sustituirla')
            repo._put(connection,'corrections',key,correction,'ai-result')
        student.update(change)
        job.update(updated_at=repo.now(),lease_until=time()+600)
        repo._put(connection,'ai_jobs',job_id,job,'ai-checkpoint')
    return True


def check_consistency(connection,job):
    """Exact equivalent transcripts/evidence with unequal credit require review."""
    signatures={}
    rows=[repo._get(connection,'corrections',job['assessment_id']+'::'+s['student_id']) for s in job['students']]
    for row in rows:
        if not row or row.get('validated'): continue
        for item in row['ai_report']['result']['items']:
            if not item['transcription'].strip(): continue
            evidence=' '.join(text for c in item['components'] for text in c['observed_evidence'])
            signature=(item['question_id'],' '.join(item['transcription'].casefold().split()),' '.join(evidence.casefold().split()))
            signatures.setdefault(signature,[]).append((row,tuple((c['component_id'],c['awarded']) for c in sorted(item['components'],key=lambda c:c['component_id']))))
    affected=set()
    for matches in signatures.values():
        if len({score for _,score in matches})>1:
            affected.update(row['student_id'] for row,_ in matches)
    for row in rows:
        if row and row['student_id'] in affected:
            reason='Consistencia: evidencia y transcripción equivalentes con créditos distintos; revisar sin promediar las notas'
            report=row['ai_report']; report['status']='REVIEW_REQUIRED'
            report['review_reasons']=list(dict.fromkeys(report['review_reasons']+[reason]))
            repo._put(connection,'corrections',repo.key_for('corrections',row),row,'ai-consistency')
            entry=next(s for s in job['students'] if s['student_id']==row['student_id'])
            entry.update(status='review_required',review_reasons=report['review_reasons'])


def run_job(job_id):
    run_id=uuid4().hex
    try:
        with repo.atomic() as connection:
            job=repo._get(connection,'ai_jobs',job_id)
            if not job or job['status']!='queued': return
            job.update(status='running',run_id=run_id,lease_until=time()+600,updated_at=repo.now())
            repo._put(connection,'ai_jobs',job_id,job,'ai-start')
        framework=Framework.model_validate(job['framework'])
        assessment=job['assessment_snapshot']
        for student in job['students']:
            if student['status']!='pending': continue
            sid=student['student_id']
            if not mark_student(job_id,run_id,sid,{'status':'running','attempts':student['attempts']+1,'error':None}): return
            try:
                images=verified_images(student)
                result,metadata=ai_provider.correct(sid,assessment,framework,images,job['provider'])
                row=correction_from_result(result,sid,assessment,framework,[p for p,_ in images],repo.state(),
                                           {**metadata,'job_id':job_id,'processed_at':repo.now(),'document_id':student['document_id']})
                status='review_required' if row['ai_report']['review_reasons'] else 'completed'
                mark_student(job_id,run_id,sid,{'status':status,'final_score':row['final_score'],
                                               'review_reasons':row['ai_report']['review_reasons'],'error':None},row)
            except (ai_provider.ProviderError,ValueError,HTTPException) as error:
                message=str(error.detail) if isinstance(error,HTTPException) else str(error)
                mark_student(job_id,run_id,sid,{'status':'failed','error':message})
        with repo.atomic() as connection:
            current=repo._get(connection,'ai_jobs',job_id)
            if current['run_id']!=run_id: return
            check_consistency(connection,current)
            failures=sum(s['status']=='failed' for s in current['students'])
            completed=sum(s['status'] in ('completed','review_required') for s in current['students'])
            current.update(status=('partial' if completed else 'failed') if failures else 'completed',
                           updated_at=repo.now(),lease_until=0)
            repo._put(connection,'ai_jobs',job_id,current,'ai-finish')
    except Exception:
        # Do not log credentials, images, provider payloads or student answers.
        with repo.atomic() as connection:
            job=repo._get(connection,'ai_jobs',job_id)
            if job and job.get('run_id')==run_id:
                for student in job['students']:
                    if student['status']=='running': student.update(status='failed',error='Fallo interno; el resultado no se ha cargado')
                job.update(status='interrupted',error='El lote se ha interrumpido. Las correcciones terminadas se conservan.',lease_until=0)
                repo._put(connection,'ai_jobs',job_id,job,'ai-interrupted')
