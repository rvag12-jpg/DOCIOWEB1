from uuid import uuid4
from typing import Literal
from datetime import date
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from app import repository as repo
from app.services.evaluation import Evaluation, assessment_key, compute
router=APIRouter(prefix='/docio',tags=['docio'])
def load(): return repo.state()
def uid(p): return f'{p}-{uuid4().hex[:10]}'
class GroupIn(BaseModel): name:str; course:str=''; subject:str=''
class StudentIn(BaseModel): student_id:str; group_id:str
class KnowledgeIn(BaseModel): knowledge_id:str; code:str=''; title:str; course:str=''; subject:str=''
class CriterionIn(BaseModel): criterion_id:str; code:str=''; title:str; course:str=''; subject:str=''
class RelationIn(BaseModel): knowledge_id:str; criterion_id:str
class Question(BaseModel): question_id:str; title:str; max_score:float=Field(gt=0); knowledge_ids:list[str]=[]; criteria:list[str]=[]
class AssessmentMetadataIn(BaseModel):
 title:str=Field(min_length=1)
 evaluation:Evaluation
 assessment_date:date
class AssessmentIn(BaseModel): title:str; group_id:str; evaluation:Literal['Inicial','1ª','2ª','Ordinaria']='1ª'; assessment_date:date=Field(default_factory=date.today); assessment_type:Literal['exam','activity','project']='exam'; questions:list[Question]=[]
class Evidence(BaseModel): criterion_id:str; text:str; score:float|None=None
class CorrectionIn(BaseModel): assessment_id:str; student_id:str; scores:dict[str,float]={}; evidence:list[Evidence]=[]; validated:bool=False; comment:str=''; overwrite:bool=False
def assessment(db,aid): return next((x for x in db['assessments'] if x['assessment_id']==aid),None)
@router.get('/state')
def state(): return load()
@router.get('/storage')
def storage(): return {'backend':repo.backend(),'persistent':repo.backend()=='postgresql','record_counts':repo.counts()}
@router.get('/history')
def history(limit:int=100): return repo.history(max(1,min(limit,500)))
@router.post('/groups')
def add_group(item:GroupIn): return repo.put('groups',{'group_id':uid('GRP'),**item.model_dump()},'create')
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
def validate_question(db,q,max_criteria=2):
 if not q.knowledge_ids: raise HTTPException(422,f'{q.question_id}: debe indicar al menos un saber básico')
 if not q.criteria: raise HTTPException(422,f'{q.question_id}: debe seleccionar criterios desde la matriz')
 if len(q.criteria)>max_criteria: raise HTTPException(422,f'{q.question_id}: máximo {max_criteria} criterios')
 allowed={r['criterion_id'] for r in db['relations'] if r['knowledge_id'] in q.knowledge_ids}; invalid=set(q.criteria)-allowed
 if invalid: raise HTTPException(422,f'{q.question_id}: criterios sin relación saber→criterio: {sorted(invalid)}')
@router.post('/assessments')
def add_assessment(item:AssessmentIn):
 db=load()
 if not any(x['group_id']==item.group_id for x in db['groups']): raise HTTPException(404,'Grupo no encontrado')
 if not item.questions: raise HTTPException(422,'La prueba debe contener al menos una cuestión')
 for q in item.questions: validate_question(db,q,3 if item.assessment_type=='project' else 2)
 row={'assessment_id':uid('ASM'),**item.model_dump(mode='json')}; return repo.put('assessments',row,'create')
@router.patch('/assessments/{assessment_id}')
def update_assessment_metadata(assessment_id:str,item:AssessmentMetadataIn):
 a=assessment(load(),assessment_id)
 if not a: raise HTTPException(404,'Prueba no encontrada')
 if not item.title.strip(): raise HTTPException(422,'El título no puede estar vacío')
 return repo.put('assessments',{**a,**item.model_dump(mode='json'),'title':item.title.strip()},'metadata')
@router.put('/corrections')
def upsert_correction(item:CorrectionIn):
 db=load(); a=assessment(db,item.assessment_id)
 if not a: raise HTTPException(404,'Prueba no encontrada')
 if not any(x['student_id']==item.student_id for x in db['students']): raise HTTPException(404,'student_id no encontrado')
 existing=next((x for x in db['corrections'] if x['assessment_id']==item.assessment_id and x['student_id']==item.student_id),None)
 if existing and existing.get('validated') and not item.overwrite: raise HTTPException(409,'La corrección ya está validada. Confirme overwrite=true para sustituirla')
 invalid=set(item.scores)-{q['question_id'] for q in a.get('questions',[])}
 if invalid: raise HTTPException(422,f'Cuestiones no válidas: {sorted(invalid)}')
 data=item.model_dump(exclude={'overwrite'}); data.update(compute(a,data)); return repo.put('corrections',data,'correction')
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
def recovery(group_id:str,student_id:str,threshold:float=Query(5.0,ge=0,le=10)):
 db=load(); amap={a['assessment_id']:a for a in db['assessments'] if a['group_id']==group_id}; values={}
 rows=[c for c in db['corrections'] if c['student_id']==student_id and c['assessment_id'] in amap and c.get('validated',False)]; rows.sort(key=lambda c:assessment_key(amap[c['assessment_id']]))
 for c in rows:
  a=amap[c['assessment_id']]
  for cid,score in compute(a,c)['criterion_scores'].items(): values.setdefault(cid,[]).append({'assessment_id':c['assessment_id'],'title':a['title'],'date':a.get('assessment_date'),'evaluation':a.get('evaluation'),'score':score})
 result=[]
 for cid,items in values.items():
  latest=items[-1]['score']; best=max(x['score'] for x in items); previous_failed=any(x['score']<threshold for x in items[:-1]); recovered=previous_failed and latest>=threshold; status='pending' if latest<threshold else ('recovered' if recovered else 'achieved')
  result.append({'criterion_id':cid,'latest':latest,'best':best,'status':status,'recovered':recovered,'needs_recovery':latest<threshold,'evidence':items})
 return {'group_id':group_id,'student_id':student_id,'threshold':threshold,'criteria':result,'pending':[x['criterion_id'] for x in result if x['status']=='pending'],'recovered':[x['criterion_id'] for x in result if x['status']=='recovered'],'achieved':[x['criterion_id'] for x in result if x['status']=='achieved']}
@router.get('/student-profile/{student_id}')
def student_profile(student_id:str,evaluation:Evaluation|None=None):
 db=load(); student=next((x for x in db['students'] if x['student_id']==student_id),None)
 if not student: raise HTTPException(404,'student_id no encontrado')
 amap={a['assessment_id']:a for a in db['assessments'] if a['group_id']==student['group_id'] and (not evaluation or a.get('evaluation')==evaluation)}; attempts=[]; crit={}
 rows=[c for c in db['corrections'] if c['student_id']==student_id and c['assessment_id'] in amap and c.get('validated',False)]; rows.sort(key=lambda c:assessment_key(amap[c['assessment_id']]))
 for c in rows:
  a=amap[c['assessment_id']]; calc=compute(a,c); item={'assessment_id':a['assessment_id'],'title':a['title'],'evaluation':a.get('evaluation'),'date':a.get('assessment_date'),'final_score':calc['final_score'],'validated':c.get('validated',False),'criterion_scores':calc['criterion_scores']}; attempts.append(item)
  for cid,score in calc['criterion_scores'].items(): crit.setdefault(cid,[]).append({'date':a.get('assessment_date'),'evaluation':a.get('evaluation'),'assessment_id':a['assessment_id'],'score':score})
 return {'student':student,'evaluation':evaluation,'attempts':attempts,'criteria':crit,'mean':round(sum(x['final_score'] for x in attempts)/len(attempts),2) if attempts else None}
@router.post('/import')
def import_correction(payload:dict):
 if payload.get('format') not in (None,'DOCIO_CORRECTION_V1'): raise HTTPException(422,'Formato no compatible')
 db=load(); rows=payload.get('corrections') or payload.get('students') or []
 if not isinstance(rows,list): raise HTTPException(422,'corrections/students debe ser una lista')
 aid0=payload.get('assessment_id'); overwrite=bool(payload.get('overwrite',False)); imported=0; skipped=[]
 for raw in rows:
  sid=raw.get('student_id'); aid=raw.get('assessment_id') or aid0
  if not sid or not aid: raise HTTPException(422,'student_id y assessment_id obligatorios')
  a=assessment(db,aid)
  if not a: raise HTTPException(404,f'Prueba no encontrada: {aid}')
  if not any(x['student_id']==sid for x in db['students']): raise HTTPException(404,f'student_id no encontrado: {sid}')
  existing=next((x for x in db['corrections'] if x['assessment_id']==aid and x['student_id']==sid),None)
  if existing and existing.get('validated') and not overwrite: skipped.append({'assessment_id':aid,'student_id':sid,'reason':'validated'}); continue
  ev=raw.get('evidence') or raw.get('evidences') or []
  if isinstance(ev,dict): ev=[{'criterion_id':str(k),'text':str(v) if not isinstance(v,dict) else str(v.get('text','')),'score':v.get('score') if isinstance(v,dict) else None} for k,v in ev.items()]
  if not isinstance(ev,list): ev=[]
  scores=raw.get('scores') or {}; invalid=set(scores)-{q['question_id'] for q in a.get('questions',[])}
  if invalid: raise HTTPException(422,f'{sid}: cuestiones no válidas: {sorted(invalid)}')
  row={'assessment_id':aid,'student_id':sid,'scores':scores,'evidence':ev,'validated':bool(raw.get('validated',False)),'comment':raw.get('comment','')}; row.update(compute(a,row)); repo.put('corrections',row,'import'); imported+=1
 return {'format':'DOCIO_CORRECTION_V1','imported':imported,'skipped':skipped}
@router.get('/export/{assessment_id}')
def export(assessment_id:str):
 db=load(); a=assessment(db,assessment_id)
 if not a: raise HTTPException(404,'Prueba no encontrada')
 return {'format':'DOCIO_CORRECTION_V1','assessment_id':assessment_id,'assessment':a,'corrections':[{**x,**compute(a,x)} for x in db['corrections'] if x['assessment_id']==assessment_id]}

