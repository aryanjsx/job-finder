from __future__ import annotations

import smtplib
from email.message import EmailMessage
from pathlib import Path


def send_report(settings, report: Path, rows: list[dict]) -> bool:
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

    new = [
        r
        for r in rows
        if r.get("status") in ("NEW", "UPDATED")
        and r.get("recommendation") != "DO NOT INCLUDE"
    ]

    immediate = [
        r for r in new
        if (r.get("match_score") or 0) >= 85
    ]

    best = new[0] if new else None

    if best:
        best_job = f"{best.get('title', 'Unknown')} at {best.get('company', 'Unknown')}"
    else:
        best_job = "None"

    salaries = [
        r.get("salary")
        for r in new
        if r.get("salary")
        and r.get("salary") != "Not disclosed"
    ]

    highest_salary = salaries[0] if salaries else "Not disclosed"

    recommended_count = sum(
        r.get("recommendation") in ("APPLY", "APPLY IMMEDIATELY")
        for r in new
    )

    cloud_devops_count = sum(
        r.get("cloud_devops_match") == "High"
        for r in new
    )

    body = (
        f"New matches: {len(new)}\n"
        f"85+ matches: {len(immediate)}\n"
        f"Recommended to apply: {recommended_count}\n"
        f"Best job: {best_job}\n"
        f"Highest salary: {highest_salary}\n"
        f"Cloud/DevOps opportunities: {cloud_devops_count}\n"
    )

    msg = EmailMessage()
    msg["Subject"] = (
        f"Daily Job Finder - {report.stem[-10:]} - "
        f"{len(new)} New Matches"
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