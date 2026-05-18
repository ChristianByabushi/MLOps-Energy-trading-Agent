"""Unit tests for ActionDispatcher.

Validates: Requirements 5.1, 5.2, 5.3, 5.4, 5.5
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, call, patch

import pytest

from agent.dispatcher import ActionDispatcher, TradeResult
from agent.logger import DecisionLogger
from agent.alert import AlertService
from agent.models import (
    ActionResult,
    ActionType,
    LogEntry,
    MarketSnapshot,
    StorageError,
    TradeDecision,
    TradeSignal,
)
from uuid import uuid4


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def make_snapshot(price: float = 65.0) -> MarketSnapshot:
    return MarketSnapshot(
        timestamp=datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc),
        spot_price_eur_mwh=price,
        demand_mw=50000.0,
        wind_production_mw=15000.0,
    )


def make_decision(action: ActionType, signal: TradeSignal = TradeSignal.HOLD) -> TradeDecision:
    return TradeDecision(
        timestamp=datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc),
        snapshot=make_snapshot(),
        action=action,
        signal=signal,
        rationale="Market conditions are stable, holding position.",
        confidence=0.75,
    )


def make_log_entry(decision: TradeDecision) -> LogEntry:
    return LogEntry(
        s3_key=f"logs/2024-01-15/{decision.id}.json",
        decision_id=decision.id,
        uploaded_at=datetime(2024, 1, 15, 12, 0, 1, tzinfo=timezone.utc),
    )


# ---------------------------------------------------------------------------
# dispatch — always logs
# ---------------------------------------------------------------------------


def test_dispatch_always_calls_logger_for_log_action():
    """Test dispatch always calls DecisionLogger.log regardless of action type (LOG)."""
    mock_logger = MagicMock(spec=DecisionLogger)
    decision = make_decision(ActionType.LOG)
    mock_logger.log.return_value = make_log_entry(decision)

    dispatcher = ActionDispatcher(decision_logger=mock_logger)
    result = dispatcher.dispatch(decision)

    mock_logger.log.assert_called_once_with(decision)
    assert result.logged is True


def test_dispatch_always_calls_logger_for_trade_action():
    """Test dispatch always calls DecisionLogger.log regardless of action type (TRADE)."""
    mock_logger = MagicMock(spec=DecisionLogger)
    decision = make_decision(ActionType.TRADE, TradeSignal.BUY)
    mock_logger.log.return_value = make_log_entry(decision)

    dispatcher = ActionDispatcher(decision_logger=mock_logger)
    result = dispatcher.dispatch(decision)

    mock_logger.log.assert_called_once_with(decision)
    assert result.logged is True


def test_dispatch_always_calls_logger_for_alert_action():
    """Test dispatch always calls DecisionLogger.log regardless of action type (ALERT)."""
    mock_logger = MagicMock(spec=DecisionLogger)
    mock_alert = MagicMock(spec=AlertService)
    decision = make_decision(ActionType.ALERT)
    mock_logger.log.return_value = make_log_entry(decision)

    dispatcher = ActionDispatcher(decision_logger=mock_logger, alert_service=mock_alert)
    result = dispatcher.dispatch(decision)

    mock_logger.log.assert_called_once_with(decision)
    assert result.logged is True


# ---------------------------------------------------------------------------
# dispatch — conditional trade
# ---------------------------------------------------------------------------

def test_dispatch_calls_execute_mock_trade_for_trade_decision():
    """Test dispatch calls execute_mock_trade only for TRADE decisions."""
    mock_logger = MagicMock(spec=DecisionLogger)
    decision = make_decision(ActionType.TRADE, TradeSignal.BUY)
    mock_logger.log.return_value = make_log_entry(decision)

    dispatcher = ActionDispatcher(decision_logger=mock_logger)

    with patch.object(dispatcher, "execute_mock_trade", wraps=dispatcher.execute_mock_trade) as mock_trade:
        result = dispatcher.dispatch(decision)

    mock_trade.assert_called_once_with(TradeSignal.BUY)
    assert result.trade_executed is True
    assert result.alert_sent is False


def test_dispatch_does_not_call_trade_for_log_decision():
    """Test dispatch does not call execute_mock_trade for LOG decisions."""
    mock_logger = MagicMock(spec=DecisionLogger)
    decision = make_decision(ActionType.LOG)
    mock_logger.log.return_value = make_log_entry(decision)

    dispatcher = ActionDispatcher(decision_logger=mock_logger)

    with patch.object(dispatcher, "execute_mock_trade") as mock_trade:
        result = dispatcher.dispatch(decision)

    mock_trade.assert_not_called()
    assert result.trade_executed is False


def test_dispatch_does_not_call_trade_for_alert_decision():
    """Test dispatch does not call execute_mock_trade for ALERT decisions."""
    mock_logger = MagicMock(spec=DecisionLogger)
    mock_alert = MagicMock(spec=AlertService)
    decision = make_decision(ActionType.ALERT)
    mock_logger.log.return_value = make_log_entry(decision)

    dispatcher = ActionDispatcher(decision_logger=mock_logger, alert_service=mock_alert)

    with patch.object(dispatcher, "execute_mock_trade") as mock_trade:
        result = dispatcher.dispatch(decision)

    mock_trade.assert_not_called()
    assert result.trade_executed is False

# ---------------------------------------------------------------------------
# dispatch — price-threshold alert (fires unconditionally when price < threshold)
# ---------------------------------------------------------------------------


def make_low_price_decision(action: ActionType = ActionType.LOG,
                             signal: TradeSignal = TradeSignal.HOLD) -> TradeDecision:
    """Decision with price=28.0, well below the default threshold of 50.0."""
    return TradeDecision(
        timestamp=datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc),
        snapshot=make_snapshot(price=28.0),
        action=action,
        signal=signal,
        rationale="Market conditions are stable, holding position.",
        confidence=0.75,
    )


def make_high_price_decision(action: ActionType = ActionType.LOG,
                              signal: TradeSignal = TradeSignal.HOLD) -> TradeDecision:
    """Decision with price=80.0, above the default threshold of 50.0."""
    return TradeDecision(
        timestamp=datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc),
        snapshot=make_snapshot(price=80.0),
        action=action,
        signal=signal,
        rationale="Market conditions are stable, holding position.",
        confidence=0.75,
    )


def test_dispatch_sends_alert_when_price_below_threshold():
    """Alert fires when price < threshold, regardless of LLM action type."""
    mock_logger = MagicMock(spec=DecisionLogger)
    mock_alert = MagicMock(spec=AlertService)
    mock_alert.should_alert.return_value = True

    decision = make_low_price_decision(ActionType.TRADE)  # LLM chose TRADE, not ALERT
    mock_logger.log.return_value = make_log_entry(decision)

    dispatcher = ActionDispatcher(
        decision_logger=mock_logger,
        alert_service=mock_alert,
        alert_threshold=50.0,
    )
    result = dispatcher.dispatch(decision)

    mock_alert.should_alert.assert_called_once()
    assert result.alert_sent is True


def test_dispatch_does_not_alert_when_price_above_threshold():
    """No alert when price >= threshold, even if LLM chose ALERT action."""
    mock_logger = MagicMock(spec=DecisionLogger)
    mock_alert = MagicMock(spec=AlertService)
    mock_alert.should_alert.return_value = False

    decision = make_high_price_decision(ActionType.ALERT)  # LLM chose ALERT but price is high
    mock_logger.log.return_value = make_log_entry(decision)

    dispatcher = ActionDispatcher(
        decision_logger=mock_logger,
        alert_service=mock_alert,
        alert_threshold=50.0,
    )
    result = dispatcher.dispatch(decision)

    mock_alert.should_alert.assert_called_once()
    assert result.alert_sent is False


def test_dispatch_calls_alert_service_for_alert_decision():
    """Alert fires when price is below threshold (action type is irrelevant)."""
    mock_logger = MagicMock(spec=DecisionLogger)
    mock_alert = MagicMock(spec=AlertService)
    mock_alert.should_alert.return_value = True

    decision = make_low_price_decision(ActionType.ALERT)
    mock_logger.log.return_value = make_log_entry(decision)

    dispatcher = ActionDispatcher(decision_logger=mock_logger, alert_service=mock_alert)
    result = dispatcher.dispatch(decision)

    assert result.alert_sent is True
    assert result.trade_executed is False


def test_dispatch_does_not_call_alert_for_log_decision():
    """No alert when price is above threshold, even for LOG action."""
    mock_logger = MagicMock(spec=DecisionLogger)
    mock_alert = MagicMock(spec=AlertService)
    mock_alert.should_alert.return_value = False

    decision = make_high_price_decision(ActionType.LOG)
    mock_logger.log.return_value = make_log_entry(decision)

    dispatcher = ActionDispatcher(decision_logger=mock_logger, alert_service=mock_alert)
    result = dispatcher.dispatch(decision)

    mock_alert.send_slack.assert_not_called()
    mock_alert.send_email.assert_not_called()
    assert result.alert_sent is False


def test_dispatch_does_not_call_alert_for_trade_decision():
    """No alert when price is above threshold, even for TRADE action."""
    mock_logger = MagicMock(spec=DecisionLogger)
    mock_alert = MagicMock(spec=AlertService)
    mock_alert.should_alert.return_value = False

    decision = make_high_price_decision(ActionType.TRADE, TradeSignal.SELL)
    mock_logger.log.return_value = make_log_entry(decision)

    dispatcher = ActionDispatcher(decision_logger=mock_logger, alert_service=mock_alert)
    result = dispatcher.dispatch(decision)

    mock_alert.send_slack.assert_not_called()
    mock_alert.send_email.assert_not_called()
    assert result.alert_sent is False


# ---------------------------------------------------------------------------
# dispatch — ActionResult accuracy
# ---------------------------------------------------------------------------


def test_dispatch_action_result_for_log_decision():
    """LOG decision with high price: logged=True, no trade, no alert."""
    mock_logger = MagicMock(spec=DecisionLogger)
    mock_alert = MagicMock(spec=AlertService)
    mock_alert.should_alert.return_value = False

    decision = make_high_price_decision(ActionType.LOG)
    log_entry = make_log_entry(decision)
    mock_logger.log.return_value = log_entry

    dispatcher = ActionDispatcher(decision_logger=mock_logger, alert_service=mock_alert)
    result = dispatcher.dispatch(decision)

    assert result.logged is True
    assert result.trade_executed is False
    assert result.alert_sent is False
    assert result.log_entry == log_entry


def test_dispatch_action_result_for_trade_decision():
    """TRADE decision with high price: logged=True, trade=True, no alert."""
    mock_logger = MagicMock(spec=DecisionLogger)
    mock_alert = MagicMock(spec=AlertService)
    mock_alert.should_alert.return_value = False

    decision = make_high_price_decision(ActionType.TRADE, TradeSignal.BUY)
    log_entry = make_log_entry(decision)
    mock_logger.log.return_value = log_entry

    dispatcher = ActionDispatcher(decision_logger=mock_logger, alert_service=mock_alert)
    result = dispatcher.dispatch(decision)

    assert result.logged is True
    assert result.trade_executed is True
    assert result.alert_sent is False
    assert result.log_entry == log_entry


def test_dispatch_action_result_for_alert_decision():
    """Low price: logged=True, no trade, alert=True regardless of action type."""
    mock_logger = MagicMock(spec=DecisionLogger)
    mock_alert = MagicMock(spec=AlertService)
    mock_alert.should_alert.return_value = True

    decision = make_low_price_decision(ActionType.LOG)
    log_entry = make_log_entry(decision)
    mock_logger.log.return_value = log_entry

    dispatcher = ActionDispatcher(decision_logger=mock_logger, alert_service=mock_alert)
    result = dispatcher.dispatch(decision)

    assert result.logged is True
    assert result.trade_executed is False
    assert result.alert_sent is True
    assert result.log_entry == log_entry


# ---------------------------------------------------------------------------
# execute_mock_trade
# ---------------------------------------------------------------------------


def test_execute_mock_trade_returns_trade_result():
    """Test execute_mock_trade returns a TradeResult with the correct signal."""
    dispatcher = ActionDispatcher()
    result = dispatcher.execute_mock_trade(TradeSignal.BUY)

    assert isinstance(result, TradeResult)
    assert result.signal == TradeSignal.BUY
    assert result.status == "mock_executed"
    assert result.executed_at is not None
