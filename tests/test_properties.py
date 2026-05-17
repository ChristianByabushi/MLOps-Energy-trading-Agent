"""Property-based tests for core data model invariants.

**Validates: Requirements 2.1, 2.3, 2.6, 3.1, 3.2, 6.1**
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from agent.models import (
    ActionType,
    MarketSnapshot,
    PriceRow,
    TradeDecision,
    TradeSignal,
)

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Positive floats for prices and demand
positive_float = st.floats(min_value=0.01, max_value=1_000_000.0, allow_nan=False, allow_infinity=False)

# Non-negative floats for wind production
non_negative_float = st.floats(min_value=0.0, max_value=1_000_000.0, allow_nan=False, allow_infinity=False)

# Rationale strings of at least 10 characters
rationale_str = st.text(min_size=10, max_size=500)

# Confidence in [0.0, 1.0]
confidence_float = st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)

# Fixed timestamp for simplicity
fixed_timestamp = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)


def build_snapshot(price: float, demand: float, wind: float) -> MarketSnapshot:
    """Helper to build a MarketSnapshot, clamping wind to demand to keep wind_ratio <= 1."""
    wind_clamped = min(wind, demand)
    return MarketSnapshot(
        timestamp=fixed_timestamp,
        spot_price_eur_mwh=price,
        demand_mw=demand,
        wind_production_mw=wind_clamped,
    )


# ---------------------------------------------------------------------------
# Property 1: Price Positivity
# **Validates: Requirements 2.1**
# ---------------------------------------------------------------------------


@given(price=positive_float)
def test_price_row_price_positivity(price: float) -> None:
    """Property 1: PriceRow.price_eur_mwh > 0 for all valid instances.

    **Validates: Requirements 2.1**
    """
    row = PriceRow(timestamp=fixed_timestamp, price_eur_mwh=price, region="DE")
    assert row.price_eur_mwh > 0


@given(price=st.floats(max_value=0.0, allow_nan=False, allow_infinity=False))
def test_price_row_rejects_non_positive_price(price: float) -> None:
    """PriceRow must reject any price_eur_mwh <= 0.

    **Validates: Requirements 2.1**
    """
    with pytest.raises(ValidationError):
        PriceRow(timestamp=fixed_timestamp, price_eur_mwh=price, region="DE")


# ---------------------------------------------------------------------------
# Property 2: Wind Ratio Bounds
# **Validates: Requirements 2.3, 2.6**
# ---------------------------------------------------------------------------


@given(
    demand=positive_float,
    wind=non_negative_float,
)
def test_wind_ratio_bounds(demand: float, wind: float) -> None:
    """Property 2: 0.0 <= MarketSnapshot.wind_ratio <= 1.0 for all valid instances.

    **Validates: Requirements 2.3, 2.6**
    """
    snapshot = build_snapshot(price=50.0, demand=demand, wind=wind)
    assert 0.0 <= snapshot.wind_ratio <= 1.0


@given(
    demand=positive_float,
    wind=non_negative_float,
)
def test_wind_ratio_computed_correctly(demand: float, wind: float) -> None:
    """wind_ratio is auto-computed as wind / demand, clamped to [0, 1].

    **Validates: Requirements 2.3**
    """
    snapshot = build_snapshot(price=50.0, demand=demand, wind=wind)
    expected = min(1.0, wind / demand) if wind <= demand else 1.0
    assert abs(snapshot.wind_ratio - expected) < 1e-9


# ---------------------------------------------------------------------------
# Property 6: Rationale Non-Triviality and Confidence Bounds
# **Validates: Requirements 3.1, 3.2**
# ---------------------------------------------------------------------------


@given(
    rationale=rationale_str,
    confidence=confidence_float,
)

def test_trade_decision_rationale_and_confidence(rationale: str, confidence: float) -> None:
    """Property 6: len(d.rationale) >= 10 and 0.0 <= d.confidence <= 1.0 for all valid TradeDecision.

    **Validates: Requirements 3.1, 3.2**
    """
    snapshot = build_snapshot(price=65.0, demand=50000.0, wind=15000.0)
    decision = TradeDecision(
        timestamp=fixed_timestamp,
        snapshot=snapshot,
        action=ActionType.LOG,
        signal=TradeSignal.HOLD,
        rationale=rationale,
        confidence=confidence,
    )
    assert len(decision.rationale) >= 10
    assert 0.0 <= decision.confidence <= 1.0


@given(rationale=st.text(max_size=9))
def test_trade_decision_rejects_short_rationale(rationale: str) -> None:
    """TradeDecision must reject rationale with fewer than 10 characters.

    **Validates: Requirements 3.1**
    """
    snapshot = build_snapshot(price=65.0, demand=50000.0, wind=15000.0)
    with pytest.raises(ValidationError):
        TradeDecision(
            timestamp=fixed_timestamp,
            snapshot=snapshot,
            action=ActionType.LOG,
            signal=TradeSignal.HOLD,
            rationale=rationale,
            confidence=0.5,
        )


@given(confidence=st.one_of(
    st.floats(max_value=-0.001, allow_nan=False, allow_infinity=False),
    st.floats(min_value=1.001, allow_nan=False, allow_infinity=False),
))

def test_trade_decision_rejects_out_of_range_confidence(confidence: float) -> None:
    """TradeDecision must reject confidence outside [0.0, 1.0].

    **Validates: Requirements 3.2**
    """
    snapshot = build_snapshot(price=65.0, demand=50000.0, wind=15000.0)
    with pytest.raises(ValidationError):
        TradeDecision(
            timestamp=fixed_timestamp,
            snapshot=snapshot,
            action=ActionType.LOG,
            signal=TradeSignal.HOLD,
            rationale="Valid rationale text here",
            confidence=confidence,
        )


# ---------------------------------------------------------------------------
# Property 7: Decision Serialisation Round Trip
# **Validates: Requirements 6.1**
# ---------------------------------------------------------------------------


@given(
    price=positive_float,
    demand=positive_float,
    wind=non_negative_float,
    rationale=rationale_str,
    confidence=confidence_float,
    action=st.sampled_from(list(ActionType)),
    signal=st.sampled_from(list(TradeSignal)),
)
def test_trade_decision_serialisation_round_trip(
    price: float,
    demand: float,
    wind: float,
    rationale: str,
    confidence: float,
    action: ActionType,
    signal: TradeSignal,
) -> None:
    """Property 7: model_validate_json(model_dump_json(d)) produces an equivalent TradeDecision.

    **Validates: Requirements 6.1**
    """
    snapshot = build_snapshot(price=price, demand=demand, wind=wind)
    original = TradeDecision(
        timestamp=fixed_timestamp,
        snapshot=snapshot,
        action=action,
        signal=signal,
        rationale=rationale,
        confidence=confidence,
    )

    json_str = original.model_dump_json()
    restored = TradeDecision.model_validate_json(json_str)

    assert restored.id == original.id
    assert restored.timestamp == original.timestamp
    assert restored.action == original.action
    assert restored.signal == original.signal
    assert restored.rationale == original.rationale
    assert abs(restored.confidence - original.confidence) < 1e-9
    assert abs(restored.snapshot.spot_price_eur_mwh - original.snapshot.spot_price_eur_mwh) < 1e-9
    assert abs(restored.snapshot.demand_mw - original.snapshot.demand_mw) < 1e-9
    assert abs(restored.snapshot.wind_production_mw - original.snapshot.wind_production_mw) < 1e-9
    assert abs(restored.snapshot.wind_ratio - original.snapshot.wind_ratio) < 1e-9
