import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from job_finder.firecrawl import FirecrawlClient, FirecrawlError, SearchCandidate, normalize_candidate, normalize_location, search_items
from job_finder.models import Job
from job_finder.service import collect


class CandidateNormalizationTests(unittest.TestCase):
    def test_location_normalizer_rejects_title_and_company(self):
        self.assertEqual(normalize_location('Software Engineer - India', 'Software Engineer - India', 'JumpCloud'), ('Unknown', False))
        self.assertEqual(normalize_location('JumpCloud', 'Software Engineer', 'JumpCloud'), ('Unknown', False))

    def test_location_normalizer_handles_remote_and_preferred_locations(self):
        self.assertEqual(normalize_location('Remote', 'Engineer', 'Acme')[0], 'Remote - India eligibility unknown')
        self.assertEqual(normalize_location('Remote, India', 'Engineer', 'Acme')[0], 'Remote - India')
        self.assertEqual(normalize_location('Hyderabad, India', 'Engineer', 'Acme')[0], 'Hyderabad, India')
        self.assertEqual(normalize_location('Delhi NCR', 'Engineer', 'Acme')[0], 'Delhi NCR')
    def test_string_url_candidate_is_normalized(self):
        candidate = normalize_candidate('https://careers.example.com/jobs/123')
        self.assertEqual(candidate, SearchCandidate('https://careers.example.com/jobs/123'))

    def test_dictionary_candidate_is_normalized(self):
        candidate = normalize_candidate({'sourceURL': 'https://careers.example.com/jobs/456'})
        self.assertEqual(candidate, SearchCandidate('https://careers.example.com/jobs/456'))

    def test_v2_envelope_uses_web_results_not_dictionary_keys(self):
        items = search_items({'data': {'web': [{'url': 'https://careers.example.com/jobs/1'}]}})
        self.assertEqual(items, [{'url': 'https://careers.example.com/jobs/1'}])

    def test_invalid_candidate_is_skipped(self):
        self.assertIsNone(normalize_candidate('not-a-url'))


class CollectionCompatibilityTests(unittest.TestCase):
    def _settings(self, directory):
        return SimpleNamespace(database_path=Path(directory) / 'jobs.db', firecrawl_api_key='test', firecrawl_base_url='https://api.example.com', boards_path=Path(directory) / 'no-boards.json')

    def test_collect_processes_string_and_dictionary_candidates(self):
        class FakeClient:
            def __init__(self, *_): self.scraped = []; self.failures = {'400': 0, '403': 0, '429': 0, 'other': 0}
            def discover(self, _): return ['https://careers.example.com/string', {'url': 'https://careers.example.com/dict'}, None]
            def should_defer(self, _): return False
            def scrape_job(self, url, candidate=None):
                self.scraped.append(url)
                return Job(company='Example Technology', title='Cloud Engineer', original_url=url, posting_date='2026-08-12', description='Python Azure CI/CD')
        with tempfile.TemporaryDirectory() as directory, patch('job_finder.service.FirecrawlClient', FakeClient):
            discovered, stored = collect(self._settings(directory), 25)
        self.assertEqual(discovered, 2)
        self.assertEqual(stored, 2)


class FirecrawlRequestTests(unittest.TestCase):
    def client(self): return FirecrawlClient('key', 'https://api.example.com', request_delay_seconds=0, sleep=lambda _: None, jitter=lambda *_: 0)

    def test_successful_scrape_uses_v2_markdown_contract(self):
        client = self.client(); captured = {}
        def post(path, payload, **kwargs):
            captured.update(path=path, payload=payload)
            return {'data': {'markdown': '# Cloud Engineer', 'metadata': {'title': 'Example - Cloud Engineer', 'sourceURL': kwargs['url']}}}
        client._post = post
        job = client.scrape_job('https://jobs.lever.co/example/123', SearchCandidate('https://jobs.lever.co/example/123'))
        self.assertEqual(captured['path'], '/v2/scrape')
        self.assertEqual(captured['payload']['formats'], ['markdown'])
        self.assertNotIn('jsonOptions', captured['payload'])
        self.assertEqual(job.title, 'Cloud Engineer')

    def test_http_errors_are_structured_and_only_429_retries(self):
        client = self.client(); calls = []
        def raise_400(*_, **__):
            calls.append(1); raise __import__('urllib.error').error.HTTPError('x', 400, 'bad', None, BytesIO(b'{"code":"BAD_REQUEST","error":"invalid body"}'))
        with patch('job_finder.firecrawl.urlopen', raise_400):
            with self.assertRaises(FirecrawlError) as caught: client._post('/v2/scrape', {'url': 'https://x'}, url='https://x')
        self.assertEqual(caught.exception.code, 'BAD_REQUEST'); self.assertFalse(caught.exception.retryable); self.assertEqual(len(calls), 1)

    def test_403_is_non_retryable_and_429_backs_off(self):
        client = self.client(); attempts = []
        def responses(*_, **__):
            attempts.append(1)
            if len(attempts) == 1: raise __import__('urllib.error').error.HTTPError('x', 429, 'limited', None, BytesIO(b'{"code":"RATE_LIMIT","error":"slow down"}'))
            class Response:
                def __enter__(self): return self
                def __exit__(self, *_): return False
                def read(self): return b'{"data": {}}'
            return Response()
        with patch('job_finder.firecrawl.urlopen', responses): self.assertEqual(client._post('/v2/scrape', {'url': 'https://x'}, url='https://x'), {'data': {}})
        self.assertEqual(len(attempts), 2); self.assertEqual(client.failures['429'], 1)

    def test_batch_scraping_returns_jobs_and_individual_remains_available(self):
        client = self.client(); candidate = SearchCandidate('https://jobs.lever.co/example/123')
        client._post = lambda *_args, **_kwargs: {'id': 'batch-1'}
        client._request = lambda *_args, **_kwargs: {'status': 'completed', 'data': [{'markdown': '# Cloud Engineer', 'metadata': {'title': 'Example - Cloud Engineer', 'sourceURL': candidate.url}}]}
        jobs = client.scrape_many([candidate])
        self.assertEqual(jobs[candidate.url].title, 'Cloud Engineer')
