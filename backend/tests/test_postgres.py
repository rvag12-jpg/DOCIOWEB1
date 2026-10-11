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


if __name__ == '__main__':
    unittest.main()
