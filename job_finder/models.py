from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Job:
    company: str
    title: str
    location: str = 'Unknown'
    work_mode: str = 'Unknown'
    salary: str = 'Not disclosed'
    experience: str = 'Unknown'
    posting_date: str = 'Unknown'
    source: str = 'Unknown'
    original_url: str = ''
    application_url: str = ''
    description: str = ''
    external_job_id: str = ''
    original_url_verified: bool = False
    company_type: str = 'Unknown'
    primary_skills: list[str] = field(default_factory=list)
    matching_skills: list[str] = field(default_factory=list)
    skill_gaps: list[str] = field(default_factory=list)
    cloud_devops_match: str = 'Low'
    why_it_matches: str = ''
    potential_concerns: str = ''
    match_score: int = 0
    recommendation: str = 'DO NOT INCLUDE'
    status: str = 'NEW'
    freshness: str = 'Unknown'
    eligibility_status: str = 'VERIFICATION REQUIRED'
    seniority: str = 'MID'
    location_verified: bool = False
    experience_verified: bool = False
    posting_date_verified: bool = False
    confidence: str = 'LOW'

    def report_dict(self) -> dict[str, Any]:
        data = asdict(self)
        for key in ('primary_skills', 'matching_skills', 'skill_gaps'):
            data[key] = ', '.join(data[key])
        return data
