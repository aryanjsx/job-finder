from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .models import Job

SCHEMA = '''
CREATE TABLE IF NOT EXISTS jobs (
 job_id TEXT PRIMARY KEY, company TEXT NOT NULL, title TEXT NOT NULL, location TEXT, work_mode TEXT,
 salary TEXT, experience TEXT, posting_date TEXT, source TEXT, original_url TEXT, application_url TEXT,
 description_hash TEXT, match_score INTEGER, recommendation TEXT, first_seen TEXT, last_seen TEXT,
 status TEXT, external_job_id TEXT, original_url_verified INTEGER NOT NULL DEFAULT 0, company_type TEXT,
 primary_skills TEXT, matching_skills TEXT, skill_gaps TEXT, cloud_devops_match TEXT, why_it_matches TEXT,
 potential_concerns TEXT, freshness TEXT
 ,eligibility_status TEXT, seniority TEXT, location_verified INTEGER, experience_verified INTEGER, posting_date_verified INTEGER, confidence TEXT
);
CREATE INDEX IF NOT EXISTS jobs_url_idx ON jobs(original_url);
CREATE INDEX IF NOT EXISTS jobs_seen_idx ON jobs(first_seen);
'''


def _hash(text: str) -> str:
    return hashlib.sha256((text or '').strip().lower().encode()).hexdigest()


def identity(job: Job) -> str:
    material = '|'.join([job.original_url.lower(), job.company.lower().strip(), job.title.lower().strip(), job.external_job_id.lower()])
    return hashlib.sha256(material.encode()).hexdigest()[:24]


class JobStore:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(SCHEMA)
        for column, definition in [('eligibility_status','TEXT'),('seniority','TEXT'),('location_verified','INTEGER'),('experience_verified','INTEGER'),('posting_date_verified','INTEGER'),('confidence','TEXT')]:
            try: self.connection.execute(f'ALTER TABLE jobs ADD COLUMN {column} {definition}')
            except sqlite3.OperationalError: pass
        self.connection.commit()

    def upsert(self, job: Job) -> Job:
        job_id, now, digest = identity(job), datetime.now(timezone.utc).isoformat(), _hash(job.description)
        existing = self.connection.execute('SELECT description_hash FROM jobs WHERE job_id=?', (job_id,)).fetchone()
        job.status = 'NEW' if existing is None else ('UPDATED' if existing['description_hash'] != digest else 'SEEN')
        columns = 'job_id,company,title,location,work_mode,salary,experience,posting_date,source,original_url,application_url,description_hash,match_score,recommendation,first_seen,last_seen,status,external_job_id,original_url_verified,company_type,primary_skills,matching_skills,skill_gaps,cloud_devops_match,why_it_matches,potential_concerns,freshness,eligibility_status,seniority,location_verified,experience_verified,posting_date_verified,confidence'
        values = (job_id, job.company, job.title, job.location, job.work_mode, job.salary, job.experience, job.posting_date, job.source, job.original_url, job.application_url, digest, job.match_score, job.recommendation, now, now, job.status, job.external_job_id, int(job.original_url_verified), job.company_type, ', '.join(job.primary_skills), ', '.join(job.matching_skills), ', '.join(job.skill_gaps), job.cloud_devops_match, job.why_it_matches, job.potential_concerns, job.freshness, job.eligibility_status, job.seniority, int(job.location_verified), int(job.experience_verified), int(job.posting_date_verified), job.confidence)
        self.connection.execute(f'''INSERT INTO jobs ({columns}) VALUES ({','.join('?' for _ in values)})
        ON CONFLICT(job_id) DO UPDATE SET location=excluded.location, work_mode=excluded.work_mode, salary=excluded.salary, experience=excluded.experience, posting_date=excluded.posting_date, source=excluded.source, application_url=excluded.application_url, description_hash=excluded.description_hash, match_score=excluded.match_score, recommendation=excluded.recommendation, last_seen=excluded.last_seen, status=excluded.status, original_url_verified=excluded.original_url_verified, company_type=excluded.company_type, primary_skills=excluded.primary_skills, matching_skills=excluded.matching_skills, skill_gaps=excluded.skill_gaps, cloud_devops_match=excluded.cloud_devops_match, why_it_matches=excluded.why_it_matches, potential_concerns=excluded.potential_concerns, freshness=excluded.freshness, eligibility_status=excluded.eligibility_status, seniority=excluded.seniority, location_verified=excluded.location_verified, experience_verified=excluded.experience_verified, posting_date_verified=excluded.posting_date_verified, confidence=excluded.confidence''', values)
        self.connection.commit()
        return job

    def report_rows(self) -> list[dict]:
        return [dict(row) for row in self.connection.execute("SELECT * FROM jobs ORDER BY match_score DESC, posting_date DESC")]

    def close(self) -> None:
        self.connection.close()
