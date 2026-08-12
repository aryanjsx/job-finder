import tempfile
import unittest
from pathlib import Path

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
