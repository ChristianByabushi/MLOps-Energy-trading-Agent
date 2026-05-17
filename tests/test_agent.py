"""Unit tests for ReActAgent.

Validates: Requirements 4.1, 4.2, 4.3, 4.4, 4.5
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

from agent.config import AgentConfig
from agent.dispatcher import ActionDispatcher
from agent.models import (
    ActionResult,
    ActionType,
    AgentRunResult,
    LogEntry,
    MarketSnapshot,
    PerceptionError,
    TradeDecision,
    TradeSignal,
)
from agent.perceiver import MarketPerceiver
from agent.react_agent import ReActAgent, _MAX_LLM_RETRIES


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def make_snapshot() -> MarketSnapshot:
    return MarketSnapshot(
        timestamp=datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc),
        spot_price_eur_mwh=65.40,
        demand_mw=50000.0,
        wind_production_mw=15000.0,
    )


def make_decision(snapshot: MarketSnapshot, action: ActionType = ActionType.LOG) -> TradeDecision:
    return TradeDecision(
        timestamp=datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc),
        snapshot=snapshot,
        action=action,
        signal=TradeSignal.HOLD,
        rationale="Market conditions are stable, holding position.",
        confidence=0.75,
    )


def make_log_entry(decision: TradeDecision) -> LogEntry:
    return LogEntry(
        s3_key=f"logs/2024-01-15/{decision.id}.json",
        decision_id=decision.id,
        uploaded_at=datetime(2024, 1, 15, 12, 0, 1, tzinfo=timezone.utc),
    )


def make_action_result(decision: TradeDecision, alert_sent: bool = False, trade_executed: bool = False) -> ActionResult:
    return ActionResult(
        logged=True,
        trade_executed=trade_executed,
        alert_sent=alert_sent,
        log_entry=make_log_entry(decision),
    )


# ---------------------------------------------------------------------------
# run_cycle — perceive → reason → act order
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_cycle_calls_perceive_then_reason_then_act():
    """Test run_cycle calls perceive, then reason, then act in order."""
    snapshot = make_snapshot()
    decision = make_decision(snapshot)
    action_result = make_action_result(decision)

    call_order = []

    mock_perceiver = MagicMock(spec=MarketPerceiver)
    mock_perceiver.perceive.side_effect = lambda: (call_order.append("perceive"), snapshot)[1]

    mock_dispatcher = MagicMock(spec=ActionDispatcher)
    mock_dispatcher.dispatch.side_effect = lambda d: (call_order.append("act"), action_result)[1]

    # Mock the PydanticAI agent
    mock_pydantic_result = MagicMock()
    mock_pydantic_result.data = decision
    mock_pydantic_agent = MagicMock()
    mock_pydantic_agent.run = AsyncMock(
        side_effect=lambda prompt: (call_order.append("reason"), mock_pydantic_result)[1]
    )

    agent = ReActAgent(
        perceiver=mock_perceiver,
        dispatcher=mock_dispatcher,
        pydantic_agent=mock_pydantic_agent,
    )

    result = await agent.run_cycle()

    assert call_order == ["perceive", "reason", "act"]
    assert isinstance(result, AgentRunResult)


@pytest.mark.asyncio
async def test_run_cycle_returns_agent_run_result_with_correct_flags():
    """Test run_cycle returns AgentRunResult with correct flags and timestamps."""
    snapshot = make_snapshot()
    decision = make_decision(snapshot, ActionType.ALERT)
    action_result = ActionResult(
        logged=True,
        trade_executed=False,
        alert_sent=True,
        log_entry=make_log_entry(decision),
    )

    mock_perceiver = MagicMock(spec=MarketPerceiver)
    mock_perceiver.perceive.return_value = snapshot

    mock_dispatcher = MagicMock(spec=ActionDispatcher)
    mock_dispatcher.dispatch.return_value = action_result

    mock_pydantic_result = MagicMock()
    mock_pydantic_result.data = decision
    mock_pydantic_agent = MagicMock()
    mock_pydantic_agent.run = AsyncMock(return_value=mock_pydantic_result)

    agent = ReActAgent(
        perceiver=mock_perceiver,
        dispatcher=mock_dispatcher,
        pydantic_agent=mock_pydantic_agent,
    )

    result = await agent.run_cycle()

    assert isinstance(result, AgentRunResult)
    assert result.decision == decision
    assert result.alert_sent is True
    assert result.trade_executed is False
    assert result.log_entry == action_result.log_entry
    assert result.started_at is not None
    assert result.completed_at is not None
    assert result.completed_at >= result.started_at


@pytest.mark.asyncio
async def test_run_cycle_records_started_at_and_completed_at():
    """Test run_cycle records started_at and completed_at timestamps."""
    snapshot = make_snapshot()
    decision = make_decision(snapshot)
    action_result = make_action_result(decision)

    mock_perceiver = MagicMock(spec=MarketPerceiver)
    mock_perceiver.perceive.return_value = snapshot

    mock_dispatcher = MagicMock(spec=ActionDispatcher)
    mock_dispatcher.dispatch.return_value = action_result

    mock_pydantic_result = MagicMock()
    mock_pydantic_result.data = decision
    mock_pydantic_agent = MagicMock()
    mock_pydantic_agent.run = AsyncMock(return_value=mock_pydantic_result)

    agent = ReActAgent(
        perceiver=mock_perceiver,
        dispatcher=mock_dispatcher,
        pydantic_agent=mock_pydantic_agent,
    )

    result = await agent.run_cycle()

    assert result.started_at is not None
    assert result.completed_at is not None
    assert result.completed_at >= result.started_at


# ---------------------------------------------------------------------------
# run_cycle — LLM validation failure fallback
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_cycle_falls_back_after_3_llm_failures():
    """Test run_cycle falls back to default TradeDecision after 3 LLM validation failures."""
    snapshot = make_snapshot()

    mock_perceiver = MagicMock(spec=MarketPerceiver)
    mock_perceiver.perceive.return_value = snapshot

    # Dispatcher should still be called with the fallback decision
    fallback_action_result = ActionResult(logged=True, log_entry=None)
    mock_dispatcher = MagicMock(spec=ActionDispatcher)
    mock_dispatcher.dispatch.return_value = fallback_action_result

    # LLM always fails
    mock_pydantic_agent = MagicMock()
    mock_pydantic_agent.run = AsyncMock(side_effect=Exception("LLM validation error"))

    agent = ReActAgent(
        perceiver=mock_perceiver,
        dispatcher=mock_dispatcher,
        pydantic_agent=mock_pydantic_agent,
    )

    result = await agent.run_cycle()

    # Should have tried 3 times
    assert mock_pydantic_agent.run.call_count == _MAX_LLM_RETRIES

    # Fallback decision should be used
    assert result.decision.action == ActionType.LOG
    assert result.decision.signal == TradeSignal.HOLD
    assert result.decision.rationale == "Validation failed after retries"
    assert result.decision.confidence == 0.0

    # Dispatcher should still be called with the fallback decision
    mock_dispatcher.dispatch.assert_called_once()


# ---------------------------------------------------------------------------
# build_prompt
# ---------------------------------------------------------------------------


def test_build_prompt_includes_all_numeric_fields():
    """Test build_prompt includes all numeric fields from MarketSnapshot."""
    snapshot = make_snapshot()
    agent = ReActAgent()

    prompt = agent.build_prompt(snapshot)

    assert str(snapshot.spot_price_eur_mwh) in prompt or "65.4" in prompt
    assert str(snapshot.demand_mw) in prompt or "50000" in prompt
    assert str(snapshot.wind_production_mw) in prompt or "15000" in prompt
    assert str(round(snapshot.wind_ratio, 4)) in prompt or "0.3" in prompt
    assert len(prompt) > 0


def test_build_prompt_is_non_empty():
    """Test build_prompt returns a non-empty string."""
    snapshot = make_snapshot()
    agent = ReActAgent()

    prompt = agent.build_prompt(snapshot)

    assert isinstance(prompt, str)
    assert len(prompt) > 10


def test_build_prompt_contains_timestamp():
    """Test build_prompt includes the snapshot timestamp."""
    snapshot = make_snapshot()
    agent = ReActAgent()

    prompt = agent.build_prompt(snapshot)

    assert "2024-01-15" in prompt
