"""Property-based tests for AlertService.

Property 3: Alert If and Only If Below Threshold
**Validates: Requirements 7.1, 7.2**
"""

from __future__ import annotations

from datetime import datetime, timezone

from hypothesis import given
from hypothesis import strategies as st

from agent.alert import AlertService
from agent.models import MarketSnapshot


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

positive_float = st.floats(min_value=0.01, max_value=1_000_000.0, allow_nan=False, allow_infinity=False)


def build_snapshot(price: float) -> MarketSnapshot:
    """Build a MarketSnapshot with the given spot price."""
    return MarketSnapshot(
        timestamp=datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc),
        spot_price_eur_mwh=price,
        demand_mw=50000.0,
        wind_production_mw=15000.0,
    )


# ---------------------------------------------------------------------------
# Property 3: Alert If and Only If Below Threshold
# **Validates: Requirements 7.1, 7.2**
# ---------------------------------------------------------------------------


@given(
    price=positive_float,
    threshold=positive_float,
)
def test_alert_iff_below_threshold(price: float, threshold: float) -> None:
    """Property 3: should_alert(s, t) == (s.spot_price_eur_mwh < t) for all valid s and t > 0.

    The alert predicate must be a pure, side-effect-free comparison.
    **Validates: Requirements 7.1, 7.2**
    """
    snapshot = build_snapshot(price=price)
    service = AlertService()

    result = service.should_alert(snapshot, threshold)

    assert result == (price < threshold)


@given(
    price=positive_float,
    threshold=positive_float,
)
def test_alert_predicate_is_pure(price: float, threshold: float) -> None:
    """should_alert must return the same result on repeated calls (pure function).

    **Validates: Requirements 7.1, 7.2**
    """
    snapshot = build_snapshot(price=price)
    service = AlertService()

    result1 = service.should_alert(snapshot, threshold)
    result2 = service.should_alert(snapshot, threshold)

    assert result1 == result2
