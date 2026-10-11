"""Validate correction exchange before any record is written."""
import hashlib
import json
from typing import Annotated

from fastapi import HTTPException
from pydantic import BaseModel, Field, StrictBool, StrictStr, ValidationError
from app.services.evaluation import compute

Score = Annotated[float, Field(strict=True, ge=0, allow_inf_nan=False)]
CriterionScore = Annotated[float, Field(strict=True, ge=0, le=10, allow_inf_nan=False)]


class Evidence(BaseModel):
    criterion_id: StrictStr
    text: StrictStr
    score: CriterionScore | None = None


class CorrectionIn(BaseModel):
    assessment_id: StrictStr = Field(min_length=1)
    student_id: StrictStr = Field(min_length=1)
    scores: dict[str, Score] = Field(default_factory=dict)
    evidence: list[Evidence] = Field(default_factory=list)
    validated: StrictBool = False
    comment: StrictStr = ''
    overwrite: StrictBool = False
    teacher_review_confirmed: StrictBool = False


def validate_correction(item, db):
    assessment = next((a for a in db['assessments'] if a['assessment_id'] == item.assessment_id), None)
    if not assessment:
        raise HTTPException(404, f'Prueba no encontrada: {item.assessment_id}')
    student = next((s for s in db['students'] if s['student_id'] == item.student_id), None)
    if not student:
        raise HTTPException(404, f'student_id no encontrado: {item.student_id}')
    if student['group_id'] != assessment['group_id']:
        raise HTTPException(422, f'{item.student_id}: el alumno no pertenece al grupo de la prueba')
    questions = {q['question_id']: q for q in assessment.get('questions', [])}
    invalid = set(item.scores) - questions.keys()
    if invalid:
        raise HTTPException(422, f'{item.student_id}: cuestiones no válidas: {sorted(invalid)}')
    for qid, score in item.scores.items():
        if score > float(questions[qid]['max_score']):
            raise HTTPException(422, f'{item.student_id}: {qid} supera la puntuación máxima')
    if item.validated and set(item.scores) != questions.keys():
        raise HTTPException(422, f'{item.student_id}: para validar, puntúe todas las cuestiones; use un borrador si faltan puntuaciones')
    allowed = {cid for q in questions.values() for cid in q.get('criteria', [])}
    seen = set()
    for evidence in item.evidence:
        if evidence.criterion_id not in allowed:
            raise HTTPException(422, f'{item.student_id}: evidencia de un criterio ajeno a la prueba: {evidence.criterion_id}')
        if evidence.criterion_id in seen:
            raise HTTPException(422, f'{item.student_id}: evidencia duplicada para {evidence.criterion_id}')
        seen.add(evidence.criterion_id)
    data = item.model_dump(exclude={'overwrite','teacher_review_confirmed'})
    data.update(compute(assessment, data))
    return data, assessment, student


def preserve_ai_review(item,existing,row,assessment):
    if not existing or not existing.get('ai_report'):
        return row
    from app import repository as repo
    report=existing['ai_report']
    if item.validated:
        if not item.teacher_review_confirmed:
            raise HTTPException(422,'Confirme la revisión docente de la propuesta IA antes de validarla')
        if report.get('simulated') and not repo.DEMO_MODE:
            raise HTTPException(422,'Una simulación no puede validar una evaluación ordinaria')
    row['ai_report']={**report,'teacher_validated':item.validated,
                      'status':'CLOSED' if item.validated else ('REVIEW_REQUIRED' if report['review_reasons'] else 'CORRECTED')}
    row.update(compute(assessment,row))
    return row


def prepare_import(payload, db):
    if payload.get('format') not in (None, 'DOCIO_CORRECTION_V1'):
        raise HTTPException(422, 'Formato no compatible')
    raw_rows = payload.get('corrections', payload.get('students'))
    if not isinstance(raw_rows, list) or not raw_rows:
        raise HTTPException(422, 'corrections/students debe ser una lista no vacía')
    overwrite = payload.get('overwrite', False)
    if not isinstance(overwrite, bool):
        raise HTTPException(422, 'overwrite debe ser true o false')
    rows, changes, skipped, seen, revision = [], [], [], set(), []
    existing_map = {(c['assessment_id'], c['student_id']): c for c in db['corrections']}
    for index, raw in enumerate(raw_rows, 1):
        if not isinstance(raw, dict):
            raise HTTPException(422, f'Fila {index}: debe ser un objeto')
        evidence = raw.get('evidence', raw.get('evidences', []))
        if isinstance(evidence, dict):
            evidence = [{**(value if isinstance(value, dict) else {'text': value}), 'criterion_id': cid}
                        for cid, value in evidence.items()]
        try:
            item = CorrectionIn.model_validate({**raw, 'assessment_id': raw.get('assessment_id') or payload.get('assessment_id'),
                                                'evidence': evidence, 'overwrite': overwrite})
        except ValidationError as error:
            messages = '; '.join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in error.errors())
            raise HTTPException(422, f'Fila {index}: {messages}') from error
        key = (item.assessment_id, item.student_id)
        if key in seen:
            raise HTTPException(422, f'Fila {index}: corrección duplicada para {item.assessment_id} / {item.student_id}')
        seen.add(key)
        row, assessment, student = validate_correction(item, db)
        existing = existing_map.get(key)
        protected = bool(existing and existing.get('validated'))
        action = 'skipped' if protected and not overwrite else ('replace_validated' if protected else ('update' if existing else 'create'))
        if action!='skipped':
            row=preserve_ai_review(item,existing,row,assessment)
        revision.append({'row': row, 'before': existing, 'assessment': assessment, 'student': student})
        changes.append({'assessment_id': item.assessment_id, 'student_id': item.student_id,
                        'title': assessment['title'], 'action': action, 'validated': item.validated,
                        'final_score': row['final_score'], 'previous_score': existing.get('final_score') if existing else None})
        if action == 'skipped':
            skipped.append({'assessment_id': item.assessment_id, 'student_id': item.student_id, 'reason': 'validated'})
        else:
            rows.append(row)
    token = hashlib.sha256(json.dumps({'overwrite': overwrite, 'records': revision}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    if payload.get('expected_revision') is not None and payload['expected_revision'] != token:
        raise HTTPException(409, 'Los registros han cambiado desde la vista previa. Revise el lote de nuevo antes de importarlo')
    report = {'format': 'DOCIO_CORRECTION_V1', 'total': len(changes), 'importable': len(rows),
              'skipped': skipped, 'changes': changes, 'revision': token,
              'replacements': sum(c['action'] == 'replace_validated' for c in changes)}
    return rows, report
