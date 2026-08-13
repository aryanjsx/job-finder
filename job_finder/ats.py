"""Public ATS JSON board APIs.

Firecrawl scrapes rendered HTML, where posting_date and salary are usually absent
or unlabelled — every stored row carried posting_date='Unknown' and
salary='Not disclosed'. The Lever, Ashby and Greenhouse board APIs publish both as
structured fields, without auth and without per-page cost.

Field names here were verified against the live APIs on 2026-08-13.
urllib only; no third-party HTTP client.
"""
from __future__ import annotations

import html
import json
import logging
import re
import time
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .extractors import extract_experience
from .models import Job

LOGGER = logging.getLogger(__name__)

LEVER_API = 'https://api.lever.co/v0/postings/{slug}?mode=json'
ASHBY_API = 'https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true'
GREENHOUSE_API = 'https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true'

BOARD_HOSTS = {
    'jobs.lever.co': 'lever',
    'boards.greenhouse.io': 'greenhouse',
    'job-boards.greenhouse.io': 'greenhouse',
    'jobs.ashbyhq.com': 'ashby',
}

DELAY_BETWEEN_BOARDS = 0.4
MAX_ATTEMPTS = 3
USER_AGENT = 'job-finder/1.0 (+https://github.com/aryanjsx/job-finder)'

GREENHOUSE_DATE_CONCERN = 'Greenhouse exposes updated_at, not the original posting date'


def fetch_json(url: str, sleep=time.sleep) -> Any:
    """GET JSON with exponential backoff on 429 and 5xx. Max 3 attempts."""
    last: Exception | None = None
    for attempt in range(MAX_ATTEMPTS):
        request = Request(url, headers={'User-Agent': USER_AGENT, 'Accept': 'application/json'})
        try:
            with urlopen(request, timeout=30) as response:
                return json.loads(response.read().decode('utf-8', 'replace'))
        except HTTPError as error:
            last = error
            if error.code != 429 and error.code < 500:
                raise
            if attempt < MAX_ATTEMPTS - 1:
                sleep(2 ** attempt)
        except (URLError, TimeoutError, ValueError) as error:
            last = error
            if attempt < MAX_ATTEMPTS - 1:
                sleep(2 ** attempt)
    raise last or RuntimeError('Unreachable fetch state')


def _clean_html(raw: str) -> str:
    """Greenhouse `content` is entity-escaped HTML. Unescape, then strip tags."""
    text = html.unescape(html.unescape(raw or ''))
    text = re.sub(r'(?is)<(script|style).*?</\1>', ' ', text)
    text = re.sub(r'(?i)<br\s*/?>|</p>|</div>|</li>|</h[1-6]>', '\n', text)
    text = re.sub(r'<[^>]+>', ' ', text)
    return re.sub(r'[ \t]{2,}', ' ', re.sub(r'\n{3,}', '\n\n', text)).strip()


def _iso_date_from_epoch_ms(value: Any) -> str:
    """Lever createdAt is epoch milliseconds and undocumented. Never guess."""
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return 'Unknown'
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 'Unknown'
    if number <= 0:
        return 'Unknown'
    try:
        moment = datetime.fromtimestamp(number / 1000, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return 'Unknown'
    if not 2000 <= moment.year <= 2100:
        return 'Unknown'
    return moment.date().isoformat()


def _iso_date_from_timestamp(value: Any) -> str:
    """Ashby publishedAt / Greenhouse updated_at are ISO 8601 strings."""
    if not isinstance(value, str) or not value.strip():
        return 'Unknown'
    text = value.strip().replace('Z', '+00:00')
    try:
        return datetime.fromisoformat(text).date().isoformat()
    except ValueError:
        return 'Unknown'


def _lever_salary(posting: Mapping[str, Any]) -> str:
    salary_range = posting.get('salaryRange')
    if not isinstance(salary_range, Mapping):
        return 'Not disclosed'
    currency = str(salary_range.get('currency') or '').strip()
    low, high = salary_range.get('min'), salary_range.get('max')
    parts = [f'{value:,.0f}' for value in (low, high) if isinstance(value, (int, float)) and value]
    if not parts:
        return 'Not disclosed'
    return f"{currency} {' - '.join(parts)}".strip()


def _ashby_salary(posting: Mapping[str, Any]) -> str:
    compensation = posting.get('compensation')
    if not isinstance(compensation, Mapping):
        return 'Not disclosed'
    summary = compensation.get('scrapeableCompensationSalarySummary')
    return str(summary).strip() if summary else 'Not disclosed'


def lever_jobs(slug: str, payload: Iterable[Any]) -> list[Job]:
    jobs = []
    for posting in payload or []:
        if not isinstance(posting, Mapping):
            continue
        title = str(posting.get('text') or '').strip()
        if not title:
            continue
        categories = posting.get('categories') if isinstance(posting.get('categories'), Mapping) else {}
        location = str(categories.get('location') or posting.get('country') or '').strip() or 'Unknown'
        posting_date = _iso_date_from_epoch_ms(posting.get('createdAt'))
        hosted = str(posting.get('hostedUrl') or '')
        description = str(posting.get('descriptionPlain') or '')
        jobs.append(Job(
            company=slug.replace('-', ' ').title(),
            title=title,
            location=location,
            work_mode=str(posting.get('workplaceType') or '').title() or 'Unknown',
            salary=_lever_salary(posting),
            posting_date=posting_date,
            source=f'Lever board API ({slug})',
            original_url=hosted,
            application_url=str(posting.get('applyUrl') or hosted),
            description=description,
            experience=extract_experience(description),
            external_job_id=str(posting.get('id') or ''),
            original_url_verified=True,
            posting_date_verified=posting_date != 'Unknown',
        ))
    return jobs


def ashby_jobs(slug: str, payload: Mapping[str, Any]) -> list[Job]:
    jobs = []
    postings = payload.get('jobs') if isinstance(payload, Mapping) else None
    for posting in postings or []:
        if not isinstance(posting, Mapping) or posting.get('isListed') is False:
            continue
        title = str(posting.get('title') or '').strip()
        if not title:
            continue
        posting_date = _iso_date_from_timestamp(posting.get('publishedAt'))
        job_url = str(posting.get('jobUrl') or '')
        description = str(posting.get('descriptionPlain') or '')
        jobs.append(Job(
            company=slug.replace('-', ' ').title(),
            title=title,
            location=str(posting.get('location') or '').strip() or 'Unknown',
            work_mode=str(posting.get('workplaceType') or '').title() or 'Unknown',
            salary=_ashby_salary(posting),
            posting_date=posting_date,
            source=f'Ashby board API ({slug})',
            original_url=job_url,
            application_url=str(posting.get('applyUrl') or job_url),
            description=description,
            experience=extract_experience(description),
            external_job_id=str(posting.get('id') or ''),
            original_url_verified=True,
            posting_date_verified=posting_date != 'Unknown',
            company_type=str(posting.get('department') or '').strip() or 'Unknown',
        ))
    return jobs


def greenhouse_jobs(slug: str, payload: Mapping[str, Any]) -> list[Job]:
    """updated_at is a re-save, not a publication date, so the date is never
    treated as verified regardless of whether the API supplied one."""
    jobs = []
    postings = payload.get('jobs') if isinstance(payload, Mapping) else None
    for posting in postings or []:
        if not isinstance(posting, Mapping):
            continue
        title = str(posting.get('title') or '').strip()
        if not title:
            continue
        location = posting.get('location')
        location_name = str(location.get('name') if isinstance(location, Mapping) else location or '').strip()
        url = str(posting.get('absolute_url') or '')
        description = _clean_html(str(posting.get('content') or ''))
        jobs.append(Job(
            company=str(posting.get('company_name') or '').strip() or slug.replace('-', ' ').title(),
            title=title,
            location=location_name or 'Unknown',
            posting_date=_iso_date_from_timestamp(posting.get('updated_at')),
            source=f'Greenhouse board API ({slug})',
            original_url=url,
            application_url=url,
            description=description,
            experience=extract_experience(description),
            external_job_id=str(posting.get('id') or ''),
            original_url_verified=True,
            posting_date_verified=False,
            potential_concerns=GREENHOUSE_DATE_CONCERN,
        ))
    return jobs


PARSERS = {'lever': (LEVER_API, lever_jobs), 'ashby': (ASHBY_API, ashby_jobs),
           'greenhouse': (GREENHOUSE_API, greenhouse_jobs)}


def fetch_board(ats: str, slug: str, fetch=fetch_json) -> list[Job]:
    if ats not in PARSERS:
        LOGGER.warning('Unknown ATS %r for slug %r', ats, slug)
        return []
    template, parser = PARSERS[ats]
    return parser(slug, fetch(template.format(slug=slug)))


def fetch_boards(boards: Iterable[Mapping[str, str]], fetch=fetch_json, sleep=time.sleep) -> list[Job]:
    """Fetch every configured board, tolerating individual board failures."""
    jobs: list[Job] = []
    for index, board in enumerate(boards or []):
        ats, slug = str(board.get('ats') or ''), str(board.get('slug') or '')
        if not ats or not slug:
            continue
        if index:
            sleep(DELAY_BETWEEN_BOARDS)
        try:
            found = fetch_board(ats, slug, fetch)
        except (HTTPError, URLError, TimeoutError, ValueError) as error:
            LOGGER.warning('Board fetch failed for %s/%s: %s', ats, slug, error)
            continue
        LOGGER.info('Fetched %s postings from %s board %s', len(found), ats, slug)
        jobs.extend(found)
    return jobs


_ID_SEGMENT = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-|^\d{4,}$|^[0-9a-f]{16,}$', re.I)


def slugs_from_urls(urls) -> list[dict]:
    """Harvest {ats, slug, company} from jobs.lever.co / boards.greenhouse.io /
    jobs.ashbyhq.com POSTING urls (slug + an id segment). Dedupe. Ignore all else."""
    found: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for raw in urls or []:
        if not isinstance(raw, str) or not raw.strip():
            continue
        parsed = urlparse(raw.strip())
        ats = BOARD_HOSTS.get(parsed.netloc.lower())
        if not ats:
            continue
        parts = [part for part in parsed.path.strip('/').split('/') if part]
        if ats == 'greenhouse' and parts and parts[0] == 'embed':
            continue
        if len(parts) < 2:
            continue
        slug = parts[0]
        identifiers = [part for part in parts[1:] if _ID_SEGMENT.match(part)]
        if not identifiers:
            continue
        key = (ats, slug.lower())
        if key in seen:
            continue
        seen.add(key)
        found.append({'ats': ats, 'slug': slug, 'company': slug.replace('-', ' ').title()})
    return found
