"""Shared pytest fixtures for the MLOps Energy Trading Agent test suite."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from agent.models import (
    ActionType,
    AgentRunResult,
    AlertMessage,
    LogEntry,
    MarketSnapshot,
    PriceRow,
    TradeDecision,
    TradeSignal,
)


@pytest.fixture
def sample_snapshot() -> MarketSnapshot:
    """A valid MarketSnapshot for use in tests."""
    return MarketSnapshot(
        timestamp=datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc),
        spot_price_eur_mwh=65.40,
        demand_mw=50000.0,
        wind_production_mw=15000.0,
    )


@pytest.fixture
def sample_decision(sample_snapshot: MarketSnapshot) -> TradeDecision:
    """A valid TradeDecision for use in tests."""
    return TradeDecision(
        timestamp=datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc),
        snapshot=sample_snapshot,
        action=ActionType.LOG,
        signal=TradeSignal.HOLD,
        rationale="Market conditions are stable, holding position.",
        confidence=0.75,
    )


@pytest.fixture
def sample_price_row() -> PriceRow:
    """A valid PriceRow for use in tests."""
    return PriceRow(
        timestamp=datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc),
        price_eur_mwh=65.40,
        region="DE",
    )
