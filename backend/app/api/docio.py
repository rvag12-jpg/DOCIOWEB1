import json
from uuid import uuid4
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, model_validator
from app.core.config import settings

router=APIRouter(prefix='/docio',tags=['docio'])
DB=settings.data_dir/'docio.json'
EMPTY={'groups':[],'students':[],'assessments':[],'corrections':[],'knowledge':[],'criteria':[],'relations':[]}
def load():
    db=json.loads(DB.read_text(encoding='utf-8')) if DB.exists() else {}
    for k,v in EMPTY.items(): db.setdefault(k,list(v))
    return db
def save(db): DB.parent.mkdir(parents=True,exist_ok=True); DB.write_text(json.dumps(db,ensure_ascii=False,indent=2),encoding='utf-8')
def uid(prefix): return f'{prefix}-{uuid4().hex[:10]}'
class GroupIn(BaseModel): name:str; course:str=''; subject:str=''
class StudentIn(BaseModel): student_id:str; group_id:str
class KnowledgeIn(BaseModel): knowledge_id:str; code:str=''; title:str; course:str=''; subject:str=''
class CriterionIn(BaseModel): criterion_id:str; code:str=''; title:str; course:str=''; subject:str=''
class RelationIn(BaseModel): knowledge_id:str; criterion_id:str
class Question(BaseModel):
    question_id:str; title:str; max_score:float=Field(gt=0); knowledge_ids:list[str]=[]; criteria:list[str]=[]
    @model_validator(mode='after')
    def limits(self):
        if len(self.criteria)>2: raise ValueError('Máximo 2 criterios por cuestión')
        return self
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
@router.post('/knowledge')
def add_knowledge(item:KnowledgeIn):
    db=load()
    if any(x['knowledge_id']==item.knowledge_id for x in db['knowledge']): raise HTTPException(409,'Saber ya existe')
    row=item.model_dump(); db['knowledge'].append(row); save(db); return row
@router.post('/criteria')
def add_criterion(item:CriterionIn):
    db=load()
    if any(x['criterion_id']==item.criterion_id for x in db['criteria']): raise HTTPException(409,'Criterio ya existe')
    row=item.model_dump(); db['criteria'].append(row); save(db); return row
@router.post('/relations')
def add_relation(item:RelationIn):
    db=load()
    if not any(x['knowledge_id']==item.knowledge_id for x in db['knowledge']): raise HTTPException(404,'Saber no encontrado')
    if not any(x['criterion_id']==item.criterion_id for x in db['criteria']): raise HTTPException(404,'Criterio no encontrado')
    row=item.model_dump()
    if row not in db['relations']: db['relations'].append(row); save(db)
    return row
def validate_question(db,q):
    if not q.knowledge_ids: raise HTTPException(422,f'{q.question_id}: debe indicar al menos un saber básico')
    allowed={r['criterion_id'] for r in db['relations'] if r['knowledge_id'] in q.knowledge_ids}
    invalid=set(q.criteria)-allowed
    if invalid: raise HTTPException(422,f'{q.question_id}: criterios sin relación saber→criterio: {sorted(invalid)}')
    if not q.criteria: raise HTTPException(422,f'{q.question_id}: debe seleccionar 1 o 2 criterios desde la matriz')
@router.post('/assessments')
def add_assessment(item:AssessmentIn):
    db=load()
    if not any(x['group_id']==item.group_id for x in db['groups']): raise HTTPException(404,'Grupo no encontrado')
    for q in item.questions: validate_question(db,q)
    row={'assessment_id':uid('ASM'),**item.model_dump()}; db['assessments'].append(row); save(db); return row
@router.put('/corrections')
def upsert_correction(item:CorrectionIn):
    db=load()
    if not any(x['assessment_id']==item.assessment_id for x in db['assessments']): raise HTTPException(404,'Prueba no encontrada')
    if not any(x['student_id']==item.student_id for x in db['students']): raise HTTPException(404,'student_id no encontrado')
    data=item.model_dump(); idx=next((i for i,x in enumerate(db['corrections']) if x['assessment_id']==item.assessment_id and x['student_id']==item.student_id),None)
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
        sid=raw.get('student_id'); aid=raw.get('assessment_id') or assessment_id
        if not sid: raise HTTPException(422,'student_id obligatorio')
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
    db=load(); assessment=next((x for x in db['assessments'] if x['assessment_id']==assessment_id),None)
    if not assessment: raise HTTPException(404,'Prueba no encontrada')
    rows=[x for x in db['corrections'] if x['assessment_id']==assessment_id]
    return {'format':'DOCIO_CORRECTION_V1','assessment_id':assessment_id,'assessment':assessment,'corrections':rows}
