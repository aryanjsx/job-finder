# Automated Job Finder

An opinionated, privacy-conscious job discovery service that finds relevant job listings, scores them against a candidate profile, stores them in a database, and generates a daily Excel report.

It combines direct ATS board APIs with [Firecrawl](https://www.firecrawl.dev/) discovery and scraping. The system focuses on **observed job data**, avoids inventing missing information, and **never applies to jobs automatically**.

## What it does

```text
ATS boards ───────────────┐
                          ├─→ normalize → filter → deduplicate → score
Firecrawl discovery ──────┘                                      │
                                                                 ↓
                                                              Supabase
                                                                 │
                                                                 ↓
                                                           Excel report
                                                                 │
                                                          optional SMTP
```

### Key features

* Searches configured ATS job boards.
* Uses Firecrawl to discover additional job pages and scrape structured job information.
* Prioritizes original company/ATS URLs over unreliable aggregator pages.
* Filters listings for India-relevant opportunities by default.
* Scores jobs against the configured candidate profile.
* Deduplicates existing listings and detects meaningful updates.
* Persists job data in SQLite by default.
* Supports PostgreSQL through `DATABASE_URL`.
* Generates a daily Excel report.
* Optionally emails the report through SMTP.
* Maintains ATS board discovery data in `config/boards.json`.
* Keeps rejected listings as audit records instead of silently deleting them.
* Supports scheduled execution through GitHub Actions.
* Never submits job applications.

## Requirements

* Python **3.11+**
* A [Firecrawl](https://www.firecrawl.dev/) API key for discovery/scraping.
* Dependencies from `requirements.txt`.
* Optional PostgreSQL database if `DATABASE_URL` is configured.
* Optional SMTP credentials if email delivery is enabled.

Install dependencies with:

```bash
python -m pip install -r requirements.txt
```

## Quick start

### 1. Clone the repository

```bash
git clone https://github.com/aryanjsx/job-finder.git
cd job-finder
```

### 2. Configure environment variables

Copy the example configuration:

```bash
cp .env.example .env
```

Then set at least:

```env
FIRECRAWL_API_KEY=your-firecrawl-api-key
```

The application uses SQLite by default:

```env
DATABASE_PATH=data/job_finder.db
```

You can use PostgreSQL instead:

```env
DATABASE_URL=postgresql://user:password@host:5432/database
```

Email is disabled by default:

```env
EMAIL_ENABLED=false
```

See [Environment variables](#environment-variables) for the complete configuration.

### 3. Run a collection

```bash
python -m job_finder collect --limit 25
```

Collection searches the configured ATS boards and uses Firecrawl for additional discovery/scraping. It stores the resulting listings but **does not send email**.

### 4. Generate the report

```bash
python -m job_finder finalize
```

The report is written to:

```text
reports/Aryan_Job_Report_YYYY-MM-DD.xlsx
```

If `EMAIL_ENABLED=true`, the finalized report is also sent through the configured SMTP server.

## CLI commands

The application exposes four commands:

### Collect jobs

```bash
python -m job_finder collect --limit 25
```

Collect and score job listings.

To keep globally located ATS postings instead of restricting results to India-relevant roles:

```bash
python -m job_finder collect --limit 25 --all-locations
```

### Discover ATS boards

```bash
python -m job_finder discover-boards --limit 60
```

Uses Firecrawl discovery to find ATS board URLs, probes them, and keeps boards that contain relevant India postings.

New boards are stored in:

```text
config/boards.json
```

### Prune ATS boards

```bash
python -m job_finder prune-boards
```

Checks configured boards and disables boards that no longer contain India-relevant listings.

Boards are disabled rather than deleted so their history is preserved.

### Finalize the report

```bash
python -m job_finder finalize
```

Generates the Excel report and sends it by email when email delivery is enabled.

The command refuses to send a report when the pipeline is empty.

## Environment variables

The supported configuration is defined in `.env.example`.

| Variable                          | Default                     | Description                                                       |
| --------------------------------- | --------------------------- | ----------------------------------------------------------------- |
| `FIRECRAWL_API_KEY`               | —                           | Firecrawl API key. Required for discovery/scraping.               |
| `FIRECRAWL_BASE_URL`              | `https://api.firecrawl.dev` | Firecrawl API base URL.                                           |
| `FIRECRAWL_REQUEST_DELAY_SECONDS` | `1.25`                      | Delay between Firecrawl requests.                                 |
| `FIRECRAWL_MAX_CONCURRENCY`       | `2`                         | Maximum concurrent Firecrawl operations.                          |
| `DATABASE_PATH`                   | `data/job_finder.db`        | SQLite database path.                                             |
| `DATABASE_URL`                    | —                           | Optional PostgreSQL connection URL. Takes precedence over SQLite. |
| `REPORT_DIR`                      | `reports`                   | Directory for generated reports.                                  |
| `BOARDS_PATH`                     | `config/boards.json`        | ATS board configuration path.                                     |
| `EMAIL_ENABLED`                   | `false`                     | Enable report email delivery.                                     |
| `SMTP_HOST`                       | —                           | SMTP server hostname.                                             |
| `SMTP_PORT`                       | `587`                       | SMTP server port.                                                 |
| `SMTP_USERNAME`                   | —                           | SMTP username.                                                    |
| `SMTP_PASSWORD`                   | —                           | SMTP password/app password.                                       |
| `EMAIL_FROM`                      | —                           | Sender address.                                                   |
| `EMAIL_TO`                        | —                           | Report recipient.                                                 |
| `SMTP_USE_TLS`                    | `true`                      | Enable SMTP TLS.                                                  |

Keep `.env` out of version control. Secrets should only be provided through local environment configuration or GitHub Actions secrets.

## Data flow

Each collection run follows roughly this process:

1. Load configured ATS boards from `config/boards.json`.
2. Fetch available jobs from those boards.
3. Search for additional job pages using Firecrawl.
4. Normalize discovered listings using only information observed from the source.
5. Ignore or defer unreliable discovery URLs when a better original source is available.
6. Discover previously unknown ATS boards and add them to the board configuration.
7. Fetch newly discovered boards directly.
8. Filter and score listings against the candidate profile.
9. Upsert listings into the database.
10. Record run metrics for reporting and auditing.
11. Generate the final Excel report during the `finalize` step.

The collection pipeline is designed so that a Firecrawl failure does not discard successfully collected ATS listings.

## Job scoring

Listings are evaluated against the configured candidate profile and assigned a match score and recommendation.

The scoring pipeline also records rejection reasons and score distributions for each run.

Listings that should not enter the final matching pipeline are retained as rejected records for auditability rather than being silently removed.

## Data quality principles

The project intentionally favors conservative data handling:

* Missing salary information is reported as `Not disclosed`.
* Unknown dates remain `Unknown`.
* Application URLs are promoted only when they are directly observed or verified as company-career URLs.
* Unverified source URLs remain marked as unverified.
* Older or excluded listings can be retained as rejected audit records.
* Duplicate detection considers source URL, normalized company/title/location information, external IDs when available, and description fingerprints.
* Meaningful changes to an existing listing are recorded as `UPDATED`.
* Secrets are never intended to be stored in the repository.

## ATS board discovery

Configured boards live in:

```text
config/boards.json
```

The repository can automatically discover additional ATS boards:

```bash
python -m job_finder discover-boards --limit 60
```

The discovery process probes candidate boards and keeps boards that expose relevant listings.

Boards with no relevant listings can be disabled with:

```bash
python -m job_finder prune-boards
```

This means the board configuration can evolve over time without deleting historical board information.

## Reports

Reports are generated as `.xlsx` files in the configured report directory.

Default:

```text
reports/
└── Aryan_Job_Report_YYYY-MM-DD.xlsx
```

The report is generated by the `finalize` command after collection has populated the database.

## Automated runs with GitHub Actions

The repository includes a scheduled GitHub Actions workflow.

The current workflow runs three collection windows:

* **08:00 IST**
* **15:00 IST**
* **22:00 IST**

The final run also generates and emails the daily report. Manual workflow runs can finalize a report as well.

The workflow expects these GitHub Actions secrets:

```text
FIRECRAWL_API_KEY
DATABASE_URL
SMTP_USERNAME
SMTP_PASSWORD
EMAIL_FROM
EMAIL_TO
```

The workflow installs the dependencies, creates the `data` and `reports` directories, runs collection, and finalizes the report during the final scheduled run.

### GitHub Actions schedule

The current schedule is implemented in:

```text
.github/workflows/job-finder.yml
```

If you change the schedule, update this README so the documented times remain accurate.

## Automatic ATS discovery workflow

A separate GitHub Actions workflow is available for discovering new ATS boards:

```text
.github/workflows/discover.yml
```

It can be triggered manually with a configurable discovery limit.

When new boards are found, the workflow commits the updated `config/boards.json` back to the repository.

## Testing

Run the complete test suite with:

```bash
python -m unittest discover -s tests -v
```

The repository currently includes tests covering:

* ATS handling
* Collection
* Database behavior
* Email delivery
* Extraction/normalization
* Report generation
* Scoring

## Project structure

```text
job-finder/
├── .github/
│   └── workflows/
│       ├── discover.yml
│       └── job-finder.yml
├── config/
│   └── boards.json
├── job_finder/
│   ├── __init__.py
│   ├── __main__.py
│   ├── ats.py
│   ├── config.py
│   ├── database.py
│   ├── emailer.py
│   ├── extractors.py
│   ├── firecrawl.py
│   ├── models.py
│   ├── profile.py
│   ├── reporter.py
│   ├── scoring.py
│   └── service.py
├── reports/
├── tests/
│   ├── fixtures/
│   ├── test_ats.py
│   ├── test_collection.py
│   ├── test_database.py
│   ├── test_emailer.py
│   ├── test_extractors.py
│   ├── test_reporter.py
│   └── test_scoring.py
├── .env.example
├── .gitignore
├── README.md
└── requirements.txt
```

## Privacy and safety

This project is designed as a **job discovery and reporting tool**, not an auto-application bot.

It does not submit applications on behalf of the user.

When adding credentials:

* Never commit `.env`.
* Use GitHub Actions secrets for automated runs.
* Prefer SMTP app passwords or dedicated credentials instead of personal account passwords.
* Treat generated reports as potentially sensitive because they can contain job-search information.

## Current scope

The project intentionally focuses on:

* job discovery
* source verification
* normalization
* filtering
* matching/scoring
* persistence
* reporting
* optional email delivery

It does **not** automatically apply to jobs.

## License

Add the project's license here once a `LICENSE` file is included in the repository.
