"""AlertService: sends Slack and Email notifications when price drops below threshold."""

from __future__ import annotations

import logging
import smtplib
import ssl
import time
from email.mime.multipart import MIMEMultipart
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
        """Single attempt to send an HTML+plain email via SMTP."""
        s = message.snapshot
        threshold = message.threshold

        # ── plain-text fallback ───────────────────────────────────────────────
        plain = (
            f"ENERGY TRADING ALERT\n"
            f"{'='*40}\n\n"
            f"Spot Price : {s.spot_price_eur_mwh:.2f} EUR/MWh\n"
            f"Threshold  : {threshold:.2f} EUR/MWh\n"
            f"Demand     : {s.demand_mw:,.0f} MW\n"
            f"Wind Prod. : {s.wind_production_mw:,.0f} MW\n"
            f"Wind Ratio : {s.wind_ratio:.1%}\n\n"
            f"AI Rationale:\n{message.body}\n\n"
            f"Sent by the MLOps Energy Trading Agent."
        )

        # ── HTML version ──────────────────────────────────────────────────────
        price_colour = "#e74c3c" if s.spot_price_eur_mwh < threshold else "#27ae60"
        html = f"""
<!DOCTYPE html>
<html>
<body style="font-family:Arial,sans-serif;background:#f4f4f4;padding:20px;margin:0;">
  <div style="max-width:520px;margin:auto;background:#fff;border-radius:8px;
              box-shadow:0 2px 8px rgba(0,0,0,0.1);overflow:hidden;">

    <!-- header -->
    <div style="background:#1a1a2e;padding:24px 28px;">
      <h1 style="color:#e94560;margin:0;font-size:22px;">
        ⚡ Energy Price Alert
      </h1>
      <p style="color:#aaa;margin:6px 0 0;font-size:13px;">
        MLOps Energy Trading Agent
      </p>
    </div>

    <!-- price highlight -->
    <div style="padding:24px 28px 12px;">
      <table style="width:100%;border-collapse:collapse;">
        <tr>
          <td style="padding:10px 14px;background:#fef9f0;border-radius:6px;
                     border-left:4px solid {price_colour};">
            <span style="font-size:13px;color:#888;">Spot Price</span><br>
            <span style="font-size:28px;font-weight:bold;color:{price_colour};">
              {s.spot_price_eur_mwh:.2f} EUR/MWh
            </span>
          </td>
          <td style="width:16px;"></td>
          <td style="padding:10px 14px;background:#f8f8f8;border-radius:6px;">
            <span style="font-size:13px;color:#888;">Alert Threshold</span><br>
            <span style="font-size:22px;font-weight:bold;color:#555;">
              {threshold:.2f} EUR/MWh
            </span>
          </td>
        </tr>
      </table>
    </div>

    <!-- market data -->
    <div style="padding:12px 28px;">
      <h3 style="color:#333;font-size:14px;margin:0 0 10px;
                 text-transform:uppercase;letter-spacing:1px;">
        Market Data
      </h3>
      <table style="width:100%;border-collapse:collapse;font-size:14px;">
        <tr style="background:#f8f8f8;">
          <td style="padding:8px 12px;color:#555;">Electricity Demand</td>
          <td style="padding:8px 12px;font-weight:bold;text-align:right;">
            {s.demand_mw:,.0f} MW
          </td>
        </tr>
        <tr>
          <td style="padding:8px 12px;color:#555;">Wind Production</td>
          <td style="padding:8px 12px;font-weight:bold;text-align:right;">
            {s.wind_production_mw:,.0f} MW
          </td>
        </tr>
        <tr style="background:#f8f8f8;">
          <td style="padding:8px 12px;color:#555;">Wind / Demand Ratio</td>
          <td style="padding:8px 12px;font-weight:bold;text-align:right;">
            {s.wind_ratio:.1%}
          </td>
        </tr>
      </table>
    </div>

    <!-- AI rationale -->
    <div style="padding:12px 28px 24px;">
      <h3 style="color:#333;font-size:14px;margin:0 0 10px;
                 text-transform:uppercase;letter-spacing:1px;">
        AI Reasoning
      </h3>
      <p style="background:#f0f4ff;border-left:4px solid #3498db;
                padding:12px 16px;border-radius:4px;
                color:#333;font-size:14px;line-height:1.6;margin:0;">
        {message.body}
      </p>
    </div>

    <!-- footer -->
    <div style="background:#f4f4f4;padding:14px 28px;text-align:center;">
      <p style="color:#aaa;font-size:12px;margin:0;">
        Sent automatically by the MLOps Energy Trading Agent
      </p>
    </div>

  </div>
</body>
</html>
"""

        # ── assemble MIME message ─────────────────────────────────────────────
        mime = MIMEMultipart("alternative")
        mime["Subject"] = message.subject
        mime["From"]    = self.smtp_user
        mime["To"]      = self.alert_email_to
        mime.attach(MIMEText(plain, "plain", "utf-8"))
        mime.attach(MIMEText(html,  "html",  "utf-8"))

        logger.info("Sending email to %s via %s:%s",
                    self.alert_email_to, self.smtp_host, self.smtp_port)

        if self.smtp_port == 465:
            ctx = ssl.create_default_context()
            with smtplib.SMTP_SSL(self.smtp_host, self.smtp_port,
                                   context=ctx, timeout=15) as server:
                if self.smtp_user and self.smtp_password:
                    server.login(self.smtp_user, self.smtp_password)
                server.sendmail(self.smtp_user, [self.alert_email_to], mime.as_string())
        else:
            with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=15) as server:
                server.ehlo()
                server.starttls(context=ssl.create_default_context())
                server.ehlo()
                if self.smtp_user and self.smtp_password:
                    server.login(self.smtp_user, self.smtp_password)
                server.sendmail(self.smtp_user, [self.alert_email_to], mime.as_string())

        logger.info("Email sent successfully to %s", self.alert_email_to)
