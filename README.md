# Aryan Job Finder

An opinionated, privacy-conscious job discovery service. It searches live listings with Firecrawl, normalizes only observed facts, scores them against Aryan Kumar's profile, stores changes in SQLite, and creates a daily Excel report. It never applies to jobs.

## Architecture

`Firecrawl search → scrape/structured extraction → normalize → reject/deduplicate → score → SQLite → Excel → optional SMTP`

The command is deliberately split into collection and finalization windows:

- `collect`: search, scrape, score, and persist only (07:00 / 12:00 / 18:00 IST)
- `finalize`: creates the report and sends one email after the final collection run (18:00 IST)

The included scheduler configuration is disabled by default. Enable it only after the manual test checklist below succeeds.

## Setup

1. Create a virtual environment with Python 3.11+ (no third-party Python packages are required).
2. Copy `.env.example` to `.env` and populate `FIRECRAWL_API_KEY`. Configure SMTP only when ready to send mail.
3. Run a safe manual collection:

```powershell
python -m job_finder collect --limit 25
python -m job_finder finalize
```

`collect` does not email. `finalize` produces `reports/Aryan_Job_Report_YYYY-MM-DD.xlsx`; it sends email only if `EMAIL_ENABLED=true`.

## Manual test gate

Before enabling the scheduler, run `python -m unittest discover -s tests -v`, then run `collect --limit 25` using a real Firecrawl key. Confirm the log reports discoveries, review the workbook worksheets and links, and run `finalize` once with a test inbox. The app will not create an OS scheduled task for you.

For Windows Task Scheduler, create three tasks in the same project folder:

```powershell
python -m job_finder collect --limit 30
python -m job_finder collect --limit 30
python -m job_finder collect --limit 30; python -m job_finder finalize
```

Set their start times to 07:00, 12:00, and 18:00 in the `Asia/Kolkata` time zone. Keep `SCHEDULER_ENABLED=false` until the manual test gate is complete, then set it to `true` as an audit acknowledgement.

## Data principles

- Missing salary is reported as `Not disclosed`; unknown dates remain `Unknown`.
- An application URL is only promoted when it is a direct observed source URL or a verified company-career URL; otherwise `original_url_verified` remains false.
- Listings older than 14 days and excluded role categories are retained as rejected audit records, not shown in final match sheets.
- Deduplication uses source URL, normalized company/title/location, optional external ID, and description fingerprint. Meaningful content changes become `UPDATED`.

## Environment reference

See `.env.example`. Secrets are never committed and the report generator receives job data through a temporary JSON file only.
