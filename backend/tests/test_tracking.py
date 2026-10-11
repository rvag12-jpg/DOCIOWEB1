"""Regression tests using only synthetic records in an isolated database."""
import os
os.environ['DATABASE_URL'] = ''
os.environ['DOCIO_DEMO_MODE'] = 'false'

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from app import repository as repo
from app.main import app


class TrackingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.patch_db = patch.object(repo, 'DB_PATH', Path(self.temp.name) / 'test.sqlite3')
        self.patch_legacy = patch.object(repo, 'LEGACY_PATH', Path(self.temp.name) / 'none.json')
        self.patch_db.start()
        self.patch_legacy.start()
        self.addCleanup(self.patch_db.stop)
        self.addCleanup(self.patch_legacy.stop)
        self.client = TestClient(app)
        repo.put('groups', {'group_id': 'G1', 'name': 'Grupo sintético'})
        for sid in ('TEST-001', 'TEST-002', 'TEST-003'):
            repo.put('students', {'student_id': sid, 'group_id': 'G1'})
        # Reverse insertion order checks ordering by actual assessment date.
        self.assessment('NEW', '2026-10-20', '1ª', 'C1')
        self.assessment('OLD', '2026-09-10', 'Inicial', 'C1')
        self.assessment('OTHER', '2026-10-10', '1ª', 'C2')

    def assessment(self, aid, day, evaluation, criterion):
        return repo.put('assessments', {
            'assessment_id': aid, 'title': aid, 'group_id': 'G1',
            'assessment_date': day, 'evaluation': evaluation, 'assessment_type': 'exam',
            'questions': [{'question_id': 'Q1', 'title': 'Cuestión sintética',
                           'max_score': 2, 'knowledge_ids': ['K1'], 'criteria': [criterion]}],
        })

    def correction(self, aid, score, student='TEST-001', validated=True):
        response = self.client.put('/api/v1/docio/corrections', json={
            'assessment_id': aid, 'student_id': student,
            'scores': {'Q1': score}, 'validated': validated,
        })
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def overview(self, query=''):
        response = self.client.get('/api/v1/docio/group-overview/G1' + query)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_no_evidence_is_distinct_from_achieved_and_zero(self):
        self.correction('NEW', 0)
        rows = {s['student_id']: s for s in self.overview()['students']}
        self.assertEqual(rows['TEST-001']['status'], 'pending')
        self.assertEqual(rows['TEST-001']['latest_criteria'], {'C1': 0.0})
        self.assertEqual(rows['TEST-002']['status'], 'no_evidence')
        self.assertIsNone(rows['TEST-002']['mean'])
        self.assertEqual(rows['TEST-002']['missing_criteria'], ['C1', 'C2'])

    def test_drafts_do_not_affect_tracking_profile_or_recovery(self):
        self.correction('OLD', .4)
        self.correction('NEW', 2, validated=False)
        row = self.overview()['students'][0]
        self.assertEqual(row['latest_criteria'], {'C1': 2.0})
        self.assertEqual(row['drafts'], 1)
        self.assertEqual(row['assessments'], 1)
        profile = self.client.get('/api/v1/docio/student-profile/TEST-001').json()
        self.assertEqual([a['assessment_id'] for a in profile['attempts']], ['OLD'])
        recovery = self.client.get('/api/v1/docio/recovery/G1/TEST-001').json()
        self.assertEqual(recovery['pending'], ['C1'])

    def test_profile_respects_evaluation_filter(self):
        self.correction('OLD', .4)
        self.correction('NEW', 1.6)
        profile = self.client.get('/api/v1/docio/student-profile/TEST-001', params={'evaluation': '1ª'}).json()
        self.assertEqual(profile['evaluation'], '1ª')
        self.assertEqual([a['assessment_id'] for a in profile['attempts']], ['NEW'])
        self.assertEqual(profile['mean'], 8.0)
        self.assertEqual(self.overview('?evaluation=1%C2%AA')['students'][0]['latest_criteria'], {'C1': 8.0})

    def test_latest_criterion_and_group_mean_use_chronology(self):
        self.correction('NEW', 1.6)
        self.correction('OLD', .4)
        self.correction('NEW', 1.2, student='TEST-002')
        overview = self.overview()
        self.assertEqual(overview['students'][0]['latest_criteria'], {'C1': 8.0})
        self.assertEqual(overview['criterion_means']['C1'], 7.0)
        self.assertIsNone(overview['criterion_means']['C2'])
        recovery = self.client.get('/api/v1/docio/recovery/G1/TEST-001').json()
        self.assertEqual(recovery['recovered'], ['C1'])
        profile = self.client.get('/api/v1/docio/student-profile/TEST-001').json()
        self.assertEqual([a['assessment_id'] for a in profile['attempts']], ['OLD', 'NEW'])

    def test_partial_evidence_is_not_green(self):
        self.correction('NEW', 2)
        row = self.overview()['students'][0]
        self.assertEqual(row['status'], 'partial')
        self.assertEqual(row['missing_criteria'], ['C2'])
        self.correction('OTHER', 1)
        row = self.overview()['students'][0]
        self.assertEqual(row['status'], 'achieved')

    def test_metadata_edit_preserves_questions_and_validated_correction(self):
        correction = self.correction('NEW', 1.6)
        before = repo.state()
        assessment = next(a for a in before['assessments'] if a['assessment_id'] == 'NEW')
        response = self.client.patch('/api/v1/docio/assessments/NEW', json={
            'title': '  Prueba revisada  ', 'evaluation': '2ª', 'assessment_date': '2026-11-01',
        })
        self.assertEqual(response.status_code, 200, response.text)
        updated = response.json()
        self.assertEqual(updated['title'], 'Prueba revisada')
        self.assertEqual(updated['questions'], assessment['questions'])
        self.assertEqual(updated['group_id'], assessment['group_id'])
        self.assertEqual(updated['assessment_type'], assessment['assessment_type'])
        self.assertEqual(repo.state()['corrections'], before['corrections'])
        self.assertEqual(correction['final_score'], 8.0)
        self.assertEqual(repo.history(1)[0]['action'], 'metadata')
        profile = self.client.get('/api/v1/docio/student-profile/TEST-001', params={'evaluation': '2ª'}).json()
        self.assertEqual(profile['attempts'][0]['date'], '2026-11-01')

    def test_metadata_date_changes_chronology_without_regrading(self):
        self.correction('OLD', .4)
        self.correction('NEW', 1.6)
        response = self.client.patch('/api/v1/docio/assessments/OLD', json={
            'title': 'OLD', 'evaluation': 'Inicial', 'assessment_date': '2026-12-01',
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.overview()['students'][0]['latest_criteria'], {'C1': 2.0})
        self.assertEqual(self.client.get('/api/v1/docio/export/NEW').json()['corrections'][0]['final_score'], 8.0)

    def test_invalid_metadata_is_rejected_without_writing(self):
        before = repo.state()
        for fields in (
            {'title': 'Prueba', 'evaluation': '3ª', 'assessment_date': '2026-10-10'},
            {'title': 'Prueba', 'evaluation': '1ª', 'assessment_date': '2026-02-30'},
            {'title': '  ', 'evaluation': '1ª', 'assessment_date': '2026-10-10'},
        ):
            with self.subTest(fields=fields):
                self.assertEqual(self.client.patch('/api/v1/docio/assessments/NEW', json=fields).status_code, 422)
        self.assertEqual(repo.state(), before)
        self.assertEqual(self.client.patch('/api/v1/docio/assessments/MISSING', json={
            'title': 'Prueba', 'evaluation': '1ª', 'assessment_date': '2026-10-10',
        }).status_code, 404)

    def test_unknown_group_and_invalid_filters(self):
        self.assertEqual(self.client.get('/api/v1/docio/group-overview/MISSING').status_code, 404)
        self.assertEqual(self.client.get('/api/v1/docio/group-overview/G1?threshold=11').status_code, 422)
        self.assertEqual(self.client.get('/api/v1/docio/group-overview/G1?evaluation=3').status_code, 422)
        self.assertEqual(self.client.get('/api/v1/docio/student-profile/TEST-001?evaluation=3').status_code, 422)

    def test_storage_summary_returns_counts_without_student_records(self):
        self.correction('NEW', 1)
        response = self.client.get('/api/v1/docio/storage')
        self.assertEqual(response.status_code, 200)
        summary = response.json()
        self.assertEqual(summary['record_counts']['students'], 3)
        self.assertEqual(summary['record_counts']['corrections'], 1)
        self.assertNotIn('TEST-001', response.text)
        self.assertNotIn('questions', response.text)

    def test_scoring_is_consistent_across_views(self):
        correction = self.correction('NEW', 1.26)
        score = correction['final_score']
        tracking = self.client.get('/api/v1/docio/tracking').json()['rows'][0]
        profile = self.client.get('/api/v1/docio/student-profile/TEST-001').json()['attempts'][0]
        self.assertEqual(score, 6.3)
        self.assertEqual(tracking['final_score'], score)
        self.assertEqual(profile['final_score'], score)
        self.assertEqual(tracking['criterion_scores'], correction['criterion_scores'])


if __name__ == '__main__':
    unittest.main()
