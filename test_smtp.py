"""Quick SMTP test — runs the full AlertService.send_email() path."""
import logging, os
from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")

from agent.alert import AlertService
from agent.models import AlertMessage, MarketSnapshot
from datetime import datetime, timezone

snapshot = MarketSnapshot(
    timestamp=datetime.now(tz=timezone.utc),
    spot_price_eur_mwh=28.00,
    demand_mw=47000.0,
    wind_production_mw=29000.0,
)
msg = AlertMessage(
    subject="⚡ Test Alert — Energy Trading Agent",
    body=(
        "Price = 28.00 EUR/MWh — below threshold of 50.00 EUR/MWh\n"
        "Demand: 47,000 MW  |  Wind: 29,000 MW\n\n"
        "This confirms the alert email pipeline is working."
    ),
    snapshot=snapshot,
    threshold=50.0,
    channel="email",
)

recipient = os.environ.get("ALERT_EMAIL_TO", "")
print(f"Sending alert email to: {recipient}")

svc = AlertService(
    smtp_host=os.environ.get("SMTP_HOST", ""),
    smtp_port=int(os.environ.get("SMTP_PORT", "465")),
    smtp_user=os.environ.get("SMTP_USER", ""),
    smtp_password=os.environ.get("SMTP_PASSWORD", ""),
    alert_email_to=recipient,
)

svc.send_email(msg)
print("Done — check your inbox.")
