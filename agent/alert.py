"""AlertService: sends Slack and Email notifications when price drops below threshold."""

from __future__ import annotations

import logging
import smtplib
import time
from email.mime.text import MIMEText

import httpx

from agent.models import AlertMessage, MarketSnapshot

logger = logging.getLogger(__name__)

_RETRY_WAIT = 2.0  # seconds to wait before retry


class AlertService:
    """Sends Slack webhook messages and/or Email notifications for price threshold breaches.

    All delivery failures are non-fatal: they are logged as warnings and execution continues.
    """

    def __init__(
        self,
        slack_webhook_url: str = "",
        smtp_host: str = "",
        smtp_port: int = 587,
        smtp_user: str = "",
        smtp_password: str = "",
        alert_email_to: str = "",
        http_client: httpx.Client | None = None,
    ) -> None:
        self.slack_webhook_url = slack_webhook_url
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.smtp_user = smtp_user
        self.smtp_password = smtp_password
        self.alert_email_to = alert_email_to
        self._http_client = http_client

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def should_alert(self, snapshot: MarketSnapshot, threshold: float) -> bool:
        """Return True if and only if the current spot price is strictly below the threshold.

        This is a pure, side-effect-free comparison.

        Args:
            snapshot: Current market snapshot.
            threshold: Price threshold in EUR/MWh.

        Returns:
            True if snapshot.spot_price_eur_mwh < threshold, False otherwise.
        """
        return snapshot.spot_price_eur_mwh < threshold

    def build_alert_message(
        self,
        snapshot: MarketSnapshot,
        threshold: float,
        channel: str = "slack",
    ) -> AlertMessage:
        """Build a formatted AlertMessage for the given snapshot and threshold.

        Args:
            snapshot: Current market snapshot.
            threshold: The price threshold that was breached.
            channel: Delivery channel ('slack' or 'email').

        Returns:
            A formatted AlertMessage.
        """
        return AlertMessage(
            subject=f"⚡ Energy Price Alert: {snapshot.spot_price_eur_mwh:.2f} EUR/MWh",
            body=(
                f"Price dropped below threshold of {threshold:.2f} EUR/MWh.\n"
                f"Current: {snapshot.spot_price_eur_mwh:.2f} EUR/MWh\n"
                f"Demand: {snapshot.demand_mw:.0f} MW | "
                f"Wind: {snapshot.wind_production_mw:.0f} MW"
            ),
            snapshot=snapshot,
            threshold=threshold,
            channel=channel,
        )

    def send_slack(self, message: AlertMessage) -> None:
        """POST an alert to the configured Slack incoming webhook URL.

        Retries once on failure. Logs a warning and continues if still failing.

        Args:
            message: The alert message to send.
        """
        if not self.slack_webhook_url:
            logger.warning("Slack webhook URL not configured; skipping Slack alert.")
            return

        payload = {"text": f"*{message.subject}*\n{message.body}"}

        for attempt in range(2):  # try once, retry once
            try:
                client = self._http_client or httpx.Client(timeout=10.0)
                response = client.post(self.slack_webhook_url, json=payload)
                if response.status_code < 300:
                    logger.info("Slack alert sent successfully.")
                    return
                else:
                    raise ValueError(
                        f"Slack webhook returned non-2xx status: {response.status_code}"
                    )
            except Exception as exc:
                if attempt == 0:
                    logger.warning(
                        "Slack alert attempt 1 failed: %s. Retrying in %.1fs…",
                        exc,
                        _RETRY_WAIT,
                    )
                    time.sleep(_RETRY_WAIT)
                else:
                    logger.warning(
                        "Slack alert failed after retry: %s. Continuing without alert.", exc
                    )

    def send_email(self, message: AlertMessage) -> None:
        """Send an alert email via SMTP.

        Retries once on failure. Logs a warning and continues if still failing.

        Args:
            message: The alert message to send.
        """
        if not self.smtp_host or not self.alert_email_to:
            logger.warning("SMTP not configured; skipping email alert.")
            return

        for attempt in range(2):  # try once, retry once
            try:
                self._do_send_email(message)
                logger.info("Email alert sent successfully.")
                return
            except Exception as exc:
                if attempt == 0:
                    logger.warning(
                        "Email alert attempt 1 failed: %s. Retrying in %.1fs…",
                        exc,
                        _RETRY_WAIT,
                    )
                    time.sleep(_RETRY_WAIT)
                else:
                    logger.warning(
                        "Email alert failed after retry: %s. Continuing without alert.", exc
                    )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _do_send_email(self, message: AlertMessage) -> None:
        """Single attempt to send an email via SMTP."""
        msg = MIMEText(message.body)
        msg["Subject"] = message.subject
        msg["From"] = self.smtp_user
        msg["To"] = self.alert_email_to

        with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
            server.starttls()
            if self.smtp_user and self.smtp_password:
                server.login(self.smtp_user, self.smtp_password)
            server.sendmail(self.smtp_user, [self.alert_email_to], msg.as_string())
