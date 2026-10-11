"""JSON exchange regressions, using only an isolated synthetic demo."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from app import repository as repo
from app.main import app


class ExchangeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        for name, value in (('DB_PATH', Path(self.temp.name)/'exchange.sqlite3'),
                            ('LEGACY_PATH', Path(self.temp.name)/'absent.json'),
                            ('POSTGRES', False), ('DEMO_MODE', True)):
            active = patch.object(repo, name, value)
            active.start()
            self.addCleanup(active.stop)
        self.client = TestClient(app)
        repo.init_db()

    def row(self, sid='DEMO-003', **changes):
        return {'student_id': sid, 'scores': {'Q1': 1.2, 'Q2': 1.4}, 'validated': True, **changes}

    def payload(self, rows=None, **changes):
        return {'format': 'DOCIO_CORRECTION_V1', 'assessment_id': 'DEMO-FOLLOWUP',
                'corrections': [self.row()] if rows is None else rows, **changes}

    def post(self, payload, preview=False):
        return self.client.post('/api/v1/docio/import'+('/preview' if preview else ''),
                                content=json.dumps(payload), headers={'Content-Type':'application/json'})

    def test_preview_does_not_write_and_preserves_validated_by_default(self):
        before, audit = repo.state(), repo.history()
        payload = self.payload([self.row('DEMO-001'), self.row()])
        response = self.post(payload, preview=True)
        self.assertEqual(response.status_code, 200, response.text)
        preview = response.json()
        self.assertEqual(preview['importable'], 1)
        self.assertEqual([c['action'] for c in preview['changes']], ['skipped', 'update'])
        self.assertEqual(repo.state(), before)
        self.assertEqual(repo.history(), audit)
        result = self.post({**payload, 'expected_revision': preview['revision']})
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()['imported'], 1)
        rows = {c['student_id']: c for c in repo.state()['corrections'] if c['assessment_id']=='DEMO-FOLLOWUP'}
        self.assertEqual(rows['DEMO-001']['scores'], {'Q1':1.6,'Q2':1.4})
        self.assertTrue(rows['DEMO-003']['validated'])
        self.assertEqual(rows['DEMO-003']['final_score'], 6.5)

    def test_explicit_overwrite_is_reported_and_audited(self):
        payload = self.payload([self.row('DEMO-001')], overwrite=True)
        preview = self.post(payload, preview=True).json()
        self.assertEqual(preview['replacements'], 1)
        self.assertEqual(preview['changes'][0]['previous_score'], 7.5)
        self.assertEqual(preview['changes'][0]['final_score'], 6.5)
        response = self.post({**payload, 'expected_revision':preview['revision']})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(repo.history(1)[0]['action'], 'import')
        self.assertIsNotNone(repo.history(1)[0]['before_data'])

    def test_error_in_last_row_does_not_write_first_row(self):
        before, audit = repo.state(), repo.history()
        response = self.post(self.payload([self.row(), self.row('DEMO-NOT-FOUND')]))
        self.assertEqual(response.status_code, 404, response.text)
        self.assertEqual(repo.state(), before)
        self.assertEqual(repo.history(), audit)

    def test_write_failure_rolls_back_records_and_audit(self):
        before, audit = repo.state(), repo.history()
        original = repo._put
        calls = []
        def fail_second(*args):
            calls.append(args)
            original(*args)
            if len(calls)==2:
                raise RuntimeError('Synthetic write failure')
        with patch.object(repo, '_put', side_effect=fail_second), self.assertRaises(RuntimeError):
            self.post(self.payload([self.row(), self.row('DEMO-002')], overwrite=True))
        self.assertEqual(repo.state(), before)
        self.assertEqual(repo.history(), audit)

    def test_changed_record_invalidates_preview(self):
        payload = self.payload()
        preview = self.post(payload, preview=True).json()
        old = next(c for c in repo.state()['corrections'] if c['student_id']=='DEMO-003')
        repo.put('corrections', {**old, 'comment':'Synthetic concurrent edit'})
        before = repo.state()
        response = self.post({**payload,'expected_revision':preview['revision']})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(repo.state(), before)

    def test_invalid_payloads_are_rejected_without_writes(self):
        before, audit = repo.state(), repo.history()
        for payload in (
            self.payload([]), self.payload([None]), self.payload([self.row(),self.row()]),
            self.payload([self.row(scores={'Q1':3,'Q2':1})]),
            self.payload([self.row(scores={'Q1':-1,'Q2':1})]),
            self.payload([self.row(scores={'Q1':float('nan'),'Q2':1})]),
            self.payload([self.row(scores={'Q1':True,'Q2':1})]),
            self.payload([self.row(scores={'Q1':1,'UNKNOWN':1})]),
            self.payload([self.row(scores={'Q1':1})]),
            self.payload([self.row(validated='false')]), self.payload(overwrite='false'),
            self.payload([self.row(evidence=[{'criterion_id':'DEMO-OTHER','text':'Invented'}])]),
            self.payload([self.row(evidence=[{'criterion_id':'DEMO-C1','text':'Invented','score':11}])]),
        ):
            with self.subTest(payload=payload):
                response = self.post(payload)
                self.assertEqual(response.status_code, 422, response.text)
                self.assertEqual(repo.state(), before)
                self.assertEqual(repo.history(), audit)

    def test_student_must_belong_to_assessment_group(self):
        repo.put('students', {'student_id':'DEMO-OUTSIDE','group_id':'DEMO-OTHER-GROUP'})
        response = self.post(self.payload([self.row('DEMO-OUTSIDE')]))
        self.assertEqual(response.status_code, 422)
        response = self.client.put('/api/v1/docio/corrections',json={**self.row('DEMO-OUTSIDE'),'assessment_id':'DEMO-FOLLOWUP'})
        self.assertEqual(response.status_code, 422)

    def test_draft_can_omit_scores_and_legacy_evidence_dictionary_is_supported(self):
        payload = self.payload([self.row(scores={'Q1':1}, validated=False,
                                        evidences={'DEMO-C1':{'text':'Invented observation','score':5}})])
        payload['students'] = payload.pop('corrections')
        response = self.post(payload)
        self.assertEqual(response.status_code, 200, response.text)
        exported = self.client.get('/api/v1/docio/export/DEMO-FOLLOWUP').json()
        row = next(c for c in exported['corrections'] if c['student_id']=='DEMO-003')
        self.assertEqual(row['evidence'], [{'criterion_id':'DEMO-C1','text':'Invented observation','score':5.0}])
        self.assertFalse(row['validated'])
        self.assertEqual(self.post(exported).json()['skipped'][0]['reason'], 'validated')

    def test_export_round_trip_preserves_all_correction_fields(self):
        exported = self.client.get('/api/v1/docio/export/DEMO-FOLLOWUP').json()
        before = repo.state()['corrections']
        response = self.post({**exported, 'overwrite':True})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['imported'], 3)
        self.assertEqual(repo.state()['corrections'], before)


if __name__ == '__main__':
    unittest.main()
