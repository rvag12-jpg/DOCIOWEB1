import json
from pathlib import Path
from uuid import uuid4
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from app.core.config import settings

router=APIRouter(prefix='/docio',tags=['docio'])
DB=settings.data_dir/'docio.json'

def load():
    if not DB.exists(): return {'groups':[],'students':[],'assessments':[],'corrections':[]}
    return json.loads(DB.read_text(encoding='utf-8'))
def save(db):
    DB.parent.mkdir(parents=True,exist_ok=True); DB.write_text(json.dumps(db,ensure_ascii=False,indent=2),encoding='utf-8')
def uid(prefix): return f'{prefix}-{uuid4().hex[:10]}'

class GroupIn(BaseModel): name:str; course:str=''; subject:str=''
class StudentIn(BaseModel): student_id:str; group_id:str
class Question(BaseModel): question_id:str; title:str; max_score:float=Field(gt=0); criteria:list[str]=[]
class AssessmentIn(BaseModel): title:str; group_id:str; evaluation:str=''; questions:list[Question]=[]
class Evidence(BaseModel): criterion_id:str; text:str; score:float|None=None
class CorrectionIn(BaseModel): assessment_id:str; student_id:str; scores:dict[str,float]={}; evidence:list[Evidence]=[]; validated:bool=False; comment:str=''

@router.get('/state')
def state(): return load()
@router.post('/groups')
def add_group(item:GroupIn):
    db=load(); row={'group_id':uid('GRP'),**item.model_dump()}; db['groups'].append(row); save(db); return row
@router.post('/students')
def add_student(item:StudentIn):
    db=load()
    if any(x['student_id']==item.student_id for x in db['students']): raise HTTPException(409,'student_id ya existe')
    if not any(x['group_id']==item.group_id for x in db['groups']): raise HTTPException(404,'Grupo no encontrado')
    row=item.model_dump(); db['students'].append(row); save(db); return row
@router.post('/assessments')
def add_assessment(item:AssessmentIn):
    db=load(); row={'assessment_id':uid('ASM'),**item.model_dump()}; db['assessments'].append(row); save(db); return row
@router.put('/corrections')
def upsert_correction(item:CorrectionIn):
    db=load(); data=item.model_dump(); idx=next((i for i,x in enumerate(db['corrections']) if x['assessment_id']==item.assessment_id and x['student_id']==item.student_id),None)
    if idx is None: db['corrections'].append(data)
    else: db['corrections'][idx]=data
    save(db); return data
@router.post('/import')
def import_correction(payload:dict):
    if payload.get('format') not in (None,'DOCIO_CORRECTION_V1'): raise HTTPException(422,'Formato no compatible')
    db=load(); rows=payload.get('corrections') or payload.get('students') or []
    if not isinstance(rows,list): raise HTTPException(422,'corrections/students debe ser una lista')
    assessment_id=payload.get('assessment_id'); imported=0
    for raw in rows:
        sid=raw.get('student_id')
        if not sid: raise HTTPException(422,'student_id obligatorio')
        aid=raw.get('assessment_id') or assessment_id
        if not aid: raise HTTPException(422,'assessment_id obligatorio')
        ev=raw.get('evidence') or raw.get('evidences') or []
        if isinstance(ev,dict): ev=[{'criterion_id':str(k),'text':str(v) if not isinstance(v,dict) else str(v.get('text','')),'score':v.get('score') if isinstance(v,dict) else None} for k,v in ev.items()]
        if not isinstance(ev,list): ev=[]
        row={'assessment_id':aid,'student_id':sid,'scores':raw.get('scores') or {},'evidence':ev,'validated':bool(raw.get('validated',False)),'comment':raw.get('comment','')}
        idx=next((i for i,x in enumerate(db['corrections']) if x['assessment_id']==aid and x['student_id']==sid),None)
        if idx is None: db['corrections'].append(row)
        else: db['corrections'][idx]=row
        imported+=1
    save(db); return {'format':'DOCIO_CORRECTION_V1','imported':imported}
@router.get('/export/{assessment_id}')
def export(assessment_id:str):
    db=load(); rows=[x for x in db['corrections'] if x['assessment_id']==assessment_id]
    return {'format':'DOCIO_CORRECTION_V1','assessment_id':assessment_id,'corrections':rows}
