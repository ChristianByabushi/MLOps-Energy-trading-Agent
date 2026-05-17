"""Property-based tests for MarketPerceiver.

Property 8: CSV Parsing Validity Invariant
**Validates: Requirements 1.1, 1.2**
"""

from __future__ import annotations

import csv
import io
import os
import tempfile

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from agent.models import PriceRow
from agent.perceiver import MarketPerceiver


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

positive_price = st.floats(min_value=0.01, max_value=1_000_000.0, allow_nan=False, allow_infinity=False)
non_positive_price = st.floats(max_value=0.0, allow_nan=False, allow_infinity=False)


def make_csv_content(rows: list[dict]) -> str:
    """Build a CSV string from a list of row dicts."""
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=["timestamp", "price_eur_mwh", "region"])
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()


# ---------------------------------------------------------------------------
# Property 8: CSV Parsing Validity Invariant
# **Validates: Requirements 1.1, 1.2**
# ---------------------------------------------------------------------------


@given(
    prices=st.lists(positive_price, min_size=1, max_size=20),
)
def test_csv_parsing_validity_invariant_all_valid(prices: list[float]) -> None:
    """Property 8: Every PriceRow returned by read_csv_prices satisfies all PriceRow constraints.

    When all rows have positive prices, all rows should be returned and valid.
    **Validates: Requirements 1.1, 1.2**
    """
    rows_data = [
        {"timestamp": "2024-01-15T12:00:00", "price_eur_mwh": str(p), "region": "DE"}
        for p in prices
    ]
    csv_content = make_csv_content(rows_data)

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".csv", encoding="utf-8", delete=False
    ) as f:
        f.write(csv_content)
        tmp_path = f.name

    try:
        perceiver = MarketPerceiver(csv_path=tmp_path)
        result = perceiver.read_csv_prices(tmp_path)

        # Every returned row must satisfy PriceRow constraints
        for row in result:
            assert isinstance(row, PriceRow)
            assert row.price_eur_mwh > 0
            assert row.region == "DE"

        # All valid rows should be returned
        assert len(result) == len(prices)
    finally:
        os.unlink(tmp_path)


@given(
    valid_prices=st.lists(positive_price, min_size=1, max_size=10),
    invalid_prices=st.lists(non_positive_price, min_size=1, max_size=10),
)
def test_csv_parsing_validity_invariant_mixed(
    valid_prices: list[float],
    invalid_prices: list[float],
) -> None:
    """Property 8: No invalid row appears in the returned list.

    When rows contain a mix of valid and invalid prices, only valid rows are returned.
    **Validates: Requirements 1.1, 1.2**
    """
    valid_rows = [
        {"timestamp": "2024-01-15T12:00:00", "price_eur_mwh": str(p), "region": "DE"}
        for p in valid_prices
    ]
    invalid_rows = [
        {"timestamp": "2024-01-15T12:00:00", "price_eur_mwh": str(p), "region": "DE"}
        for p in invalid_prices
    ]
    # Interleave valid and invalid rows
    all_rows = valid_rows + invalid_rows
    csv_content = make_csv_content(all_rows)

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".csv", encoding="utf-8", delete=False
    ) as f:
        f.write(csv_content)
        tmp_path = f.name

    try:
        perceiver = MarketPerceiver(csv_path=tmp_path)
        result = perceiver.read_csv_prices(tmp_path)

        # No invalid row should appear in the result
        for row in result:
            assert isinstance(row, PriceRow)
            assert row.price_eur_mwh > 0

        # Exactly the valid rows should be returned
        assert len(result) == len(valid_prices)
    finally:
        os.unlink(tmp_path)
