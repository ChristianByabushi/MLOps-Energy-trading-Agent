"""
set_alert_email.py — set the alert recipient email and send a test message.

Usage:
    python set_alert_email.py your@email.com

What it does:
  1. Updates ALERT_EMAIL_TO in .env
  2. Sends a test email immediately to confirm delivery works
  3. Prints the result

After running this, all agent ALERT decisions will email that address.
To change it before a demo, just run the script again with a new address.
"""

from __future__ import annotations

import re
import smtplib
import sys
from datetime import datetime
from email.mime.text import MIMEText
from pathlib import Path

from dotenv import dotenv_values, load_dotenv

ENV_FILE = Path(".env")


def update_env(key: str, value: str) -> None:
    """Update a single key in .env without touching other lines."""
    content = ENV_FILE.read_text(encoding="utf-8")
    pattern = rf"^{re.escape(key)}=.*$"
    new_line = f"{key}={value}"

    if re.search(pattern, content, flags=re.MULTILINE):
        content = re.sub(pattern, new_line, content, flags=re.MULTILINE)
    else:
        content = content.rstrip("\n") + f"\n{new_line}\n"

    ENV_FILE.write_text(content, encoding="utf-8")


def send_test_email(to: str, smtp_host: str, smtp_port: int,
                    smtp_user: str, smtp_password: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    subject = "⚡ Energy Trading Agent — Alert Email Confirmed"
    body = (
        f"This is a test message from the MLOps Energy Trading Agent.\n\n"
        f"Your email address has been set as the alert recipient.\n"
        f"You will receive a message like this whenever the electricity\n"
        f"spot price drops below the configured threshold.\n\n"
        f"Sent at: {ts}\n"
        f"Recipient: {to}\n"
        f"SMTP server: {smtp_host}:{smtp_port}\n"
    )

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"]    = smtp_user
    msg["To"]      = to

    if smtp_port == 465:
        with smtplib.SMTP_SSL(smtp_host, smtp_port) as server:
            server.login(smtp_user, smtp_password)
            server.sendmail(smtp_user, [to], msg.as_string())
    else:
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            server.login(smtp_user, smtp_password)
            server.sendmail(smtp_user, [to], msg.as_string())


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python set_alert_email.py your@email.com")
        sys.exit(1)

    recipient = sys.argv[1].strip()

    # Basic email format check
    if "@" not in recipient or "." not in recipient.split("@")[-1]:
        print(f"❌ '{recipient}' does not look like a valid email address.")
        sys.exit(1)

    # Load current .env values
    load_dotenv(override=True)
    cfg = dotenv_values(ENV_FILE)

    smtp_host     = cfg.get("SMTP_HOST", "")
    smtp_port     = int(cfg.get("SMTP_PORT", "587"))
    smtp_user     = cfg.get("SMTP_USER", "")
    smtp_password = cfg.get("SMTP_PASSWORD", "")

    if not smtp_host or not smtp_user or not smtp_password:
        print("❌ SMTP is not fully configured in .env")
        print("   Make sure SMTP_HOST, SMTP_USER, and SMTP_PASSWORD are set.")
        sys.exit(1)

    # 1. Update .env
    update_env("ALERT_EMAIL_TO", recipient)
    print(f"\n✅ ALERT_EMAIL_TO set to: {recipient}")
    print(f"   (updated in .env)\n")

    # 2. Send test email
    print(f"📧 Sending test email via {smtp_host}:{smtp_port} ...")
    try:
        send_test_email(recipient, smtp_host, smtp_port, smtp_user, smtp_password)
        print(f"✅ Test email sent successfully to {recipient}")
        print(f"\n   Check your inbox — subject: '⚡ Energy Trading Agent — Alert Email Confirmed'")
        print(f"\n   The agent will now email {recipient} on every ALERT decision.")
        print(f"   To change it: python set_alert_email.py other@email.com\n")
    except Exception as exc:
        print(f"❌ Failed to send test email: {exc}")
        print(f"\n   The ALERT_EMAIL_TO was still updated in .env.")
        print(f"   Fix the SMTP error above and try again.\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
