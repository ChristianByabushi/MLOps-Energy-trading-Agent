"""Unit tests for AlertService.

Validates: Requirements 7.1, 7.2, 7.5, 7.6
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import httpx
import pytest

from agent.alert import AlertService
from agent.models import AlertMessage, MarketSnapshot


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_snapshot(price: float, demand: float = 50000.0, wind: float = 15000.0) -> MarketSnapshot:
    """Build a MarketSnapshot with the given spot price."""
    return MarketSnapshot(
        timestamp=datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc),
        spot_price_eur_mwh=price,
        demand_mw=demand,
        wind_production_mw=wind,
    )


def make_alert_message(snapshot: MarketSnapshot, threshold: float = 50.0) -> AlertMessage:
    """Build an AlertMessage for the given snapshot."""
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
        channel="slack",
    )


# ---------------------------------------------------------------------------
# should_alert
# ---------------------------------------------------------------------------


def test_should_alert_returns_true_when_price_below_threshold():
    """Test should_alert returns True when price < threshold."""
    service = AlertService()
    snapshot = make_snapshot(price=40.0)
    assert service.should_alert(snapshot, threshold=50.0) is True


def test_should_alert_returns_false_when_price_equals_threshold():
    """Test should_alert returns False when price == threshold."""
    service = AlertService()
    snapshot = make_snapshot(price=50.0)
    assert service.should_alert(snapshot, threshold=50.0) is False


def test_should_alert_returns_false_when_price_above_threshold():
    """Test should_alert returns False when price > threshold."""
    service = AlertService()
    snapshot = make_snapshot(price=75.0)
    assert service.should_alert(snapshot, threshold=50.0) is False


def test_should_alert_boundary_just_below():
    """Test should_alert returns True for price just below threshold."""
    service = AlertService()
    snapshot = make_snapshot(price=49.99)
    assert service.should_alert(snapshot, threshold=50.0) is True


def test_should_alert_boundary_just_above():
    """Test should_alert returns False for price just above threshold."""
    service = AlertService()
    snapshot = make_snapshot(price=50.01)
    assert service.should_alert(snapshot, threshold=50.0) is False


# ---------------------------------------------------------------------------
# build_alert_message
# ---------------------------------------------------------------------------


def test_build_alert_message_includes_price():
    """Test build_alert_message includes current spot price in body."""
    service = AlertService()
    snapshot = make_snapshot(price=42.50)
    msg = service.build_alert_message(snapshot, threshold=50.0)
    assert "42.50" in msg.body


def test_build_alert_message_includes_threshold():
    """Test build_alert_message includes threshold in body."""
    service = AlertService()
    snapshot = make_snapshot(price=42.50)
    msg = service.build_alert_message(snapshot, threshold=50.0)
    assert "50.00" in msg.body


def test_build_alert_message_includes_demand():
    """Test build_alert_message includes demand in body."""
    service = AlertService()
    snapshot = make_snapshot(price=42.50, demand=50000.0)
    msg = service.build_alert_message(snapshot, threshold=50.0)
    assert "50000" in msg.body


def test_build_alert_message_includes_wind():
    """Test build_alert_message includes wind production in body."""
    service = AlertService()
    snapshot = make_snapshot(price=42.50, wind=15000.0)
    msg = service.build_alert_message(snapshot, threshold=50.0)
    assert "15000" in msg.body


# ---------------------------------------------------------------------------
# send_slack — success
# ---------------------------------------------------------------------------


def test_send_slack_success():
    """Test send_slack succeeds when webhook returns 2xx."""
    mock_response = MagicMock()
    mock_response.status_code = 200

    mock_client = MagicMock(spec=httpx.Client)
    mock_client.post.return_value = mock_response

    service = AlertService(
        slack_webhook_url="https://hooks.slack.com/test",
        http_client=mock_client,
    )
    snapshot = make_snapshot(price=42.50)
    msg = make_alert_message(snapshot)

    service.send_slack(msg)  # should not raise

    mock_client.post.assert_called_once()


# ---------------------------------------------------------------------------
# send_slack — failure (non-2xx)
# ---------------------------------------------------------------------------


def test_send_slack_logs_warning_on_non_2xx(caplog):
    """Test send_slack logs a warning and does not raise when webhook returns non-2xx."""
    mock_response = MagicMock()
    mock_response.status_code = 500

    mock_client = MagicMock(spec=httpx.Client)
    mock_client.post.return_value = mock_response

    service = AlertService(
        slack_webhook_url="https://hooks.slack.com/test",
        http_client=mock_client,
    )
    snapshot = make_snapshot(price=42.50)
    msg = make_alert_message(snapshot)

    with caplog.at_level(logging.WARNING, logger="agent.alert"):
        with patch("agent.alert.time.sleep"):  # don't actually sleep
            service.send_slack(msg)  # must NOT raise

    assert mock_client.post.call_count == 2  # initial + 1 retry
    assert any("warning" in record.levelname.lower() or "failed" in record.message.lower()
               for record in caplog.records)


def test_send_slack_logs_warning_on_connection_error(caplog):
    """Test send_slack logs a warning and does not raise on connection error."""
    mock_client = MagicMock(spec=httpx.Client)
    mock_client.post.side_effect = httpx.ConnectError("Connection refused")

    service = AlertService(
        slack_webhook_url="https://hooks.slack.com/test",
        http_client=mock_client,
    )
    snapshot = make_snapshot(price=42.50)
    msg = make_alert_message(snapshot)

    with caplog.at_level(logging.WARNING, logger="agent.alert"):
        with patch("agent.alert.time.sleep"):
            service.send_slack(msg)  # must NOT raise

    assert mock_client.post.call_count == 2  # initial + 1 retry


def test_send_slack_skips_when_no_webhook_url(caplog):
    """Test send_slack skips and logs warning when webhook URL is not configured."""
    service = AlertService(slack_webhook_url="")
    snapshot = make_snapshot(price=42.50)
    msg = make_alert_message(snapshot)

    with caplog.at_level(logging.WARNING, logger="agent.alert"):
        service.send_slack(msg)  # must NOT raise

    assert any("not configured" in record.message.lower() for record in caplog.records)


# ---------------------------------------------------------------------------
# send_email — failure
# ---------------------------------------------------------------------------


def test_send_email_logs_warning_on_smtp_failure(caplog):
    """Test send_email logs a warning and does not raise on SMTP failure."""
    service = AlertService(
        smtp_host="smtp.example.com",
        smtp_port=587,
        smtp_user="user@example.com",
        smtp_password="password",
        alert_email_to="trader@example.com",
    )
    snapshot = make_snapshot(price=42.50)
    msg = make_alert_message(snapshot)
    msg = AlertMessage(
        subject=msg.subject,
        body=msg.body,
        snapshot=snapshot,
        threshold=50.0,
        channel="email",
    )

    with caplog.at_level(logging.WARNING, logger="agent.alert"):
        with patch("agent.alert.smtplib.SMTP") as mock_smtp:
            mock_smtp.side_effect = ConnectionRefusedError("Connection refused")
            with patch("agent.alert.time.sleep"):
                service.send_email(msg)  # must NOT raise

    assert any(
        "failed" in record.message.lower() or "warning" in record.levelname.lower()
        for record in caplog.records
    )


def test_send_email_skips_when_not_configured(caplog):
    """Test send_email skips and logs warning when SMTP is not configured."""
    service = AlertService()  # no smtp_host or alert_email_to
    snapshot = make_snapshot(price=42.50)
    msg = make_alert_message(snapshot)

    with caplog.at_level(logging.WARNING, logger="agent.alert"):
        service.send_email(msg)  # must NOT raise

    assert any("not configured" in record.message.lower() for record in caplog.records)
