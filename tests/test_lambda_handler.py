"""Unit tests for the Lambda handler.

Validates: Requirements 8.1, 8.3
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.models import (
    ActionType,
    AgentRunResult,
    LogEntry,
    MarketSnapshot,
    TradeDecision,
    TradeSignal,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_snapshot() -> MarketSnapshot:
    return MarketSnapshot(
        timestamp=datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc),
        spot_price_eur_mwh=65.40,
        demand_mw=50000.0,
        wind_production_mw=15000.0,
    )


def make_decision(snapshot: MarketSnapshot) -> TradeDecision:
    return TradeDecision(
        timestamp=datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc),
        snapshot=snapshot,
        action=ActionType.LOG,
        signal=TradeSignal.HOLD,
        rationale="Market conditions are stable, holding position.",
        confidence=0.75,
    )


def make_agent_run_result(decision: TradeDecision) -> AgentRunResult:
    return AgentRunResult(
        started_at=datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc),
        completed_at=datetime(2024, 1, 15, 12, 0, 1, tzinfo=timezone.utc),
        decision=decision,
        log_entry=LogEntry(
            s3_key=f"logs/2024-01-15/{decision.id}.json",
            decision_id=decision.id,
            uploaded_at=datetime(2024, 1, 15, 12, 0, 1, tzinfo=timezone.utc),
        ),
        alert_sent=False,
        trade_executed=False,
    )


# ---------------------------------------------------------------------------
# handler — success (HTTP 200)
# ---------------------------------------------------------------------------


def test_handler_returns_200_on_success():
    """Test handler returns HTTP 200 with serialised AgentRunResult on success."""
    snapshot = make_snapshot()
    decision = make_decision(snapshot)
    run_result = make_agent_run_result(decision)

    mock_agent = MagicMock()
    mock_agent.run_cycle = AsyncMock(return_value=run_result)

    with patch("lambda_handler.AgentConfig") as mock_config_cls, \
         patch("lambda_handler.ReActAgent") as mock_agent_cls:
        mock_config_cls.from_env.return_value = MagicMock()
        mock_agent_cls.return_value = mock_agent

        from lambda_handler import handler
        response = handler({}, None)

    assert response["statusCode"] == 200
    body = response["body"]
    assert isinstance(body, dict)
    # Verify the response contains key fields from AgentRunResult
    assert "decision" in body
    assert "started_at" in body
    assert "completed_at" in body


def test_handler_calls_from_env():
    """Test handler calls AgentConfig.from_env() to load configuration."""
    snapshot = make_snapshot()
    decision = make_decision(snapshot)
    run_result = make_agent_run_result(decision)

    mock_agent = MagicMock()
    mock_agent.run_cycle = AsyncMock(return_value=run_result)

    with patch("lambda_handler.AgentConfig") as mock_config_cls, \
         patch("lambda_handler.ReActAgent") as mock_agent_cls:
        mock_config = MagicMock()
        mock_config_cls.from_env.return_value = mock_config
        mock_agent_cls.return_value = mock_agent

        from lambda_handler import handler
        handler({}, None)

    mock_config_cls.from_env.assert_called_once()


def test_handler_passes_config_to_react_agent():
    """Test handler passes the config from from_env() to ReActAgent."""
    snapshot = make_snapshot()
    decision = make_decision(snapshot)
    run_result = make_agent_run_result(decision)

    mock_agent = MagicMock()
    mock_agent.run_cycle = AsyncMock(return_value=run_result)

    with patch("lambda_handler.AgentConfig") as mock_config_cls, \
         patch("lambda_handler.ReActAgent") as mock_agent_cls:
        mock_config = MagicMock()
        mock_config_cls.from_env.return_value = mock_config
        mock_agent_cls.return_value = mock_agent

        from lambda_handler import handler
        handler({}, None)

    mock_agent_cls.assert_called_once_with(config=mock_config)


# ---------------------------------------------------------------------------
# handler — failure (HTTP 500)
# ---------------------------------------------------------------------------


def test_handler_returns_500_on_exception():
    """Test handler returns HTTP 500 with error message when run_cycle raises."""
    mock_agent = MagicMock()
    mock_agent.run_cycle = AsyncMock(side_effect=RuntimeError("Agent cycle failed"))

    with patch("lambda_handler.AgentConfig") as mock_config_cls, \
         patch("lambda_handler.ReActAgent") as mock_agent_cls:
        mock_config_cls.from_env.return_value = MagicMock()
        mock_agent_cls.return_value = mock_agent

        from lambda_handler import handler
        response = handler({}, None)

    assert response["statusCode"] == 500
    assert "error" in response["body"]
    assert "Agent cycle failed" in response["body"]["error"]


def test_handler_returns_500_on_config_error():
    """Test handler returns HTTP 500 when AgentConfig.from_env() raises."""
    with patch("lambda_handler.AgentConfig") as mock_config_cls:
        mock_config_cls.from_env.side_effect = ValueError("Missing required env var")

        from lambda_handler import handler
        response = handler({}, None)

    assert response["statusCode"] == 500
    assert "error" in response["body"]
