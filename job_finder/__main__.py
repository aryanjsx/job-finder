from __future__ import annotations

import argparse
import logging

from .config import Settings
from .database import JobStore
from .emailer import send_report
from .reporter import generate_report
from .service import collect


def main() -> None:
    parser = argparse.ArgumentParser(description='Find, rank, report, and optionally email job listings.')
    parser.add_argument('command', choices=('collect', 'finalize'))
    parser.add_argument('--limit', type=int, default=25)
    args = parser.parse_args(); logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    settings = Settings.from_env()
    if args.command == 'collect':
        discovered, stored = collect(settings, args.limit); logging.info('Collection complete: searched %s candidates, stored %s listings.', discovered, stored); return
    store = JobStore(getattr(settings, 'database_url', None) or settings.database_path)
    try:
        rows = store.report_rows(); report = generate_report(rows, settings.report_dir); sent = send_report(settings, report, rows); logging.info('Report created at %s; email sent: %s', report, sent)
    finally: store.close()


if __name__ == '__main__': main()
