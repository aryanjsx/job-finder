"""Corrected field extraction. Replaces inline logic in firecrawl.py / scoring.py.

Each function fixes a bug reproduced against the live codebase:
  extract_experience   - the old regex turned "7+ years" into "7-7 years"
  derive_company_title - the Lever slug was computed then overwritten
  normalize_location   - marketing copy was accepted as a location
  terms                - substring matching made "java" match "javascript"
  cloud_match          - three substring hits saturated the scale at "High"
  skill_gaps           - was a hard-coded {docker, kubernetes, terraform}
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

# --------------------------------------------------------------- experience
_EXP = [
    ("range",   re.compile(r"(\d+(?:\.\d+)?)\s*(?:-|–|—|to)\s*(\d+(?:\.\d+)?)\s*\+?\s*(?:years?|yrs?)", re.I)),
    ("plus",    re.compile(r"(\d+(?:\.\d+)?)\s*\+\s*(?:years?|yrs?)", re.I)),
    ("minimum", re.compile(r"(?:minimum|min\.?|at ?least|atleast)\s*(?:of\s*)?(\d+(?:\.\d+)?)\s*(?:years?|yrs?)", re.I)),
    ("months",  re.compile(r"(\d+)\s*months?\s*(?:of\s*)?experience", re.I)),
    ("fresher", re.compile(r"\b(?:fresher|fresh graduate|no prior experience)\b", re.I)),
    ("exact",   re.compile(r"(\d+(?:\.\d+)?)\s*(?:years?|yrs?)\s*(?:of\s*)?(?:relevant\s*)?experience", re.I)),
]


def extract_experience(markdown: str) -> str:
    """Never fabricates a range. '7+' stays '7+ yrs'; only a true range gets a dash."""
    hits = [(n, m) for n, rx in _EXP for m in rx.finditer(markdown or "")]
    if not hits:
        return "Unknown"
    order = {n: i for i, (n, _) in enumerate(_EXP)}
    name, m = min(hits, key=lambda h: (h[1].start(), order[h[0]]))
    f = lambda v: str(int(float(v))) if float(v).is_integer() else str(float(v))
    if name == "range":
        lo, hi = float(m.group(1)), float(m.group(2))
        if hi < lo:
            lo, hi = hi, lo
        return f"{f(lo)}-{f(hi)} yrs"
    if name in ("plus", "minimum"):
        return f"{f(m.group(1))}+ yrs"
    if name == "months":
        return f"{m.group(1)} months"
    if name == "fresher":
        return "0-1 yrs"
    return f"{f(m.group(1))} yrs"


# ----------------------------------------------------------- company / title
ATS_SLUG_HOSTS = {"jobs.lever.co", "boards.greenhouse.io", "jobs.ashbyhq.com"}


def derive_company_title(url: str, meta_title: str):
    """The ATS slug is authoritative. Only fall back to splitting the page title."""
    title = meta_title or ""
    parsed = urlparse(url or "")
    parts = parsed.path.strip("/").split("/")
    company = parts[0] if parsed.netloc in ATS_SLUG_HOSTS and parts and parts[0] else ""
    if not company and " - " in title:
        company, title = title.split(" - ", 1)
    elif company and " - " in title:
        head, tail = title.split(" - ", 1)
        if head.lower().replace(" ", "") == company.lower().replace("-", "").replace(" ", ""):
            title = tail
    if not company or not title:
        return None, None
    return company.replace("-", " ").title(), title


# ------------------------------------------------------------------ location
LOCATION_TERMS = ("hyderabad", "gurgaon", "gurugram", "noida", "delhi ncr", "delhi",
                  "kolkata", "bengaluru", "bangalore", "pune", "chennai", "mumbai",
                  "india", "remote")
_PROSE = re.compile(r"(join |be among|hiring|apply |click|refreshed|daily|·|\||\]\(|http|"
                    r"jobs? in |we're|we are|first hires|updated)", re.I)


def normalize_location(value: str, title: str, company: str):
    clean = re.sub(r"\s+", " ", (value or "").strip(" #*-"))
    lowered = clean.lower()
    if not clean or lowered in {(title or "").lower().strip(), (company or "").lower().strip()}:
        return "Unknown", False
    if len(clean) > 60 or _PROSE.search(clean):
        return "Unknown", False
    if len(clean.split()) > 6:
        return "Unknown", False
    if not any(t in lowered for t in LOCATION_TERMS):
        return "Unknown", False
    if "remote" in lowered:
        return ("Remote - India" if "india" in lowered else "Remote - India eligibility unknown"), True
    for city in ("Hyderabad", "Gurgaon", "Gurugram", "Noida", "Delhi NCR", "Delhi",
                 "Kolkata", "Bengaluru", "Bangalore", "Pune", "Chennai", "Mumbai"):
        if city.lower() in lowered:
            return city + (", India" if "india" in lowered and city != "Delhi NCR" else ""), True
    return ("India" if lowered in {"india", "india - remote"} else clean), True


# ------------------------------------------------------------------- scoring
def terms(text: str, vocabulary):
    """Word-boundary matching. The trailing (?!\.[a-z0-9]) stops bare 'node'
    matching inside 'node.js' and bare 'java' inside 'javascript'."""
    found = []
    for term in vocabulary:
        if re.search(r"(?<![a-z0-9])" + re.escape(term) + r"(?![a-z0-9]|\.[a-z0-9])", text or "", re.I):
            found.append(term)
    return sorted(found)


CORE_CLOUD = {"kubernetes", "docker", "terraform", "ci/cd", "devops", "sre",
              "aws", "azure", "gcp", "cloud-native"}
WEAK_CLOUD = {"cloud", "platform", "infrastructure", "automation", "reliability"}


def cloud_match(text: str):
    """Returns (label, points, core_hits). Core tools weigh 2x, soft words 1x."""
    core = terms(text, CORE_CLOUD)
    weak = terms(text, WEAK_CLOUD)
    pts = min(10, 2 * len(core) + len(weak))
    return ("High" if pts >= 8 else "Medium" if pts >= 4 else "Low"), pts, core


def skill_gaps(job_text: str, my_skills):
    """Gaps derived from THIS job, not a hard-coded triple."""
    required = terms(job_text, CORE_CLOUD | WEAK_CLOUD |
                     {"java", "python", "react", "node.js", "postgresql", "mysql", "mongodb"})
    return sorted(set(required) - {s.lower() for s in my_skills})[:5]
