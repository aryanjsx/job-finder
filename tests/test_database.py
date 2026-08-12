import tempfile
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Mock psycopg2 in sys.modules so it does not fail to import if not installed.
mock_psycopg2 = MagicMock()
mock_psycopg2_extras = MagicMock()
sys.modules['psycopg2'] = mock_psycopg2
sys.modules['psycopg2.extras'] = mock_psycopg2_extras

from job_finder.database import JobStore
from job_finder.models import Job
from job_finder.scoring import score


class DatabaseTests(unittest.TestCase):
    def test_same_listing_becomes_seen_then_updated(self):
        with tempfile.TemporaryDirectory() as temp:
            store = JobStore(Path(temp) / 'jobs.db')
            first = score(Job(company='Acme', title='Cloud Engineer', original_url='https://careers.acme.com/123', description='Python Azure', posting_date='2026-08-12'))
            self.assertEqual(store.upsert(first).status, 'NEW')
            self.assertEqual(store.upsert(first).status, 'SEEN')
            first.description = 'Python Azure Kubernetes'
            self.assertEqual(store.upsert(score(first)).status, 'UPDATED')
            self.assertEqual(len(store.report_rows()), 1)
            store.close()


class PostgresDatabaseTests(unittest.TestCase):
    def test_postgres_initialization_and_operations(self):
        # Reset mocks
        mock_psycopg2.reset_mock()
        mock_psycopg2_extras.reset_mock()
        
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_psycopg2.connect.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor
        
        # Mock RealDictCursor type or class
        mock_psycopg2_extras.RealDictCursor = MagicMock()
        
        # Mock fetchone to simulate a NEW job (no existing description_hash)
        mock_cursor.fetchone.return_value = None
        # Mock fetchall to return a single job dict for report_rows
        mock_cursor.fetchall.return_value = [{'job_id': 'sample-1', 'title': 'Cloud Engineer'}]
        
        store = JobStore('postgresql://user:pass@host:5432/db')
        self.assertTrue(store.is_postgres)
        
        # Verify schema execution
        mock_conn.cursor.assert_called_once()
        self.assertIn('CREATE TABLE IF NOT EXISTS jobs', mock_cursor.execute.call_args_list[0][0][0])
        
        # Test upsert
        job = Job(company='Acme', title='Cloud Engineer', original_url='https://careers.acme.com/123', description='Python Azure', posting_date='2026-08-12')
        stored_job = store.upsert(job)
        
        self.assertEqual(stored_job.status, 'NEW')
        
        # Verify that %s is used as a placeholder in PostgreSQL query
        called_queries = [args[0] for args, _ in mock_cursor.execute.call_args_list]
        self.assertTrue(any('%s' in q for q in called_queries))
        self.assertFalse(any('?' in q for q in called_queries))
        
        # Test report_rows
        rows = store.report_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['title'], 'Cloud Engineer')
        
        store.close()
        mock_cursor.close.assert_called_once()
        mock_conn.close.assert_called_once()


if __name__ == '__main__':
    unittest.main()
