"""Common scoring and chronology for correction, tracking and recovery."""
from math import isfinite
from typing import Literal

Evaluation = Literal['Inicial', '1ª', '2ª', 'Ordinaria']
EVAL_ORDER = {'Inicial': 0, '1ª': 1, '2ª': 2, 'Ordinaria': 3}


def assessment_key(assessment):
    return (assessment.get('assessment_date') or '',
            EVAL_ORDER.get(assessment.get('evaluation'), 99),
            assessment.get('assessment_id', ''))


def compute(assessment, correction):
    questions = assessment.get('questions', [])
    question_map = {q['question_id']: q for q in questions}
    total_max = sum(float(q['max_score']) for q in questions)
    total = 0.0
    criteria = {}
    scored = set()
    for question_id, raw in (correction.get('scores') or {}).items():
        question = question_map.get(question_id)
        if question is None or raw is None or raw == '':
            continue
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        maximum = float(question['max_score'])
        if not isfinite(value) or maximum <= 0:
            continue
        score = max(0.0, min(value, maximum))
        scored.add(question_id)
        total += score
        for criterion_id in question.get('criteria', []):
            criteria.setdefault(criterion_id, []).append(10 * score / maximum)
    return {
        'final_score': None if correction.get('ai_report') and len(scored)!=len(question_map) else (round(10 * total / total_max, 2) if total_max else 0.0),
        'criterion_scores': {cid: round(sum(values) / len(values), 2)
                             for cid, values in criteria.items()},
        'raw_score': round(total, 2),
        'raw_max': round(total_max, 2),
    }
