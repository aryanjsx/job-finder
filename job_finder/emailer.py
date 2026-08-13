from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage
from pathlib import Path


def send_report(settings, report: Path, rows: list[dict]) -> bool:
    pipeline_rows = [
        row for row in rows
        if row.get("recommendation") != "DO NOT INCLUDE"
    ]
    if not pipeline_rows:
        logging.error("Pipeline is empty; refusing to email an empty workbook.")
        return False
    if not settings.email_enabled:
        return False

    required = (
        settings.smtp_host,
        settings.smtp_username,
        settings.smtp_password,
        settings.email_from,
        settings.email_to,
    )

    if not all(required):
        raise ValueError("SMTP settings are incomplete while EMAIL_ENABLED=true.")

    new = [row for row in pipeline_rows if row.get("status") in ("NEW", "UPDATED")]
    carried_over = [row for row in pipeline_rows if row.get("status") not in ("NEW", "UPDATED")]

    immediate = [
        r for r in pipeline_rows
        if (r.get("match_score") or 0) >= 85
    ]

    best = max(pipeline_rows, key=lambda row: row.get("match_score") or 0, default=None)

    if best:
        best_job = f"{best.get('title', 'Unknown')} at {best.get('company', 'Unknown')}"
    else:
        best_job = "None"

    salaries = [
        r.get("salary")
        for r in pipeline_rows
        if r.get("salary")
        and r.get("salary") != "Not disclosed"
    ]

    highest_salary = salaries[0] if salaries else "Not disclosed"

    recommended_count = sum(
        r.get("recommendation") in ("APPLY", "APPLY IMMEDIATELY")
        for r in pipeline_rows
    )

    cloud_devops_count = sum(
        r.get("cloud_devops_match") == "High"
        for r in pipeline_rows
    )

    body = (
        f"Pipeline matches: {len(pipeline_rows)}\n"
        f"New matches: {len(new)}\n"
        f"Carried-over matches: {len(carried_over)}\n"
        f"85+ matches: {len(immediate)}\n"
        f"Recommended to apply: {recommended_count}\n"
        f"Best job: {best_job}\n"
        f"Highest salary: {highest_salary}\n"
        f"Cloud/DevOps opportunities: {cloud_devops_count}\n"
    )

    msg = EmailMessage()
    msg["Subject"] = (
        f"Daily Job Finder - {report.stem[-10:]} - "
        f"{len(pipeline_rows)} matches ({len(new)} new)"
    )
    msg["From"] = settings.email_from
    msg["To"] = settings.email_to
    msg.set_content(body)

    msg.add_attachment(
        report.read_bytes(),
        maintype="application",
        subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=report.name,
    )

    with smtplib.SMTP(
        settings.smtp_host,
        settings.smtp_port,
        timeout=30,
    ) as server:
        if settings.smtp_use_tls:
            server.starttls()

        server.login(
            settings.smtp_username,
            settings.smtp_password,
        )

        server.send_message(msg)

    return True