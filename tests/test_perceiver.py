"""Unit tests for MarketPerceiver.

Validates: Requirements 1.1, 1.2, 1.3, 1.6
"""

from __future__ import annotations

import textwrap
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import httpx
import pytest

from agent.models import PerceptionError, PriceRow
from agent.perceiver import MarketPerceiver, SMARDSnapshot


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

VALID_CSV = textwrap.dedent("""\
    timestamp,price_eur_mwh,region
    2024-01-15T00:00:00,42.50,DE
    2024-01-15T01:00:00,38.75,DE
    2024-01-15T02:00:00,35.20,DE
""")

INVALID_PRICE_CSV = textwrap.dedent("""\
    timestamp,price_eur_mwh,region
    2024-01-15T00:00:00,-5.00,DE
    2024-01-15T01:00:00,0.00,DE
""")

MIXED_CSV = textwrap.dedent("""\
    timestamp,price_eur_mwh,region
    2024-01-15T00:00:00,42.50,DE
    2024-01-15T01:00:00,-5.00,DE
    2024-01-15T02:00:00,35.20,DE
""")

MISSING_COLUMN_CSV = textwrap.dedent("""\
    timestamp,region
    2024-01-15T00:00:00,DE
""")


def write_csv(tmp_path, content: str, filename: str = "prices.csv"):
    p = tmp_path / filename
    p.write_text(content, encoding="utf-8")
    return str(p)


# ---------------------------------------------------------------------------
# read_csv_prices — valid input
# ---------------------------------------------------------------------------


def test_read_csv_prices_valid(tmp_path):
    """Test read_csv_prices with a valid CSV returns correct PriceRow list."""
    path = write_csv(tmp_path, VALID_CSV)
    perceiver = MarketPerceiver(csv_path=path)
    rows = perceiver.read_csv_prices(path)

    assert len(rows) == 3
    assert all(isinstance(r, PriceRow) for r in rows)
    assert rows[0].price_eur_mwh == 42.50
    assert rows[1].price_eur_mwh == 38.75
    assert rows[2].price_eur_mwh == 35.20
    assert all(r.region == "DE" for r in rows)


def test_read_csv_prices_default_region(tmp_path):
    """Test that region defaults to 'DE' when not provided."""
    csv_content = "timestamp,price_eur_mwh\n2024-01-15T00:00:00,42.50\n"
    path = write_csv(tmp_path, csv_content)
    perceiver = MarketPerceiver(csv_path=path)
    rows = perceiver.read_csv_prices(path)

    assert len(rows) == 1
    assert rows[0].region == "DE"


# ---------------------------------------------------------------------------
# read_csv_prices — invalid rows skipped
# ---------------------------------------------------------------------------


def test_read_csv_prices_skips_non_positive_prices(tmp_path):
    """Test read_csv_prices skips rows with non-positive prices."""
    path = write_csv(tmp_path, INVALID_PRICE_CSV)
    perceiver = MarketPerceiver(csv_path=path)
    rows = perceiver.read_csv_prices(path)

    assert len(rows) == 0  # both rows have non-positive prices


def test_read_csv_prices_skips_invalid_keeps_valid(tmp_path):
    """Test read_csv_prices skips invalid rows but keeps valid ones."""
    path = write_csv(tmp_path, MIXED_CSV)
    perceiver = MarketPerceiver(csv_path=path)
    rows = perceiver.read_csv_prices(path)

    assert len(rows) == 2
    assert rows[0].price_eur_mwh == 42.50
    assert rows[1].price_eur_mwh == 35.20


# ---------------------------------------------------------------------------
# read_csv_prices — error cases
# ---------------------------------------------------------------------------


def test_read_csv_prices_raises_on_missing_file():
    """Test read_csv_prices raises PerceptionError on missing file."""
    perceiver = MarketPerceiver()
    with pytest.raises(PerceptionError, match="not found"):
        perceiver.read_csv_prices("/nonexistent/path/prices.csv")


def test_read_csv_prices_raises_on_missing_columns(tmp_path):
    """Test read_csv_prices raises PerceptionError when required columns are missing."""
    path = write_csv(tmp_path, MISSING_COLUMN_CSV)
    perceiver = MarketPerceiver(csv_path=path)
    with pytest.raises(PerceptionError, match="missing required columns"):
        perceiver.read_csv_prices(path)


# ---------------------------------------------------------------------------
# fetch_smard_snapshot — retry and failure
# ---------------------------------------------------------------------------


def test_fetch_smard_snapshot_raises_after_3_retries():
    """Test fetch_smard_snapshot raises PerceptionError after 3 failed retries."""
    mock_client = MagicMock(spec=httpx.Client)
    mock_client.get.side_effect = httpx.ConnectError("Connection refused")

    perceiver = MarketPerceiver(http_client=mock_client)

    with patch("agent.perceiver.time.sleep"):  # don't actually sleep in tests
        with pytest.raises(PerceptionError, match="unreachable after 3 attempts"):
            perceiver.fetch_smard_snapshot()

    assert mock_client.get.call_count == 3


def test_fetch_smard_snapshot_raises_on_http_error():
    """Test fetch_smard_snapshot raises PerceptionError on HTTP 500 after retries.

    _do_fetch_smard calls _fetch_smard_series for demand first. If demand raises,
    _do_fetch_smard raises immediately (before calling wind). So 3 retries × 1 demand
    call = 3 total get() calls.
    """
    mock_response = MagicMock()
    mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "500 Server Error", request=MagicMock(), response=MagicMock()
    )
    mock_client = MagicMock(spec=httpx.Client)
    mock_client.get.return_value = mock_response

    perceiver = MarketPerceiver(http_client=mock_client)

    with patch("agent.perceiver.time.sleep"):
        with pytest.raises(PerceptionError, match="unreachable after 3 attempts"):
            perceiver.fetch_smard_snapshot()

    assert mock_client.get.call_count == 3  # demand fails each time, wind never called


def test_fetch_smard_snapshot_succeeds_on_valid_response():
    """Test fetch_smard_snapshot returns SMARDSnapshot on valid API response."""
    demand_response = MagicMock()
    demand_response.raise_for_status.return_value = None
    demand_response.json.return_value = {
        "series": [[1705276800000, 52000.0], [1705280400000, 51500.0]]
    }

    wind_response = MagicMock()
    wind_response.raise_for_status.return_value = None
    wind_response.json.return_value = {
        "series": [[1705276800000, 14000.0], [1705280400000, 14500.0]]
    }

    mock_client = MagicMock(spec=httpx.Client)
    mock_client.get.side_effect = [demand_response, wind_response]

    perceiver = MarketPerceiver(http_client=mock_client)
    snapshot = perceiver.fetch_smard_snapshot()

    assert isinstance(snapshot, SMARDSnapshot)
    assert snapshot.demand_mw == 51500.0
    assert snapshot.wind_production_mw == 14500.0


def test_fetch_smard_snapshot_skips_null_values():
    """Test fetch_smard_snapshot skips null values and uses the most recent non-null."""
    demand_response = MagicMock()
    demand_response.raise_for_status.return_value = None
    demand_response.json.return_value = {
        "series": [[1705276800000, 52000.0], [1705280400000, None]]
    }

    wind_response = MagicMock()
    wind_response.raise_for_status.return_value = None
    wind_response.json.return_value = {
        "series": [[1705276800000, 14000.0], [1705280400000, None]]
    }

    mock_client = MagicMock(spec=httpx.Client)
    mock_client.get.side_effect = [demand_response, wind_response]

    perceiver = MarketPerceiver(http_client=mock_client)
    snapshot = perceiver.fetch_smard_snapshot()

    assert snapshot.demand_mw == 52000.0  # falls back to previous non-null
    assert snapshot.wind_production_mw == 14000.0
