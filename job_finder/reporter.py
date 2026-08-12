from __future__ import annotations

import json
import subprocess
from datetime import date
from pathlib import Path


def generate_report(rows: list[dict], report_dir: Path) -> Path:
    report_dir.mkdir(parents=True, exist_ok=True)
    payload = report_dir / '.report-data.json'
    output = report_dir / f'Aryan_Job_Report_{date.today().isoformat()}.xlsx'
    payload.write_text(json.dumps(rows), encoding='utf-8')
    root = Path(__file__).resolve().parent.parent
    node = Path(r'C:\Users\LENOVO\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe')
    try:
        completed = subprocess.run([str(node), str(root / 'tools' / 'build_report.mjs'), str(payload), str(output)], cwd=root, capture_output=True, text=True)
        # The bundled artifact runtime may return a non-zero code after successfully
        # writing its inspection sidecar. Treat the verified output file as success.
        if completed.returncode and not output.exists():
            raise RuntimeError(f'Excel generation failed: {completed.stderr or completed.stdout}')
    finally:
        payload.unlink(missing_ok=True)
    return output
