"""PostgreSQL integration tests in an isolated, temporary test schema."""
import os
import unittest
import tempfile
from pathlib import Path
from contextlib import contextmanager
from uuid import uuid4
from unittest.mock import patch

from app import repository as repo

TEST_URL = os.getenv('DOCIO_TEST_POSTGRES_URL', '')


@unittest.skipUnless(TEST_URL, 'Synthetic PostgreSQL test service is not configured')
class PostgresTests(unittest.TestCase):
    def setUp(self):
        import psycopg
        from psycopg import sql
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.schema = 'docio_test_' + uuid4().hex
        with psycopg.connect(TEST_URL, autocommit=True) as connection:
            connection.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(self.schema)))
        self.addCleanup(self.drop_schema)

        @contextmanager
        def isolated_connection():
            connection = psycopg.connect(TEST_URL, options='-c search_path=' + self.schema)
            try:
                yield connection
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            finally:
                connection.close()

        for name, value in (('POSTGRES', True), ('DEMO_MODE', False), ('conn', isolated_connection), ('LEGACY_PATH', Path(self.temp.name) / 'absent.json')):
            active = patch.object(repo, name, value)
            active.start()
            self.addCleanup(active.stop)

    def drop_schema(self):
        import psycopg
        from psycopg import sql
        with psycopg.connect(TEST_URL, autocommit=True) as connection:
            connection.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(self.schema)))

    def test_committed_records_survive_new_connections(self):
        group = {'group_id': 'TEST-PG-GROUP', 'name': 'Grupo PostgreSQL ficticio'}
        repo.put('groups', group, 'test-create')
        self.assertEqual(repo.backend(), 'postgresql')
        self.assertEqual(repo.state()['groups'], [group])
        self.assertEqual(repo.counts()['groups'], 1)
        self.assertEqual(repo.history(1)[0]['action'], 'test-create')
        repo.put('groups', {**group, 'name': 'Grupo ficticio actualizado'}, 'test-update')
        self.assertEqual(repo.state()['groups'][0]['name'], 'Grupo ficticio actualizado')
        self.assertTrue(repo.remove('groups', group['group_id']))
        self.assertEqual(repo.state()['groups'], [])
        self.assertEqual(repo.history(1)[0]['action'], 'delete')

    def test_demo_isolation_on_postgresql(self):
        control = {'group_id': 'TEST-PG-CONTROL', 'name': 'Registro de control inventado'}
        repo.put('groups', control)
        with patch.object(repo, 'DEMO_MODE', True):
            self.assertEqual(repo.counts()['students'], 3)
            self.assertEqual(repo.state()['groups'][0]['group_id'], 'DEMO-GROUP')
            demo = repo.state()['groups'][0]
            repo.put('groups', {**demo, 'name': 'DEMO PG editada'})
            self.assertEqual(repo.state()['groups'][0]['name'], 'DEMO PG editada')
        self.assertEqual(repo.state()['groups'], [control])
        self.assertEqual(repo.counts()['students'], 0)

    def test_batch_lock_commit_and_rollback_on_postgresql(self):
        repo.init_db()
        rows = [{'assessment_id':'TEST-PG-ASSESSMENT','student_id':f'TEST-PG-{i}','scores':{}} for i in (1,2)]
        original = repo._put
        def write_and_fail(*args):
            original(*args)
            if args[3]['student_id']=='TEST-PG-2':
                raise RuntimeError('Synthetic PostgreSQL failure')
        with patch.object(repo,'_put',side_effect=write_and_fail), self.assertRaises(RuntimeError):
            repo.import_corrections(lambda db:(rows, {}))
        self.assertEqual(repo.counts()['corrections'],0)
        self.assertEqual(repo.history(),[])
        result = repo.import_corrections(lambda db:(rows, {}))
        self.assertEqual(result['imported'],2)
        self.assertEqual(repo.counts()['corrections'],2)
        self.assertEqual(len(repo.history()),2)

    def test_ai_job_checkpoints_and_drafts_survive_connections(self):
        from app.api.ai import demo_images
        from app.storage import store
        from app.services import ai_jobs,ai_provider
        from app.services.corrector import framework_template
        root=Path(self.temp.name)/'synthetic-images';root.mkdir()
        with patch.object(repo,'DEMO_MODE',True),patch.object(store,'root',root),patch.dict(os.environ,{'DOCIO_AI_PROVIDER':'mock'}):
            document=demo_images()
            source=repo.get_record('assessments','DEMO-FOLLOWUP')
            group=repo.get_record('groups','DEMO-GROUP')
            payload=ai_jobs.JobIn.model_validate({
                'request_id':'synthetic-pg-ai-001','source_assessment_id':source['assessment_id'],
                'title':'Prueba PG ficticia','evaluation':'1ª','assessment_date':'2026-10-11',
                'framework':framework_template(source,group,True),'framework_confirmed':True,
                'assignments':[{'student_id':f'DEMO-{n:03d}','document_id':document.document_id} for n in (1,2,3)]})
            job=ai_jobs.create_job(payload)
            with patch.object(ai_provider.httpx,'Client',side_effect=AssertionError('Synthetic PG job cannot call OpenAI')):
                ai_jobs.run_job(job['job_id'])
            saved=repo.get_record('ai_jobs',job['job_id'])
            self.assertEqual(saved['status'],'completed')
            self.assertEqual(ai_jobs.summary(saved)['completed'],3)
            self.assertEqual(len(repo.list_records('ai_jobs')),1)
            self.assertNotIn('ai_jobs',repo.state())
            drafts=[r for r in repo.state()['corrections'] if r['assessment_id']==job['assessment_id']]
            self.assertEqual(len(drafts),3)
            self.assertTrue(all(not r['validated'] and r['final_score']==6.5 and r['ai_report']['simulated'] for r in drafts))


if __name__ == '__main__':
    unittest.main()
