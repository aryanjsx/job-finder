from __future__ import annotations

import logging

from .database import JobStore
from .firecrawl import ATS_HOSTS, FirecrawlClient, FirecrawlError, normalize_candidate
from .scoring import score


def collect(settings, limit: int) -> tuple[int, int]:
    store = JobStore(getattr(settings, 'database_url', None) or settings.database_path)
    client = FirecrawlClient(settings.firecrawl_api_key, settings.firecrawl_base_url, getattr(settings, 'firecrawl_request_delay_seconds', 1.25), getattr(settings, 'firecrawl_max_concurrency', 2))
    accepted = 0
    try:
        discovered = 0
        candidates = []
        for raw_candidate in client.discover(limit):
            candidate = normalize_candidate(raw_candidate)
            if not candidate:
                continue
            discovered += 1
            if client.should_defer(candidate):
                logging.info('Deferring blocked discovery source %s; prefer an original company/ATS URL.', candidate.url)
                continue
            candidates.append(candidate)
        ats = [candidate for candidate in candidates if any(host in candidate.url for host in ATS_HOSTS)]
        batched = {}
        if len(ats) > 1:
            try:
                batched = client.scrape_many(ats[:6])
            except FirecrawlError as exc:
                logging.warning('Batch scrape failed; using throttled individual fallback: %s', exc)
        for candidate in candidates:
            try:
                job = batched.get(candidate.url) if candidate.url in batched else client.scrape_job(candidate.url, candidate)
                if job: store.upsert(score(job)); accepted += 1
            except FirecrawlError as exc:
                logging.warning('Scrape failed: %s', exc)
        logging.info('Firecrawl failures: HTTP 400=%s, HTTP 403=%s, HTTP 429=%s, other=%s', client.failures['400'], client.failures['403'], client.failures['429'], client.failures['other'])
        return discovered, accepted
    finally:
        store.close()
