from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def load_dotenv(path: Path = Path('.env')) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@dataclass(frozen=True)
class Settings:
    firecrawl_api_key: str
    firecrawl_base_url: str
    database_path: Path
    report_dir: Path
    email_enabled: bool
    smtp_host: str
    smtp_port: int
    smtp_username: str
    smtp_password: str
    email_from: str
    email_to: str
    smtp_use_tls: bool
    firecrawl_request_delay_seconds: float
    firecrawl_max_concurrency: int

    @classmethod
    def from_env(cls) -> 'Settings':
        load_dotenv()
        truthy = lambda value: value.lower() in {'1', 'true', 'yes', 'on'}
        return cls(
            firecrawl_api_key=os.getenv('FIRECRAWL_API_KEY', ''),
            firecrawl_base_url=os.getenv('FIRECRAWL_BASE_URL', 'https://api.firecrawl.dev').rstrip('/'),
            database_path=Path(os.getenv('DATABASE_PATH', 'data/job_finder.db')),
            report_dir=Path(os.getenv('REPORT_DIR', 'reports')),
            email_enabled=truthy(os.getenv('EMAIL_ENABLED', 'false')),
            smtp_host=os.getenv('SMTP_HOST', ''), smtp_port=int(os.getenv('SMTP_PORT', '587')),
            smtp_username=os.getenv('SMTP_USERNAME', ''), smtp_password=os.getenv('SMTP_PASSWORD', ''),
            email_from=os.getenv('EMAIL_FROM', ''), email_to=os.getenv('EMAIL_TO', ''),
            smtp_use_tls=truthy(os.getenv('SMTP_USE_TLS', 'true')),
            firecrawl_request_delay_seconds=float(os.getenv('FIRECRAWL_REQUEST_DELAY_SECONDS', '1.25')),
            firecrawl_max_concurrency=int(os.getenv('FIRECRAWL_MAX_CONCURRENCY', '2')),
        )
