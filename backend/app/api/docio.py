from uuid import uuid4
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, model_validator
from app import repository as repo
router=APIRouter(prefix='/docio',tags=['docio'])
def load(): return repo.state()
def uid(p): return f'{p}-{uuid4().hex[:10]}'
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
def assessment(db,aid): return next((x for x in db['assessments'] if x['assessment_id']==aid),None)
def compute(a,c):
 qs=a.get('questions',[]); qmap={q['question_id']:q for q in qs}; total_max=sum(float(q['max_score']) for q in qs); total=0.; crit={}
 for qid,raw in (c.get('scores') or {}).items():
  q=qmap.get(qid)
  if not q: continue
  score=max(0.,min(float(raw),float(q['max_score']))); total+=score; ratio=10*score/float(q['max_score'])
  for cid in q.get('criteria',[]): crit.setdefault(cid,[]).append(ratio)
 return {'final_score':round(10*total/total_max,2) if total_max else 0.,'criterion_scores':{k:round(sum(v)/len(v),2) for k,v in crit.items()},'raw_score':round(total,2),'raw_max':round(total_max,2)}
@router.get('/state')
def state(): return load()
@router.get('/storage')
def storage(): return {'backend':repo.backend(),'persistent':repo.backend()=='postgresql'}
@router.get('/history')
def history(limit:int=100): return repo.history(max(1,min(limit,500)))
@router.post('/groups')
def add_group(item:GroupIn):
 row={'group_id':uid('GRP'),**item.model_dump()}; return repo.put('groups',row,'create')
@router.post('/students')
def add_student(item:StudentIn):
 db=load()
 if any(x['student_id']==item.student_id for x in db['students']): raise HTTPException(409,'student_id ya existe')
 if not any(x['group_id']==item.group_id for x in db['groups']): raise HTTPException(404,'Grupo no encontrado')
 return repo.put('students',item.model_dump(),'create')
@router.post('/knowledge')
def add_knowledge(item:KnowledgeIn):
 if any(x['knowledge_id']==item.knowledge_id for x in load()['knowledge']): raise HTTPException(409,'Saber ya existe')
 return repo.put('knowledge',item.model_dump(),'create')
@router.post('/criteria')
def add_criterion(item:CriterionIn):
 if any(x['criterion_id']==item.criterion_id for x in load()['criteria']): raise HTTPException(409,'Criterio ya existe')
 return repo.put('criteria',item.model_dump(),'create')
@router.post('/relations')
def add_relation(item:RelationIn):
 db=load()
 if not any(x['knowledge_id']==item.knowledge_id for x in db['knowledge']): raise HTTPException(404,'Saber no encontrado')
 if not any(x['criterion_id']==item.criterion_id for x in db['criteria']): raise HTTPException(404,'Criterio no encontrado')
 return repo.put('relations',item.model_dump(),'create')
def validate_question(db,q):
 if not q.knowledge_ids: raise HTTPException(422,f'{q.question_id}: debe indicar al menos un saber básico')
 allowed={r['criterion_id'] for r in db['relations'] if r['knowledge_id'] in q.knowledge_ids}; invalid=set(q.criteria)-allowed
 if invalid: raise HTTPException(422,f'{q.question_id}: criterios sin relación saber→criterio: {sorted(invalid)}')
 if not q.criteria: raise HTTPException(422,f'{q.question_id}: debe seleccionar 1 o 2 criterios desde la matriz')
@router.post('/assessments')
def add_assessment(item:AssessmentIn):
 db=load()
 if not any(x['group_id']==item.group_id for x in db['groups']): raise HTTPException(404,'Grupo no encontrado')
 for q in item.questions: validate_question(db,q)
 row={'assessment_id':uid('ASM'),**item.model_dump()}; return repo.put('assessments',row,'create')
@router.put('/corrections')
def upsert_correction(item:CorrectionIn):
 db=load(); a=assessment(db,item.assessment_id)
 if not a: raise HTTPException(404,'Prueba no encontrada')
 if not any(x['student_id']==item.student_id for x in db['students']): raise HTTPException(404,'student_id no encontrado')
 invalid=set(item.scores)-{q['question_id'] for q in a.get('questions',[])}
 if invalid: raise HTTPException(422,f'Cuestiones no válidas: {sorted(invalid)}')
 data=item.model_dump(); data.update(compute(a,data)); return repo.put('corrections',data,'correction')
@router.delete('/corrections/{assessment_id}/{student_id}')
def delete_correction(assessment_id:str,student_id:str):
 if not repo.remove('corrections',f'{assessment_id}::{student_id}'): raise HTTPException(404,'Corrección no encontrada')
 return {'deleted':True}
@router.get('/analytics/{assessment_id}')
def analytics(assessment_id:str):
 db=load(); a=assessment(db,assessment_id)
 if not a: raise HTTPException(404,'Prueba no encontrada')
 rows=[{**c,**compute(a,c)} for c in db['corrections'] if c['assessment_id']==assessment_id]; criteria=sorted({cid for q in a.get('questions',[]) for cid in q.get('criteria',[])})
 means={cid:(round(sum(vals)/len(vals),2) if (vals:=[r['criterion_scores'][cid] for r in rows if cid in r['criterion_scores']]) else None) for cid in criteria}
 return {'assessment':a,'students':rows,'criterion_means':means,'group_mean':round(sum(r['final_score'] for r in rows)/len(rows),2) if rows else None}
@router.get('/recovery/{group_id}/{student_id}')
def recovery(group_id:str,student_id:str,threshold:float=5.0):
 db=load(); aids={a['assessment_id']:a for a in db['assessments'] if a['group_id']==group_id}; values={}
 for c in db['corrections']:
  if c['student_id']!=student_id or c['assessment_id'] not in aids: continue
  for cid,score in compute(aids[c['assessment_id']],c)['criterion_scores'].items(): values.setdefault(cid,[]).append({'assessment_id':c['assessment_id'],'score':score})
 result=[]
 for cid,items in values.items():
  latest=items[-1]['score']; best=max(x['score'] for x in items); result.append({'criterion_id':cid,'latest':latest,'best':best,'recovered':latest>=threshold,'needs_recovery':latest<threshold,'evidence':items})
 return {'group_id':group_id,'student_id':student_id,'threshold':threshold,'criteria':result}
@router.post('/import')
def import_correction(payload:dict):
 if payload.get('format') not in (None,'DOCIO_CORRECTION_V1'): raise HTTPException(422,'Formato no compatible')
 db=load(); rows=payload.get('corrections') or payload.get('students') or []
 if not isinstance(rows,list): raise HTTPException(422,'corrections/students debe ser una lista')
 aid0=payload.get('assessment_id'); imported=0
 for raw in rows:
  sid=raw.get('student_id'); aid=raw.get('assessment_id') or aid0
  if not sid or not aid: raise HTTPException(422,'student_id y assessment_id obligatorios')
  ev=raw.get('evidence') or raw.get('evidences') or []
  if isinstance(ev,dict): ev=[{'criterion_id':str(k),'text':str(v) if not isinstance(v,dict) else str(v.get('text','')),'score':v.get('score') if isinstance(v,dict) else None} for k,v in ev.items()]
  if not isinstance(ev,list): ev=[]
  row={'assessment_id':aid,'student_id':sid,'scores':raw.get('scores') or {},'evidence':ev,'validated':bool(raw.get('validated',False)),'comment':raw.get('comment','')}; a=assessment(db,aid)
  if a: row.update(compute(a,row))
  repo.put('corrections',row,'import'); imported+=1
 return {'format':'DOCIO_CORRECTION_V1','imported':imported}
@router.get('/export/{assessment_id}')
def export(assessment_id:str):
 db=load(); a=assessment(db,assessment_id)
 if not a: raise HTTPException(404,'Prueba no encontrada')
 return {'format':'DOCIO_CORRECTION_V1','assessment_id':assessment_id,'assessment':a,'corrections':[{**x,**compute(a,x)} for x in db['corrections'] if x['assessment_id']==assessment_id]}
