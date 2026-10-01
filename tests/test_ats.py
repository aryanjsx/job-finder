import json
import unittest
from pathlib import Path

from job_finder.ats import greenhouse_jobs, lever_jobs, slugs_from_urls


class AtsTests(unittest.TestCase):
    def lever_posting(self, **overrides):
        posting = {
            'id': 'lever-1',
            'text': 'Cloud Engineer',
            'categories': {'location': 'Hyderabad, India'},
            'country': 'IN',
            'workplaceType': 'hybrid',
            'createdAt': 1723507200000,
            'descriptionPlain': '2 years of relevant experience with Python.',
            'hostedUrl': 'https://jobs.lever.co/acme/12345678-1234-1234-1234-123456789abc',
            'applyUrl': 'https://jobs.lever.co/acme/12345678-1234-1234-1234-123456789abc/apply',
            'salaryRange': {'currency': 'INR', 'min': 1200000, 'max': 1800000},
        }
        posting.update(overrides)
        return posting

    def test_lever_epoch_ms_created_at_becomes_iso_date(self):
        job = lever_jobs('acme', [self.lever_posting()])[0]
        self.assertEqual(job.posting_date, '2024-08-13')
        self.assertTrue(job.posting_date_verified)
        self.assertEqual(job.salary, 'INR 1,200,000 - 1,800,000')

    def test_missing_lever_created_at_is_unverified(self):
        job = lever_jobs('acme', [self.lever_posting(createdAt=None)])[0]
        self.assertEqual(job.posting_date, 'Unknown')
        self.assertFalse(job.posting_date_verified)

    def test_lever_location_falls_back_to_country(self):
        job = lever_jobs('acme', [self.lever_posting(categories={}, country='IN')], all_locations=True)[0]
        self.assertEqual(job.location, 'IN')

    def test_lever_keeps_india_roles_only_unless_all_locations_requested(self):
        canada = self.lever_posting(categories={'location': 'Toronto, Canada'})
        india = self.lever_posting(id='lever-2', categories={'location': 'Noida, India'})
        self.assertEqual([job.location for job in lever_jobs('acme', [canada, india])], ['Noida, India'])
        self.assertEqual(len(lever_jobs('acme', [canada, india], all_locations=True)), 2)

    def test_greenhouse_updated_at_is_never_a_verified_posting_date(self):
        payload = {
            'jobs': [{
                'id': 42,
                'title': 'Platform Engineer',
                'company_name': 'Acme',
                'location': {'name': 'Bengaluru, India'},
                'updated_at': '2026-08-13T12:00:00+00:00',
                'absolute_url': 'https://boards.greenhouse.io/acme/jobs/42',
                'content': '&lt;p&gt;Python &amp; Kubernetes&lt;/p&gt;',
            }],
        }
        job = greenhouse_jobs('acme', payload)[0]
        self.assertEqual(job.posting_date, '2026-08-13')
        self.assertFalse(job.posting_date_verified)
        self.assertIn('updated_at', job.potential_concerns)
        self.assertEqual(job.description, 'Python & Kubernetes')

    def test_slugs_from_existing_board_config_and_ignores_search_sites(self):
        boards_path = Path(__file__).resolve().parents[1] / 'config' / 'boards.json'
        boards = json.loads(boards_path.read_text(encoding='utf-8'))
        urls = [
            f"https://jobs.lever.co/{board['slug']}/12345678-1234-1234-1234-123456789abc"
            for board in boards
        ]
        urls.extend([
            'https://reactjobs.io/location/india',
            'https://simplyhired.co.in/search?q=cloud+engineer',
            'https://in.jooble.org/jobs-cloud-engineer',
        ])
        found = slugs_from_urls(urls)
        self.assertEqual(len(found), 18)
        self.assertEqual({board['slug'] for board in found},
                         {board['slug'] for board in boards})


if __name__ == '__main__':
    unittest.main()
