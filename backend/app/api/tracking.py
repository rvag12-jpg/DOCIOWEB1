from fastapi import APIRouter, HTTPException
from app import repository as repo

router=APIRouter(prefix='/docio',tags=['docio-tracking'])
EVAL_ORDER={'Inicial':0,'1ª':1,'2ª':2,'Ordinaria':3}

def compute(a,c):
    qs=a.get('questions',[]); qmap={q['question_id']:q for q in qs}; total_max=sum(float(q['max_score']) for q in qs); total=0.; crit={}
    for qid,raw in (c.get('scores') or {}).items():
        q=qmap.get(qid)
        if not q: continue
        score=max(0.,min(float(raw),float(q['max_score']))); total+=score; ratio=10*score/float(q['max_score'])
        for cid in q.get('criteria',[]): crit.setdefault(cid,[]).append(ratio)
    return {'final_score':round(10*total/total_max,2) if total_max else 0.,'criterion_scores':{k:round(sum(v)/len(v),2) for k,v in crit.items()}}

def akey(a): return (str(a.get('assessment_date','0000-00-00')),EVAL_ORDER.get(a.get('evaluation',''),99),a.get('assessment_id',''))

@router.get('/tracking')
def tracking(group_id:str|None=None,evaluation:str|None=None):
    db=repo.state(); assessments=db['assessments']
    if group_id: assessments=[a for a in assessments if a.get('group_id')==group_id]
    if evaluation: assessments=[a for a in assessments if a.get('evaluation')==evaluation]
    amap={a['assessment_id']:a for a in assessments}; rows=[]
    for c in db['corrections']:
        a=amap.get(c.get('assessment_id'))
        if not a: continue
        calc=compute(a,c); rows.append({'student_id':c['student_id'],'assessment_id':a['assessment_id'],'title':a['title'],'group_id':a['group_id'],'evaluation':a.get('evaluation'),'date':a.get('assessment_date'),'validated':c.get('validated',False),'final_score':calc['final_score'],'criterion_scores':calc['criterion_scores']})
    rows.sort(key=lambda x:(x['student_id'],x.get('date') or '',EVAL_ORDER.get(x.get('evaluation',''),99)))
    return {'group_id':group_id,'evaluation':evaluation,'rows':rows,'count':len(rows)}

@router.get('/group-overview/{group_id}')
def group_overview(group_id:str,evaluation:str|None=None,threshold:float=5.0):
    db=repo.state()
    if not any(g['group_id']==group_id for g in db['groups']): raise HTTPException(404,'Grupo no encontrado')
    assessments=[a for a in db['assessments'] if a.get('group_id')==group_id and (not evaluation or a.get('evaluation')==evaluation)]; assessments.sort(key=akey); amap={a['assessment_id']:a for a in assessments}; students=[s for s in db['students'] if s.get('group_id')==group_id]; result=[]
    for s in students:
        corrections=[c for c in db['corrections'] if c.get('student_id')==s['student_id'] and c.get('assessment_id') in amap]; corrections.sort(key=lambda c:akey(amap[c['assessment_id']]))
        criterion_values={}; finals=[]
        for c in corrections:
            calc=compute(amap[c['assessment_id']],c); finals.append(calc['final_score'])
            for cid,score in calc['criterion_scores'].items(): criterion_values.setdefault(cid,[]).append(score)
        latest={cid:vals[-1] for cid,vals in criterion_values.items()}; pending=[cid for cid,v in latest.items() if v<threshold]
        result.append({'student_id':s['student_id'],'mean':round(sum(finals)/len(finals),2) if finals else None,'assessments':len(corrections),'latest_criteria':latest,'pending_criteria':pending})
    return {'group_id':group_id,'evaluation':evaluation,'threshold':threshold,'students':result,'assessments':[{'assessment_id':a['assessment_id'],'title':a['title'],'evaluation':a.get('evaluation'),'date':a.get('assessment_date')} for a in assessments]}
