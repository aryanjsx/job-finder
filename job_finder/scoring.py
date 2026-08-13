from __future__ import annotations

import re
from datetime import date, datetime, timezone

from .extractors import cloud_match, skill_gaps, terms
from .models import Job
from .profile import CLOUD_SKILLS, LOCATIONS, PREFERRED_COMPANY_TERMS, SKILLS, TARGET_ROLES


def _text(job: Job) -> str:
    return ' '.join((job.title, job.location, job.work_mode, job.experience, job.description)).lower()


def _terms(text: str, vocabulary: set[str]) -> list[str]:
    return terms(text, vocabulary)


def _years(experience: str) -> tuple[float | None, float | None]:
    """Handles '24 months' (-> 2.0) and '1.5 yrs' (-> 1.5, not (1, 5))."""
    if not experience or experience == 'Unknown':
        return None, None
    if 'month' in experience.lower():
        m = re.search(r'(\d+(?:\.\d+)?)', experience)
        v = round(float(m.group(1)) / 12, 2) if m else None
        return (v, v)
    numbers = [float(n) for n in re.findall(r'\d+(?:\.\d+)?', experience)]
    if not numbers:
        return None, None
    return (numbers[0], numbers[1] if len(numbers) > 1 else numbers[0])


INDIA_TOKENS = ('india', 'hyderabad', 'gurgaon', 'gurugram', 'noida', 'delhi', 'ncr',
                'kolkata', 'bengaluru', 'bangalore', 'pune', 'chennai', 'mumbai')
PREFERRED_CITIES = ('hyderabad', 'gurgaon', 'gurugram', 'noida', 'delhi', 'ncr', 'kolkata')


def location_points(job: Job) -> int:
    """India-eligible only. Bare 'Remote' is ambiguous and scores 0, not 10.
    Preferred city or India-remote = 10, elsewhere in India = 5, otherwise 0."""
    loc = (job.location or '').lower().strip()
    if not loc or loc == 'unknown':
        return 0
    if not any(t in loc for t in INDIA_TOKENS):
        return 0
    if any(c in loc for c in PREFERRED_CITIES):
        return 10
    if 'remote' in loc:
        return 10
    return 5


def freshness(posting_date: str) -> tuple[str, int]:
    if not posting_date or posting_date == 'Unknown':
        return 'Unknown', 0
    try:
        posted = datetime.fromisoformat(posting_date.replace('Z', '+00:00')).date()
    except ValueError:
        return 'Unknown', 0
    days = (date.today() - posted).days
    if days < 0 or days <= 0: return '0–6 hours', 5
    if days <= 1: return '6–24 hours', 5
    if days <= 3: return '1–3 days', 4
    if days <= 7: return '3–7 days', 3
    if days <= 14: return '7–14 days', 1
    return 'Older than 14 days', 0


EXCLUDED_ROLE_TERMS = ('bpo', 'call center', 'customer support', 'technical support',
                       'support engineer', 'manual test', 'manual testing', 'qa',
                       'data entry', 'sales', 'account executive', 'intern',
                       'internship', 'apprentice', 'graduate trainee', 'recruiter',
                       'content writer')


def is_excluded(job: Job) -> bool:
    """Title only, word-boundary. A JD that merely mentions sales is not a sales job."""
    return bool(terms(job.title or '', EXCLUDED_ROLE_TERMS))


BOARD_API_MARKER = 'board API'


def is_stale(job: Job) -> bool:
    """Board feeds only list open postings, so createdAt age never disqualifies.
    Freshness remains a scoring signal for every source."""
    if BOARD_API_MARKER in (job.source or ''):
        return False
    return job.freshness == 'Older than 14 days'

def classify_seniority(title: str) -> str:
    text = title.lower()
    for token, level in (('senior staff','STAFF'),('staff','STAFF'),('principal','PRINCIPAL'),('lead','LEAD'),('manager','MANAGER'),('director','DIRECTOR'),('architect','PRINCIPAL'),('junior','JUNIOR'),('entry','ENTRY'),('senior','SENIOR')):
        if token in text: return level
    return 'MID'


def score(job: Job) -> Job:
    text = _text(job)
    job.seniority = classify_seniority(job.title)
    corrupted = job.company.strip().lower() == job.title.strip().lower() or job.location.strip().lower() in {job.title.strip().lower(), job.company.strip().lower()}
    job.location_verified = job.location not in {'Unknown', 'Remote - India eligibility unknown'} and not corrupted
    job.experience_verified = job.experience != 'Unknown'
    job.posting_date_verified = job.posting_date != 'Unknown'
    matched = _terms(text, SKILLS)
    cloud = _terms(text, CLOUD_SKILLS)
    job.primary_skills = sorted(set(matched + cloud))
    job.matching_skills = matched
    job.skill_gaps = skill_gaps(text, SKILLS)
    technical = min(30, round(30 * len(matched) / 8))
    role = 20 if any(role in job.title.lower() for role in TARGET_ROLES) else 0
    low, high = _years(job.experience)
    experience = 15 if low is None or (low <= 5 and (high is None or high >= 2)) else 0
    location = location_points(job)
    job.cloud_devops_match, cloud_points, _core = cloud_match(text)
    company = 5 if any(term in (job.company + ' ' + job.description).lower() for term in PREFERRED_COMPANY_TERMS) else 2
    salary = 5 if any(marker in job.salary.lower() for marker in ('10', '12', '15', 'lpa', 'lakh')) and job.salary != 'Not disclosed' else 0
    job.freshness, fresh_points = freshness(job.posting_date)
    job.match_score = technical + role + experience + location + cloud_points + company + salary + fresh_points
    too_senior = job.seniority in {'STAFF', 'PRINCIPAL', 'LEAD', 'MANAGER', 'DIRECTOR'}
    outside_location = job.location_verified and location == 0
    if is_excluded(job) or too_senior or outside_location or is_stale(job):
        job.recommendation = 'DO NOT INCLUDE'
    elif job.match_score >= 85:
        job.recommendation = 'APPLY IMMEDIATELY'
    elif job.match_score >= 70:
        job.recommendation = 'APPLY'
    elif job.match_score >= 60:
        job.recommendation = 'CONSIDER / STRETCH'
    else:
        job.recommendation = 'DO NOT INCLUDE'
    if not job.location_verified: job.match_score = min(job.match_score, 79)
    if not job.experience_verified: job.match_score = min(job.match_score, 79)
    if not job.location_verified and not job.experience_verified: job.match_score = min(job.match_score, 69)
    evidence = [f"{skill} matches your profile" for skill in matched[:5]]
    if job.experience_verified: evidence.insert(0, f"experience requirement: {job.experience}")
    if job.location_verified: evidence.append(f"{job.location} matches a preferred location")
    job.why_it_matches = '✓ ' + '\n✓ '.join(evidence or ['limited verified technical evidence'])
    concerns = []
    if job.location == 'Unknown': concerns.append('Location not stated')
    if job.posting_date == 'Unknown': concerns.append('Posting date unavailable')
    if not job.original_url_verified: concerns.append('Original company URL unverified')
    if not job.location_verified: concerns.append('Location verification required')
    if not job.experience_verified: concerns.append('Experience verification required')
    if too_senior: concerns.append(f'{job.seniority.title()} title exceeds target seniority')
    if corrupted: concerns.append('Critical field extraction corrupted')
    job.potential_concerns = '; '.join(concerns) or 'None observed'
    job.eligibility_status = 'REJECTED' if job.recommendation == 'DO NOT INCLUDE' else ('ELIGIBLE' if job.location_verified and job.experience_verified and job.original_url_verified else 'VERIFICATION REQUIRED')
    job.confidence = 'HIGH' if job.eligibility_status == 'ELIGIBLE' and job.posting_date_verified else ('MEDIUM' if job.original_url_verified and job.location_verified and job.experience_verified else 'LOW')
    if job.recommendation != 'DO NOT INCLUDE':
        if job.confidence == 'HIGH' and job.match_score >= 85 and not corrupted:
            job.recommendation = 'APPLY IMMEDIATELY'
        elif job.confidence == 'MEDIUM' and job.match_score >= 70:
            job.recommendation = 'APPLY'
        elif job.match_score >= 60:
            job.recommendation = 'CONSIDER / STRETCH'
        else:
            job.recommendation = 'DO NOT INCLUDE'
    return job
