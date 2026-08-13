from __future__ import annotations

import argparse
import logging
import sys

from .config import Settings
from .database import JobStore
from .emailer import send_report
from .reporter import generate_report, run_log_metrics
from .service import collect


def main() -> None:
    parser = argparse.ArgumentParser(description='Find, rank, report, and optionally email job listings.')
    parser.add_argument('command', choices=('collect', 'finalize'))
    parser.add_argument('--limit', type=int, default=25)
    parser.add_argument('--all-locations', action='store_true',
                        help='Keep global ATS board postings instead of India-relevant roles only.')
    args = parser.parse_args(); logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    settings = Settings.from_env()
    if args.command == 'collect':
        discovered, stored, pipeline = collect(settings, args.limit, args.all_locations); logging.info('Collection complete: searched %s candidates, stored %s listings, %s in pipeline.', discovered, stored, pipeline); return
    store = JobStore(getattr(settings, 'database_url', None) or settings.database_path)
    try:
        rows = store.report_rows()
        metrics = dict(run_log_metrics(rows))
        report = generate_report(rows, settings.report_dir)
        if metrics['rows_in_pipeline'] == 0:
            logging.error('Pipeline is empty; refusing to send report. Rejections: %s', metrics['rejection_reasons'])
            sys.exit(1)
        sent = send_report(settings, report, rows); logging.info('Report created at %s; email sent: %s', report, sent)
    finally: store.close()


if __name__ == '__main__': main()
