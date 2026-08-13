from __future__ import annotations

import json
import logging
import random
import re
import time
from dataclasses import dataclass
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .extractors import derive_company_title, extract_experience
from .extractors import normalize_location as _normalize_location
from .models import Job

LOGGER = logging.getLogger(__name__)
SEARCH_QUERIES = [
    'site:boards.greenhouse.io OR site:jobs.lever.co (Cloud Engineer OR DevOps Engineer OR Software Engineer) India',
    '(Cloud Engineer OR Platform Engineer OR Backend Engineer) (Hyderabad OR Gurgaon OR Noida OR Remote) jobs India',
    '(Software Engineer OR Full Stack Engineer) (Azure OR Python OR React) jobs India',
]
BOARD_DISCOVERY_QUERIES = [
    'site:jobs.lever.co (software engineer OR backend OR devops) India',
    'site:boards.greenhouse.io (software engineer OR backend OR devops) India',
    'site:jobs.ashbyhq.com (software engineer OR backend OR devops) India',
    'site:jobs.lever.co (Bangalore OR Hyderabad OR Pune OR Gurugram) engineer',
    'site:boards.greenhouse.io (Bangalore OR Hyderabad OR Pune OR Gurugram) engineer',
]
BLOCKED_DISCOVERY_HOSTS = {'linkedin.com', 'indeed.com', 'naukri.com', 'glassdoor.co.in', 'wellfound.com'}
ATS_HOSTS = ('jobs.lever.co', 'boards.greenhouse.io', 'myworkdayjobs.com', 'jobs.ashbyhq.com', 'smartrecruiters.com')
LOCATION_TERMS = ('hyderabad', 'gurgaon', 'gurugram', 'noida', 'delhi ncr', 'delhi', 'kolkata', 'india', 'remote')


@dataclass(frozen=True)
class SearchCandidate:
    url: str
    source: str = 'Firecrawl web search'
    title: str = ''
    description: str = ''


@dataclass
class FirecrawlError(Exception):
    status: int | None
    code: str | None
    message: str
    url: str
    retryable: bool
    source: str = ''

    def __str__(self) -> str:
        status = self.status if self.status is not None else 'network'
        code = f' {self.code}' if self.code else ''
        return f'Firecrawl {status}{code}: {self.message} (url={self.url}; retryable={self.retryable})'


def normalize_candidate(candidate: Any) -> SearchCandidate | None:
    if isinstance(candidate, SearchCandidate): return candidate
    if isinstance(candidate, str): url, title, description = candidate.strip(), '', ''
    elif isinstance(candidate, Mapping):
        raw = candidate.get('url') or candidate.get('sourceURL')
        url = raw.strip() if isinstance(raw, str) else ''
        title = str(candidate.get('title') or '')
        description = str(candidate.get('description') or candidate.get('markdown') or '')
    else:
        LOGGER.warning('Skipping unsupported Firecrawl candidate type: %s', type(candidate).__name__); return None
    parsed = urlparse(url)
    if parsed.scheme not in {'http', 'https'} or not parsed.netloc:
        LOGGER.warning('Skipping invalid Firecrawl candidate URL: %r', url); return None
    return SearchCandidate(url, title=title, description=description)


def search_items(response: Mapping[str, Any]) -> list[Any]:
    data = response.get('data', [])
    if isinstance(data, list): return data
    if isinstance(data, Mapping) and isinstance(data.get('web', []), list): return data['web']
    LOGGER.warning('Unexpected Firecrawl search data shape: %s', type(data).__name__); return []


normalize_location = _normalize_location   # re-exported for existing imports


class FirecrawlClient:
    """Firecrawl v2 client with conservative throttling and typed API errors."""
    def __init__(self, api_key: str, base_url: str, request_delay_seconds: float = 1.25, max_concurrency: int = 2, sleep=time.sleep, jitter=random.uniform):
        if not api_key: raise ValueError('FIRECRAWL_API_KEY is required for live collection.')
        self.api_key, self.base_url = api_key, base_url.rstrip('/')
        self.request_delay_seconds, self.max_concurrency = request_delay_seconds, max(1, min(max_concurrency, 2))
        self.sleep, self.jitter, self._last_request = sleep, jitter, 0.0
        self.failures: dict[str, int] = {'400': 0, '403': 0, '429': 0, 'other': 0}

    def _throttle(self) -> None:
        wait = self.request_delay_seconds - (time.monotonic() - self._last_request)
        if wait > 0: self.sleep(wait)
        self._last_request = time.monotonic()

    @staticmethod
    def _error(error: HTTPError, url: str, source: str) -> FirecrawlError:
        try: body = json.loads(error.read().decode('utf-8', 'replace'))
        except (ValueError, UnicodeDecodeError): body = {}
        code = body.get('code') or body.get('errorCode')
        message = body.get('error') or body.get('message') or error.reason
        retryable = error.code == 429 or error.code >= 500
        return FirecrawlError(error.code, str(code) if code else None, str(message), url, retryable, source)

    def _request(self, method: str, path: str, payload: dict | None = None, url: str = '', source: str = '') -> dict:
        last: FirecrawlError | None = None
        for attempt in range(3):
            self._throttle()
            data = json.dumps(payload).encode() if payload is not None else None
            request = Request(f'{self.base_url}{path}', data=data, headers={'Authorization': f'Bearer {self.api_key}', 'Content-Type': 'application/json'}, method=method)
            try:
                with urlopen(request, timeout=60) as response: return json.loads(response.read().decode())
            except HTTPError as raw:
                last = self._error(raw, url, source)
                self.failures[str(raw.code) if raw.code in (400, 403, 429) else 'other'] += 1
                if not last.retryable: raise last
                if raw.code == 429 and attempt < 2: self.sleep((2 ** attempt) + self.jitter(0, 0.5)); continue
                raise last
            except (URLError, TimeoutError) as raw:
                last = FirecrawlError(None, None, str(raw), url, True, source); self.failures['other'] += 1
                if attempt < 2: self.sleep((2 ** attempt) + self.jitter(0, 0.5)); continue
                raise last
        raise last or RuntimeError('Unreachable request state')

    def _post(self, path: str, payload: dict, url: str = '', source: str = '') -> dict:
        return self._request('POST', path, payload, url, source)

    def discover(self, limit: int) -> list[SearchCandidate]:
        return self.discover_queries(SEARCH_QUERIES, limit)

    def discover_queries(self, queries: list[str], limit: int) -> list[SearchCandidate]:
        results: list[SearchCandidate] = []
        for query in queries:
            data = self._post('/v2/search', {'query': query, 'limit': max(5, limit // len(queries)), 'scrapeOptions': {'formats': ['markdown']}}, source='search')
            results.extend(item for raw in search_items(data) if (item := normalize_candidate(raw)))
        return results[:limit]

    def should_defer(self, candidate: SearchCandidate) -> bool:
        host = urlparse(candidate.url).netloc.lower()
        return any(host == blocked or host.endswith('.' + blocked) for blocked in BLOCKED_DISCOVERY_HOSTS)

    def scrape_job(self, url: str, candidate: SearchCandidate | None = None) -> Job | None:
        data = self._post('/v2/scrape', {'url': url, 'formats': ['markdown'], 'onlyMainContent': True, 'proxy': 'auto'}, url=url, source=urlparse(url).netloc)
        return self.job_from_payload(data.get('data', data), candidate or SearchCandidate(url))

    def scrape_many(self, candidates: list[SearchCandidate]) -> dict[str, Job | None]:
        """Batch preferred ATS pages; caller can fall back to individual scraping."""
        if not candidates: return {}
        urls = [candidate.url for candidate in candidates]
        started = self._post('/v2/batch/scrape', {'urls': urls, 'formats': ['markdown'], 'onlyMainContent': True, 'proxy': 'auto', 'ignoreInvalidURLs': True, 'maxConcurrency': self.max_concurrency}, source='batch')
        batch_id = started.get('id')
        if not batch_id: raise FirecrawlError(200, 'INVALID_BATCH_RESPONSE', 'Batch scrape response did not include an id.', '', False, 'batch')
        for _ in range(20):
            status = self._request('GET', f'/v2/batch/scrape/{batch_id}', url='batch', source='batch')
            if status.get('status') in {'completed', 'done'}:
                by_url = {candidate.url: candidate for candidate in candidates}
                return {payload.get('metadata', {}).get('sourceURL', ''): self.job_from_payload(payload, by_url.get(payload.get('metadata', {}).get('sourceURL', ''))) for payload in status.get('data', []) if isinstance(payload, Mapping)}
            if status.get('status') in {'failed', 'cancelled'}: raise FirecrawlError(200, 'BATCH_FAILED', f"Batch status: {status.get('status')}", 'batch', False, 'batch')
            self.sleep(2)
        raise FirecrawlError(None, 'BATCH_TIMEOUT', 'Batch did not complete before polling deadline.', 'batch', True, 'batch')

    @staticmethod
    def job_from_payload(payload: Mapping[str, Any], candidate: SearchCandidate) -> Job | None:
        markdown, metadata = str(payload.get('markdown') or ''), payload.get('metadata') or {}
        title = candidate.title or str(metadata.get('title') or '')
        if not title:
            match = re.search(r'^#{1,2}\s+(.+)$', markdown, re.MULTILINE); title = match.group(1).strip() if match else ''
        company, title = derive_company_title(candidate.url, title)
        if not company or not title:
            LOGGER.info('Skipping incomplete listing %s', candidate.url); return None
        location = 'Unknown'
        structured_location = str(metadata.get('location') or '')
        location, valid_location = normalize_location(structured_location, title, company)
        if not valid_location:
            for line in markdown.splitlines()[:40]:
                clean = line.strip(' #*-')
                location, valid_location = normalize_location(clean, title, company)
                if valid_location: break
        experience = extract_experience(markdown)
        work_mode = 'Remote' if 'remote' in markdown.lower() else ('Hybrid' if 'hybrid' in markdown.lower() else 'Onsite' if location != 'Unknown' else 'Unknown')
        return Job(company=company, title=title, location=location, work_mode=work_mode, experience=experience, source=candidate.source, original_url=str(metadata.get('sourceURL') or candidate.url), application_url=candidate.url, description=markdown or candidate.description, original_url_verified=any(host in candidate.url for host in ATS_HOSTS), company_type='Unknown')
