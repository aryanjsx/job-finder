import json
from pathlib import Path


def load_fixture() -> list[dict]:
    p = Path(__file__).resolve().parent / 'report_rows.json'
    with open(p, 'r', encoding='utf-8') as f:
        return json.load(f)
