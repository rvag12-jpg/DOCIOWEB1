"""Invented demonstration records; no source files or real records are read."""
from app.services.evaluation import compute


def dataset():
    group_id = 'DEMO-GROUP'
    questions = [
        {'question_id': 'Q1', 'title': 'Cuestión simulada 1', 'max_score': 2,
         'knowledge_ids': ['DEMO-K1'], 'criteria': ['DEMO-C1']},
        {'question_id': 'Q2', 'title': 'Cuestión simulada 2', 'max_score': 2,
         'knowledge_ids': ['DEMO-K2'], 'criteria': ['DEMO-C2']},
    ]
    assessments = [
        {'assessment_id': 'DEMO-INITIAL', 'title': 'Prueba inicial ficticia',
         'group_id': group_id, 'evaluation': 'Inicial', 'assessment_date': '2026-09-15',
         'assessment_type': 'exam', 'questions': questions},
        {'assessment_id': 'DEMO-FOLLOWUP', 'title': 'Prueba de seguimiento ficticia',
         'group_id': group_id, 'evaluation': '1ª', 'assessment_date': '2026-10-05',
         'assessment_type': 'exam', 'questions': questions},
    ]
    corrections = []
    for aid, sid, scores, validated in (
        ('DEMO-INITIAL', 'DEMO-001', {'Q1': .4, 'Q2': .8}, True),
        ('DEMO-FOLLOWUP', 'DEMO-001', {'Q1': 1.6, 'Q2': 1.4}, True),
        ('DEMO-FOLLOWUP', 'DEMO-002', {'Q1': .6, 'Q2': 1.2}, True),
        ('DEMO-FOLLOWUP', 'DEMO-003', {'Q1': 1.8, 'Q2': 1.8}, False),
    ):
        row = {'assessment_id': aid, 'student_id': sid, 'scores': scores,
               'validated': validated, 'comment': 'Registro completamente ficticio.',
               'evidence': [{'criterion_id': 'DEMO-C1', 'text': 'Evidencia simulada para comprobar la interfaz.', 'score': None}]}
        assessment = next(a for a in assessments if a['assessment_id'] == aid)
        corrections.append({**row, **compute(assessment, row)})
    return {
        'groups': [{'group_id': group_id, 'name': 'Grupo DEMO · datos ficticios',
                    'course': '3.º ESO · demostración', 'subject': 'Física y Química · demostración'}],
        'students': [{'student_id': f'DEMO-{i:03d}', 'group_id': group_id} for i in range(1, 4)],
        'knowledge': [{'knowledge_id': f'DEMO-K{i}', 'code': f'DEMO-K{i}',
                       'title': f'Saber sintético {i} para comprobar relaciones',
                       'course': 'Demostración', 'subject': 'Demostración'} for i in (1, 2)],
        'criteria': [{'criterion_id': f'DEMO-C{i}', 'code': f'DEMO-C{i}',
                      'title': f'Criterio sintético {i}; no es un criterio curricular oficial',
                      'course': 'Demostración', 'subject': 'Demostración'} for i in (1, 2)],
        'relations': [{'knowledge_id': f'DEMO-K{i}', 'criterion_id': f'DEMO-C{i}'} for i in (1, 2)],
        'assessments': assessments, 'corrections': corrections,
    }
