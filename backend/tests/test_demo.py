"""Isolation checks. Every record used here is invented."""
import json
import os
os.environ['DOCIO_DEMO_MODE'] = 'false'

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from app import repository as repo
from app.main import app


class DemoTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        for name, value in (
            ('DB_PATH', Path(self.temp.name) / 'test.sqlite3'),
            ('LEGACY_PATH', Path(self.temp.name) / 'legacy.json'),
            ('POSTGRES', False), ('DEMO_MODE', True),
        ):
            active = patch.object(repo, name, value)
            active.start()
            self.addCleanup(active.stop)
        self.client = TestClient(app)

    def test_seed_contains_only_explicit_demo_identifiers(self):
        state = repo.state()
        self.assertEqual(len(state['students']), 3)
        self.assertEqual(len(state['assessments']), 2)
        self.assertEqual(len(state['corrections']), 4)
        for student in state['students']:
            self.assertTrue(student['student_id'].startswith('DEMO-'))
        self.assertTrue(all(a['title'].endswith('ficticia') for a in state['assessments']))
        self.assertTrue(all('no es un criterio curricular oficial' in c['title'] for c in state['criteria']))

    def test_legacy_fixture_is_not_read_in_demo_mode(self):
        repo.LEGACY_PATH.write_text(json.dumps({'students': [{'student_id': 'CONTROL-SYNTHETIC'}]}))
        with patch.object(Path, 'read_text', side_effect=AssertionError('Demo must not read legacy files')):
            state = repo.state()
        self.assertNotIn('CONTROL-SYNTHETIC', json.dumps(state))

    def test_demo_tables_are_separate_from_standard_tables(self):
        with patch.object(repo, 'DEMO_MODE', False):
            repo.put('groups', {'group_id': 'CONTROL-GROUP', 'name': 'Invented control fixture'})
            before = repo.state()
        demo = repo.state()
        self.assertEqual(demo['groups'][0]['group_id'], 'DEMO-GROUP')
        repo.put('students', {'student_id': 'DEMO-004', 'group_id': 'DEMO-GROUP'})
        with patch.object(repo, 'DEMO_MODE', False):
            self.assertEqual(repo.state(), before)
            self.assertNotIn('DEMO-004', json.dumps(repo.state()))

    def test_repeated_initialization_preserves_demo_edits(self):
        state = repo.state()
        group = state['groups'][0]
        repo.put('groups', {**group, 'name': 'DEMO editada'})
        for _ in range(2):
            self.assertEqual(repo.state()['groups'][0]['name'], 'DEMO editada')
        self.assertEqual(repo.counts()['groups'], 1)

    def test_demo_api_exercises_missing_evidence_and_recovery(self):
        storage = self.client.get('/api/v1/docio/storage').json()
        self.assertEqual(storage['data_mode'], 'demo')
        overview = self.client.get('/api/v1/docio/group-overview/DEMO-GROUP').json()
        rows = {s['student_id']: s for s in overview['students']}
        self.assertEqual(rows['DEMO-001']['status'], 'achieved')
        self.assertEqual(rows['DEMO-002']['status'], 'pending')
        self.assertEqual(rows['DEMO-003']['status'], 'no_evidence')
        self.assertEqual(rows['DEMO-003']['drafts'], 1)
        recovery = self.client.get('/api/v1/docio/recovery/DEMO-GROUP/DEMO-001').json()
        self.assertEqual(set(recovery['recovered']), {'DEMO-C1', 'DEMO-C2'})
        profile = self.client.get('/api/v1/docio/student-profile/DEMO-001', params={'evaluation': '1ª'}).json()
        self.assertEqual(len(profile['attempts']), 1)
        self.assertEqual(profile['mean'], 7.5)


if __name__ == '__main__':
    unittest.main()
