from fastapi import APIRouter, HTTPException, Query
from app import repository as repo
from app.services.evaluation import Evaluation, assessment_key, compute

router = APIRouter(prefix='/docio', tags=['docio-tracking'])


@router.get('/tracking')
def tracking(group_id: str | None = None, evaluation: Evaluation | None = None):
    db = repo.state()
    assessments = [a for a in db['assessments']
                   if (not group_id or a.get('group_id') == group_id)
                   and (not evaluation or a.get('evaluation') == evaluation)]
    assessments.sort(key=assessment_key)
    order = {a['assessment_id']: i for i, a in enumerate(assessments)}
    amap = {a['assessment_id']: a for a in assessments}
    rows = []
    for correction in db['corrections']:
        assessment = amap.get(correction.get('assessment_id'))
        if assessment is None:
            continue
        calc = compute(assessment, correction)
        rows.append({
            'student_id': correction['student_id'],
            'assessment_id': assessment['assessment_id'],
            'title': assessment['title'], 'group_id': assessment['group_id'],
            'evaluation': assessment.get('evaluation'),
            'date': assessment.get('assessment_date'),
            'validated': correction.get('validated', False),
            'final_score': calc['final_score'],
            'criterion_scores': calc['criterion_scores'],
        })
    rows.sort(key=lambda row: (row['student_id'], order[row['assessment_id']]))
    return {'group_id': group_id, 'evaluation': evaluation, 'rows': rows, 'count': len(rows)}


@router.get('/group-overview/{group_id}')
def group_overview(group_id: str, evaluation: Evaluation | None = None,
                   threshold: float = Query(5.0, ge=0, le=10)):
    db = repo.state()
    if not any(g['group_id'] == group_id for g in db['groups']):
        raise HTTPException(404, 'Grupo no encontrado')
    assessments = [a for a in db['assessments'] if a.get('group_id') == group_id
                   and (not evaluation or a.get('evaluation') == evaluation)]
    assessments.sort(key=assessment_key)
    amap = {a['assessment_id']: a for a in assessments}
    expected = sorted({cid for a in assessments for q in a.get('questions', [])
                       for cid in q.get('criteria', [])})
    result = []
    for student in (s for s in db['students'] if s.get('group_id') == group_id):
        corrections = [c for c in db['corrections']
                       if c.get('student_id') == student['student_id']
                       and c.get('assessment_id') in amap]
        drafts = sum(not c.get('validated', False) for c in corrections)
        corrections = [c for c in corrections if c.get('validated', False)]
        corrections.sort(key=lambda c: assessment_key(amap[c['assessment_id']]))
        latest, finals = {}, []
        for correction in corrections:
            calc = compute(amap[correction['assessment_id']], correction)
            finals.append(calc['final_score'])
            latest.update(calc['criterion_scores'])
        pending = sorted(cid for cid, value in latest.items() if value < threshold)
        missing = sorted(set(expected) - latest.keys())
        status = ('no_evidence' if not latest else 'pending' if pending
                  else 'partial' if missing else 'achieved')
        result.append({
            'student_id': student['student_id'],
            'mean': round(sum(finals) / len(finals), 2) if finals else None,
            'assessments': len(corrections), 'drafts': drafts,
            'latest_criteria': latest, 'pending_criteria': pending,
            'missing_criteria': missing, 'status': status,
        })
    means = {}
    for cid in expected:
        values = [s['latest_criteria'][cid] for s in result if cid in s['latest_criteria']]
        means[cid] = round(sum(values) / len(values), 2) if values else None
    return {
        'group_id': group_id, 'evaluation': evaluation, 'threshold': threshold,
        'students': result, 'expected_criteria': expected, 'criterion_means': means,
        'assessments': [{'assessment_id': a['assessment_id'], 'title': a['title'],
                         'evaluation': a.get('evaluation'), 'date': a.get('assessment_date')}
                        for a in assessments],
    }
