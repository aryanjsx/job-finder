"""Public ATS JSON board APIs, using urllib only."""
from __future__ import annotations

import html
import json
import logging
import re
import time
from datetime import date, datetime, timezone
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
        except (URLError, TimeoutError, ValueError) as error:
            last = error
        if attempt < MAX_ATTEMPTS - 1:
            sleep(2 ** attempt)
    raise last or RuntimeError('Unreachable fetch state')


def _clean_html(raw: str) -> str:
    text = html.unescape(html.unescape(raw or ''))
    text = re.sub(r'(?is)<(script|style).*?</\1>', ' ', text)
    text = re.sub(r'(?i)<br\s*/?>|</p>|</div>|</li>|</h[1-6]>', '\n', text)
    return re.sub(r'[ \t]{2,}', ' ', re.sub(r'\n{3,}', '\n\n', re.sub(r'<[^>]+>', ' ', text))).strip()


def _iso_date_from_epoch_ms(value: Any) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return 'Unknown'
    try:
        moment = datetime.fromtimestamp(float(value) / 1000, tz=timezone.utc)
    except (OverflowError, OSError, TypeError, ValueError):
        return 'Unknown'
    return moment.date().isoformat() if 2000 <= moment.year <= 2100 else 'Unknown'


def _iso_date_from_timestamp(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        return 'Unknown'
    try:
        return datetime.fromisoformat(value.strip().replace('Z', '+00:00')).date().isoformat()
    except ValueError:
        return 'Unknown'


def _lever_salary(posting: Mapping[str, Any]) -> str:
    value = posting.get('salaryRange')
    if not isinstance(value, Mapping):
        return 'Not disclosed'
    values = [f'{number:,.0f}' for number in (value.get('min'), value.get('max'))
              if isinstance(number, (int, float)) and number]
    return f"{str(value.get('currency') or '').strip()} {' - '.join(values)}".strip() if values else 'Not disclosed'


def _ashby_salary(posting: Mapping[str, Any]) -> str:
    value = posting.get('compensation')
    summary = value.get('scrapeableCompensationSalarySummary') if isinstance(value, Mapping) else None
    return str(summary).strip() if summary else 'Not disclosed'


def is_india_relevant(location: str) -> bool:
    """Board feeds are global. Keep only India / India-eligible-remote postings."""
    from .scoring import INDIA_TOKENS
    loc = (location or '').lower().strip()
    return bool(loc) and loc != 'unknown' and any(t in loc for t in INDIA_TOKENS)


def _job(company: str, title: str, location: str, source: str, description: str,
         posting_date: str, original_url: str, application_url: str, external_job_id: str,
         work_mode: str = 'Unknown', salary: str = 'Not disclosed', **kwargs) -> Job:
    values = {
        'company': company, 'title': title, 'location': location, 'work_mode': work_mode,
        'salary': salary, 'posting_date': posting_date, 'source': source,
        'original_url': original_url, 'application_url': application_url,
        'description': description, 'experience': extract_experience(description),
        'external_job_id': external_job_id, 'original_url_verified': True,
        'posting_date_verified': posting_date != 'Unknown',
    }
    values.update(kwargs)
    return Job(**values)


def lever_jobs(slug: str, payload: Iterable[Any], all_locations: bool = False, metrics: dict | None = None) -> list[Job]:
    jobs, fetched, relevant = [], 0, 0
    for posting in payload or []:
        if not isinstance(posting, Mapping) or not (title := str(posting.get('text') or '').strip()):
            continue
        fetched += 1
        categories = posting.get('categories') if isinstance(posting.get('categories'), Mapping) else {}
        location = str(categories.get('location') or posting.get('country') or '').strip() or 'Unknown'
        india_relevant = is_india_relevant(location)
        relevant += india_relevant
        if not all_locations and not india_relevant:
            continue
        description = str(posting.get('descriptionPlain') or '')
        hosted = str(posting.get('hostedUrl') or '')
        jobs.append(_job(
            slug.replace('-', ' ').title(), title, location, f'Lever board API ({slug})',
            description, _iso_date_from_epoch_ms(posting.get('createdAt')), hosted,
            str(posting.get('applyUrl') or hosted), str(posting.get('id') or ''),
            str(posting.get('workplaceType') or '').title() or 'Unknown', _lever_salary(posting)))
    LOGGER.info('Lever board %s: fetched %s, India-relevant %s', slug, fetched, relevant)
    if metrics is not None:
        metrics['run_listings_fetched'] += fetched
        metrics['run_india_relevant'] += relevant
    return jobs


def ashby_jobs(slug: str, payload: Mapping[str, Any], all_locations: bool = False, metrics: dict | None = None) -> list[Job]:
    jobs, fetched, relevant = [], 0, 0
    for posting in (payload.get('jobs') if isinstance(payload, Mapping) else []) or []:
        if not isinstance(posting, Mapping) or posting.get('isListed') is False or not (title := str(posting.get('title') or '').strip()):
            continue
        fetched += 1
        location = str(posting.get('location') or '').strip() or 'Unknown'
        india_relevant = is_india_relevant(location)
        relevant += india_relevant
        if not all_locations and not india_relevant:
            continue
        description = str(posting.get('descriptionPlain') or '')
        url = str(posting.get('jobUrl') or '')
        jobs.append(_job(
            slug.replace('-', ' ').title(), title, location, f'Ashby board API ({slug})',
            description, _iso_date_from_timestamp(posting.get('publishedAt')), url,
            str(posting.get('applyUrl') or url), str(posting.get('id') or ''),
            str(posting.get('workplaceType') or '').title() or 'Unknown', _ashby_salary(posting),
            company_type=str(posting.get('department') or '').strip() or 'Unknown'))
    LOGGER.info('Ashby board %s: fetched %s, India-relevant %s', slug, fetched, relevant)
    if metrics is not None:
        metrics['run_listings_fetched'] += fetched
        metrics['run_india_relevant'] += relevant
    return jobs


def greenhouse_jobs(slug: str, payload: Mapping[str, Any], all_locations: bool = False, metrics: dict | None = None) -> list[Job]:
    """Greenhouse exposes updated_at, never a verified posting date."""
    jobs, fetched, relevant = [], 0, 0
    for posting in (payload.get('jobs') if isinstance(payload, Mapping) else []) or []:
        if not isinstance(posting, Mapping) or not (title := str(posting.get('title') or '').strip()):
            continue
        fetched += 1
        raw_location = posting.get('location')
        location = str(raw_location.get('name') if isinstance(raw_location, Mapping) else raw_location or '').strip() or 'Unknown'
        india_relevant = is_india_relevant(location)
        relevant += india_relevant
        if not all_locations and not india_relevant:
            continue
        url = str(posting.get('absolute_url') or '')
        jobs.append(_job(
            str(posting.get('company_name') or '').strip() or slug.replace('-', ' ').title(),
            title, location, f'Greenhouse board API ({slug})',
            _clean_html(str(posting.get('content') or '')),
            _iso_date_from_timestamp(posting.get('updated_at')), url, url,
            str(posting.get('id') or ''), posting_date_verified=False,
            potential_concerns=GREENHOUSE_DATE_CONCERN))
    LOGGER.info('Greenhouse board %s: fetched %s, India-relevant %s', slug, fetched, relevant)
    if metrics is not None:
        metrics['run_listings_fetched'] += fetched
        metrics['run_india_relevant'] += relevant
    return jobs


PARSERS = {'lever': (LEVER_API, lever_jobs), 'ashby': (ASHBY_API, ashby_jobs),
           'greenhouse': (GREENHOUSE_API, greenhouse_jobs)}


def fetch_board(ats: str, slug: str, fetch=fetch_json, all_locations: bool = False,
                metrics: dict | None = None) -> list[Job]:
    if ats not in PARSERS:
        LOGGER.warning('Unknown ATS %r for slug %r', ats, slug)
        return []
    template, parser = PARSERS[ats]
    found = parser(slug, fetch(template.format(slug=slug)), all_locations, metrics)
    if metrics is not None:
        metrics['run_boards_fetched'] += 1
    return found


def fetch_boards(boards: Iterable[Mapping[str, str]], fetch=fetch_json, sleep=time.sleep,
                 all_locations: bool = False, metrics: dict | None = None) -> list[Job]:
    """Fetch every configured board, tolerating individual board failures."""
    jobs: list[Job] = []
    for index, board in enumerate(boards or []):
        ats, slug = str(board.get('ats') or ''), str(board.get('slug') or '')
        if not ats or not slug or board.get('disabled'):
            continue
        if index:
            sleep(DELAY_BETWEEN_BOARDS)
        try:
            found = fetch_board(ats, slug, fetch, all_locations, metrics)
        except (HTTPError, URLError, TimeoutError, ValueError) as error:
            LOGGER.warning('Board fetch failed for %s/%s: %s', ats, slug, error)
            if metrics is not None:
                metrics['boards_failed'] += 1
            continue
        board['last_ok'] = date.today().isoformat()
        board['india_count'] = len(found)
        if metrics is not None and board['india_count'] == 0:
            metrics['boards_zero_india'] += 1
        jobs.extend(found)
    return jobs


_ID_SEGMENT = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-|^\d{4,}$|^[0-9a-f]{16,}$', re.I)


def slugs_from_urls(urls) -> list[dict]:
    """Harvest {ats, slug, company} from jobs.lever.co / boards.greenhouse.io /
    jobs.ashbyhq.com POSTING urls (slug + an id segment). Dedupe. Ignore all else."""
    found, seen = [], set()
    for raw in urls or []:
        if not isinstance(raw, str) or not raw.strip():
            continue
        parsed = urlparse(raw.strip())
        ats = BOARD_HOSTS.get(parsed.netloc.lower())
        parts = [part for part in parsed.path.strip('/').split('/') if part]
        if not ats or (ats == 'greenhouse' and parts and parts[0] == 'embed') or len(parts) < 2:
            continue
        slug = parts[0]
        if not any(_ID_SEGMENT.match(part) for part in parts[1:]) or (ats, slug.lower()) in seen:
            continue
        seen.add((ats, slug.lower()))
        found.append({'ats': ats, 'slug': slug, 'company': slug.replace('-', ' ').title()})
    return found
