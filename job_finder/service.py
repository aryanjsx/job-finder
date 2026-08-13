from __future__ import annotations

import json
import logging
from pathlib import Path

from .ats import fetch_boards, slugs_from_urls
from .database import JobStore
from .firecrawl import ATS_HOSTS, FirecrawlClient, FirecrawlError, normalize_candidate
from .scoring import score

BOARDS_PATH = Path('config/boards.json')


def load_boards(path: Path = BOARDS_PATH) -> list[dict]:
    if not path.exists():
        logging.info('No board config at %s; skipping ATS APIs.', path)
        return []
    try:
        boards = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        logging.warning('Could not read board config %s: %s', path, exc)
        return []
    return [board for board in boards if isinstance(board, dict) and board.get('ats') and board.get('slug')]


def save_boards(boards: list[dict], path: Path = BOARDS_PATH) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(boards, indent=2) + '\n', encoding='utf-8')
    except OSError as exc:
        logging.warning('Could not write board config %s: %s', path, exc)


def remember_boards(urls, boards: list[dict], path: Path = BOARDS_PATH) -> list[dict]:
    """A slug is discovered once and reused forever; a scrape is paid every run."""
    known = {(board['ats'], board['slug'].lower()) for board in boards}
    new = [board for board in slugs_from_urls(urls) if (board['ats'], board['slug'].lower()) not in known]
    if new:
        logging.info('Learned %s new ATS board(s): %s', len(new), ', '.join(b['slug'] for b in new))
        save_boards(boards + new, path)
    return new


def collect(settings, limit: int, all_locations: bool = False) -> tuple[int, int, int]:
    store = JobStore(getattr(settings, 'database_url', None) or settings.database_path)
    accepted = 0
    pipeline = 0
    discovered = 0
    boards_path = Path(getattr(settings, 'boards_path', BOARDS_PATH))
    try:
        boards = load_boards(boards_path)
        for job in fetch_boards(boards, all_locations=all_locations):
            discovered += 1
            job = score(job)
            store.upsert(job)
            accepted += 1
            pipeline += job.recommendation != 'DO NOT INCLUDE'
        logging.info('ATS board APIs contributed %s listings from %s boards.', accepted, len(boards))

        try:
            client = FirecrawlClient(settings.firecrawl_api_key, settings.firecrawl_base_url, getattr(settings, 'firecrawl_request_delay_seconds', 1.25), getattr(settings, 'firecrawl_max_concurrency', 2))
        except ValueError as exc:
            logging.warning('Skipping Firecrawl discovery: %s', exc)
            return discovered, accepted, pipeline

        candidates = []
        raw_candidates = list(client.discover(limit))
        for raw_candidate in raw_candidates:
            candidate = normalize_candidate(raw_candidate)
            if not candidate:
                continue
            discovered += 1
            if client.should_defer(candidate):
                logging.info('Deferring blocked discovery source %s; prefer an original company/ATS URL.', candidate.url)
                continue
            candidates.append(candidate)
        learned = remember_boards([candidate.url for candidate in candidates], boards, boards_path)
        learned_slugs = {(board['ats'], board['slug'].lower()) for board in learned}
        for job in fetch_boards(learned, all_locations=all_locations):
            job = score(job)
            store.upsert(job)
            accepted += 1
            pipeline += job.recommendation != 'DO NOT INCLUDE'
        harvested = {(entry['ats'], entry['slug'].lower()) for entry in slugs_from_urls([c.url for c in candidates])}
        already_covered = {(b['ats'], b['slug'].lower()) for b in boards} | learned_slugs

        def covered_by_board(candidate) -> bool:
            entry = slugs_from_urls([candidate.url])
            return bool(entry) and (entry[0]['ats'], entry[0]['slug'].lower()) in already_covered

        candidates = [candidate for candidate in candidates if not covered_by_board(candidate)]
        logging.info('Board APIs cover %s of the discovered slugs; scraping %s remaining pages.', len(harvested), len(candidates))

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
                if job:
                    job = score(job)
                    store.upsert(job)
                    accepted += 1
                    pipeline += job.recommendation != 'DO NOT INCLUDE'
            except FirecrawlError as exc:
                logging.warning('Scrape failed: %s', exc)
        logging.info('Firecrawl failures: HTTP 400=%s, HTTP 403=%s, HTTP 429=%s, other=%s', client.failures['400'], client.failures['403'], client.failures['429'], client.failures['other'])
        return discovered, accepted, pipeline
    finally:
        store.close()
