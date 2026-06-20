import os
import smtplib
from email.message import EmailMessage
from pathlib import Path


REQUIRED = ["SMTP_SERVER", "SMTP_USERNAME", "SMTP_PASSWORD", "EMAIL_TO"]


def configured() -> bool:
    missing = [name for name in REQUIRED if not os.getenv(name)]
    if missing:
        print(f"Email notification skipped. Missing secrets/env: {', '.join(missing)}")
        return False
    return True


def attach_file(message: EmailMessage, path: Path) -> None:
    if not path.exists() or not path.is_file():
        return
    message.add_attachment(
        path.read_bytes(),
        maintype="application",
        subtype="octet-stream",
        filename=path.name,
    )


def main() -> None:
    if not configured():
        return

    reports_dir = Path(os.getenv("REPORTS_DIR", "reports"))
    markdown_report = reports_dir / "hourly-auto-trading-report.md"
    json_report = reports_dir / "hourly-auto-trading-report.json"
    dashboard_json = reports_dir / "dashboard-data.json"

    body = markdown_report.read_text(encoding="utf-8") if markdown_report.exists() else "ไม่มีไฟล์รายงาน Markdown"
    run_url = os.getenv("GITHUB_RUN_URL")
    if run_url:
        body = f"GitHub Actions Run: {run_url}\n\n" + body

    msg = EmailMessage()
    msg["Subject"] = os.getenv("EMAIL_SUBJECT", "รายงานระบบเทรดอัตโนมัติจาก GitHub Actions")
    msg["From"] = os.getenv("EMAIL_FROM") or os.getenv("SMTP_USERNAME")
    msg["To"] = os.getenv("EMAIL_TO")
    if os.getenv("EMAIL_CC"):
        msg["Cc"] = os.getenv("EMAIL_CC")
    msg.set_content(body)

    attach_file(msg, markdown_report)
    attach_file(msg, json_report)
    attach_file(msg, dashboard_json)

    server = os.getenv("SMTP_SERVER")
    port = int(os.getenv("SMTP_PORT", "587"))
    use_ssl = os.getenv("SMTP_USE_SSL", "false").lower() == "true"

    recipients = [addr.strip() for addr in msg["To"].split(",") if addr.strip()]
    if msg.get("Cc"):
        recipients.extend(addr.strip() for addr in msg["Cc"].split(",") if addr.strip())

    if use_ssl:
        with smtplib.SMTP_SSL(server, port, timeout=30) as smtp:
            smtp.login(os.getenv("SMTP_USERNAME"), os.getenv("SMTP_PASSWORD"))
            smtp.send_message(msg, to_addrs=recipients)
    else:
        with smtplib.SMTP(server, port, timeout=30) as smtp:
            smtp.starttls()
            smtp.login(os.getenv("SMTP_USERNAME"), os.getenv("SMTP_PASSWORD"))
            smtp.send_message(msg, to_addrs=recipients)

    print(f"Email notification sent to {msg['To']}")


if __name__ == "__main__":
    main()
