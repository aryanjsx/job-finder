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
    def __init__(self, connection_string_or_path: str | Path):
        if isinstance(connection_string_or_path, str) and (connection_string_or_path.startswith('postgresql://') or connection_string_or_path.startswith('postgres://')):
            self.is_postgres = True
            import psycopg2
            import psycopg2.extras
            import urllib.parse
            
            parsed = urllib.parse.urlparse(connection_string_or_path)
            dbname = parsed.path[1:] if parsed.path else 'postgres'
            self.connection = psycopg2.connect(
                user=parsed.username,
                password=urllib.parse.unquote(parsed.password) if parsed.password else None,
                host=parsed.hostname,
                port=parsed.port,
                database=dbname
            )
            self.cursor = self.connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            
            # Create postgres-compatible table and indexes
            PG_SCHEMA = '''
            CREATE TABLE IF NOT EXISTS jobs (
                job_id VARCHAR(24) PRIMARY KEY, company VARCHAR(255) NOT NULL, title VARCHAR(255) NOT NULL, location VARCHAR(255), work_mode VARCHAR(50),
                salary VARCHAR(255), experience VARCHAR(255), posting_date VARCHAR(50), source VARCHAR(255), original_url TEXT, application_url TEXT,
                description_hash VARCHAR(64), match_score INTEGER, recommendation VARCHAR(50), first_seen VARCHAR(50), last_seen VARCHAR(50),
                status VARCHAR(50), external_job_id VARCHAR(255), original_url_verified BOOLEAN NOT NULL DEFAULT FALSE, company_type VARCHAR(255),
                primary_skills TEXT, matching_skills TEXT, skill_gaps TEXT, cloud_devops_match VARCHAR(50), why_it_matches TEXT,
                potential_concerns TEXT, freshness VARCHAR(100), eligibility_status VARCHAR(50), seniority VARCHAR(50),
                location_verified BOOLEAN DEFAULT FALSE, experience_verified BOOLEAN DEFAULT FALSE, posting_date_verified BOOLEAN DEFAULT FALSE, confidence VARCHAR(50)
            );
            CREATE INDEX IF NOT EXISTS jobs_url_idx ON jobs(original_url);
            CREATE INDEX IF NOT EXISTS jobs_seen_idx ON jobs(first_seen);
            '''
            self.cursor.execute(PG_SCHEMA)
            self.connection.commit()
        else:
            self.is_postgres = False
            path = Path(connection_string_or_path)
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
        
        if self.is_postgres:
            self.cursor.execute('SELECT description_hash FROM jobs WHERE job_id=%s', (job_id,))
            existing = self.cursor.fetchone()
        else:
            existing = self.connection.execute('SELECT description_hash FROM jobs WHERE job_id=?', (job_id,)).fetchone()
            
        job.status = 'NEW' if existing is None else ('UPDATED' if existing['description_hash'] != digest else 'SEEN')
        
        columns = 'job_id,company,title,location,work_mode,salary,experience,posting_date,source,original_url,application_url,description_hash,match_score,recommendation,first_seen,last_seen,status,external_job_id,original_url_verified,company_type,primary_skills,matching_skills,skill_gaps,cloud_devops_match,why_it_matches,potential_concerns,freshness,eligibility_status,seniority,location_verified,experience_verified,posting_date_verified,confidence'
        
        if self.is_postgres:
            original_url_verified = bool(job.original_url_verified)
            location_verified = bool(job.location_verified)
            experience_verified = bool(job.experience_verified)
            posting_date_verified = bool(job.posting_date_verified)
        else:
            original_url_verified = int(job.original_url_verified)
            location_verified = int(job.location_verified)
            experience_verified = int(job.experience_verified)
            posting_date_verified = int(job.posting_date_verified)
            
        values = (job_id, job.company, job.title, job.location, job.work_mode, job.salary, job.experience, job.posting_date, job.source, job.original_url, job.application_url, digest, job.match_score, job.recommendation, now, now, job.status, job.external_job_id, original_url_verified, job.company_type, ', '.join(job.primary_skills), ', '.join(job.matching_skills), ', '.join(job.skill_gaps), job.cloud_devops_match, job.why_it_matches, job.potential_concerns, job.freshness, job.eligibility_status, job.seniority, location_verified, experience_verified, posting_date_verified, job.confidence)
        
        if self.is_postgres:
            placeholders = ','.join('%s' for _ in values)
            self.cursor.execute(f'''INSERT INTO jobs ({columns}) VALUES ({placeholders})
            ON CONFLICT(job_id) DO UPDATE SET location=excluded.location, work_mode=excluded.work_mode, salary=excluded.salary, experience=excluded.experience, posting_date=excluded.posting_date, source=excluded.source, application_url=excluded.application_url, description_hash=excluded.description_hash, match_score=excluded.match_score, recommendation=excluded.recommendation, last_seen=excluded.last_seen, status=excluded.status, original_url_verified=excluded.original_url_verified, company_type=excluded.company_type, primary_skills=excluded.primary_skills, matching_skills=excluded.matching_skills, skill_gaps=excluded.skill_gaps, cloud_devops_match=excluded.cloud_devops_match, why_it_matches=excluded.why_it_matches, potential_concerns=excluded.potential_concerns, freshness=excluded.freshness, eligibility_status=excluded.eligibility_status, seniority=excluded.seniority, location_verified=excluded.location_verified, experience_verified=excluded.experience_verified, posting_date_verified=excluded.posting_date_verified, confidence=excluded.confidence''', values)
            self.connection.commit()
        else:
            placeholders = ','.join('?' for _ in values)
            self.connection.execute(f'''INSERT INTO jobs ({columns}) VALUES ({placeholders})
            ON CONFLICT(job_id) DO UPDATE SET location=excluded.location, work_mode=excluded.work_mode, salary=excluded.salary, experience=excluded.experience, posting_date=excluded.posting_date, source=excluded.source, application_url=excluded.application_url, description_hash=excluded.description_hash, match_score=excluded.match_score, recommendation=excluded.recommendation, last_seen=excluded.last_seen, status=excluded.status, original_url_verified=excluded.original_url_verified, company_type=excluded.company_type, primary_skills=excluded.primary_skills, matching_skills=excluded.matching_skills, skill_gaps=excluded.skill_gaps, cloud_devops_match=excluded.cloud_devops_match, why_it_matches=excluded.why_it_matches, potential_concerns=excluded.potential_concerns, freshness=excluded.freshness, eligibility_status=excluded.eligibility_status, seniority=excluded.seniority, location_verified=excluded.location_verified, experience_verified=excluded.experience_verified, posting_date_verified=excluded.posting_date_verified, confidence=excluded.confidence''', values)
            self.connection.commit()
        return job

    def report_rows(self) -> list[dict]:
        if self.is_postgres:
            self.cursor.execute("SELECT * FROM jobs ORDER BY match_score DESC, posting_date DESC")
            return [dict(row) for row in self.cursor.fetchall()]
        else:
            return [dict(row) for row in self.connection.execute("SELECT * FROM jobs ORDER BY match_score DESC, posting_date DESC")]

    def close(self) -> None:
        if self.is_postgres:
            self.cursor.close()
        self.connection.close()
