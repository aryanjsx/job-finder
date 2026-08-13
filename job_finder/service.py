from __future__ import annotations

import json
import logging
from collections import Counter
from datetime import date
from pathlib import Path
from urllib.error import HTTPError, URLError

from .ats import fetch_board, fetch_boards, slugs_from_urls
from .database import JobStore
from .firecrawl import ATS_HOSTS, BOARD_DISCOVERY_QUERIES, FirecrawlClient, FirecrawlError, normalize_candidate
from .scoring import rejection_reason, score

BOARDS_PATH = Path('config/boards.json')
RUN_METRICS_PATH = Path('data/last_run_metrics.json')


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


def load_run_metrics(path: Path = RUN_METRICS_PATH) -> dict:
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def save_run_metrics(metrics: dict, path: Path = RUN_METRICS_PATH) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(metrics, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    except OSError as exc:
        logging.warning('Could not write run metrics %s: %s', path, exc)


def discover_boards(settings, limit: int) -> dict[str, int]:
    """Search once, probe new ATS boards once, and retain only India-capable boards."""
    boards_path = Path(getattr(settings, 'boards_path', BOARDS_PATH))
    boards = load_boards(boards_path)
    known = {(board['ats'], board['slug'].lower()) for board in boards}
    stats = {'slugs_seen': 0, 'already_known': 0, 'probed': 0, 'kept': 0,
             'dropped_for_no_india_roles': 0}
    try:
        client = FirecrawlClient(settings.firecrawl_api_key, settings.firecrawl_base_url,
                                 getattr(settings, 'firecrawl_request_delay_seconds', 1.25),
                                 getattr(settings, 'firecrawl_max_concurrency', 2))
    except ValueError as exc:
        stats = {'slugs_seen': 0, 'already_known': 0, 'probed': 0, 'kept': 0,
                 'dropped_for_no_india_roles': 0}
        logging.error('Board discovery skipped: %s', exc)
        logging.info('Board discovery: slugs seen=0, already known=0, probed=0, kept=0, dropped-for-no-India-roles=0')
        return stats
    candidates = client.discover_queries(BOARD_DISCOVERY_QUERIES, limit)
    seen = slugs_from_urls([candidate.url for candidate in candidates])
    stats['slugs_seen'] = len(seen)
    for board in seen:
        if (board['ats'], board['slug'].lower()) in known:
            stats['already_known'] += 1
            continue
        stats['probed'] += 1
        try:
            jobs = fetch_board(board['ats'], board['slug'])
        except (HTTPError, URLError, TimeoutError, ValueError) as exc:
            logging.warning('Could not probe %s/%s: %s', board['ats'], board['slug'], exc)
            stats['dropped_for_no_india_roles'] += 1
            continue
        if not jobs:
            stats['dropped_for_no_india_roles'] += 1
            continue
        board['india_count'] = len(jobs)
        board['last_ok'] = date.today().isoformat()
        boards.append(board)
        known.add((board['ats'], board['slug'].lower()))
        stats['kept'] += 1
    save_boards(boards, boards_path)
    logging.info('Board discovery: slugs seen=%s, already known=%s, probed=%s, kept=%s, dropped-for-no-India-roles=%s',
                 stats['slugs_seen'], stats['already_known'], stats['probed'], stats['kept'], stats['dropped_for_no_india_roles'])
    return stats


def prune_boards(settings) -> list[str]:
    """Disable boards with no India-relevant postings without deleting history."""
    boards_path = Path(getattr(settings, 'boards_path', BOARDS_PATH))
    boards = load_boards(boards_path)
    disabled = []
    for board in boards:
        try:
            jobs = fetch_board(board['ats'], board['slug'])
        except (HTTPError, URLError, TimeoutError, ValueError) as exc:
            logging.warning('Could not prune-check %s/%s: %s', board['ats'], board['slug'], exc)
            continue
        board['last_ok'] = date.today().isoformat()
        board['india_count'] = len(jobs)
        if not jobs:
            board['disabled'] = True
            disabled.append(board['slug'])
        else:
            board.pop('disabled', None)
    save_boards(boards, boards_path)
    logging.info('Disabled zero-India boards: %s', ', '.join(disabled) or 'none')
    return disabled


def collect(settings, limit: int, all_locations: bool = False) -> tuple[int, int, int]:
    store = JobStore(getattr(settings, 'database_url', None) or settings.database_path)
    accepted = 0
    pipeline = 0
    discovered = 0
    run = {
        'run_boards_fetched': 0,
        'run_listings_fetched': 0,
        'run_india_relevant': 0,
        'run_new_rows': 0,
        'run_updated_rows': 0,
        'run_rows_in_pipeline': 0,
        'run_rejection_reasons': Counter(),
        'score_histogram': Counter(),
        'boards_failed': 0,
        'boards_zero_india': 0,
    }
    boards_path = Path(getattr(settings, 'boards_path', BOARDS_PATH))
    run_path = Path(getattr(settings, 'run_metrics_path', RUN_METRICS_PATH))

    def store_scored(job):
        nonlocal accepted, pipeline
        job = score(job)
        store.upsert(job)
        accepted += 1
        pipeline += job.recommendation != 'DO NOT INCLUDE'
        run['run_new_rows'] += job.status == 'NEW'
        run['run_updated_rows'] += job.status == 'UPDATED'
        run['run_rows_in_pipeline'] += job.recommendation != 'DO NOT INCLUDE'
        run['run_rejection_reasons'][rejection_reason(job)] += job.recommendation == 'DO NOT INCLUDE'
        run['score_histogram'][f'{min(90, (job.match_score // 10) * 10)}-{min(99, (job.match_score // 10) * 10 + 9)}'] += 1

    try:
        boards = load_boards(boards_path)
        for job in fetch_boards(boards, all_locations=all_locations, metrics=run):
            discovered += 1
            store_scored(job)
        save_boards(boards, boards_path)
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
        for job in fetch_boards(learned, all_locations=all_locations, metrics=run):
            store_scored(job)
        if learned:
            save_boards(boards + learned, boards_path)
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
                    store_scored(job)
            except FirecrawlError as exc:
                logging.warning('Scrape failed: %s', exc)
        logging.info('Firecrawl failures: HTTP 400=%s, HTTP 403=%s, HTTP 429=%s, other=%s', client.failures['400'], client.failures['403'], client.failures['429'], client.failures['other'])
        return discovered, accepted, pipeline
    finally:
        run['run_rejection_reasons'] = dict(run['run_rejection_reasons'])
        run['score_histogram'] = dict(sorted(run['score_histogram'].items()))
        logging.info('Run score histogram: %s', run['score_histogram'])
        save_run_metrics(run, run_path)
        store.close()
