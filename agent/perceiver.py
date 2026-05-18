"""MarketPerceiver: reads electricity price, demand, and wind data from CSV and SMARD API."""

from __future__ import annotations

import csv
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx

from agent.models import MarketSnapshot, PerceptionError, PriceRow

logger = logging.getLogger(__name__)

# SMARD API constants — Germany (DE) indices
# Index 410 = Total grid load (demand), Index 4169 = Wind onshore production
SMARD_BASE_URL = "https://www.smard.de/app/chart_data"
SMARD_DEMAND_INDEX = 410
SMARD_WIND_INDEX = 4169
SMARD_RESOLUTION = "hour"
SMARD_REGION = "DE"

_MAX_RETRIES = 3
_BACKOFF_BASE = 1.0  # seconds


@dataclass
class SMARDSnapshot:
    """Raw data fetched from the SMARD API."""

    demand_mw: float
    wind_production_mw: float
    timestamp: datetime


class MarketPerceiver:
    """Reads and merges electricity market data from CSV and the SMARD API."""

    def __init__(
        self,
        csv_path: str = "data/fake_energy_prices.csv",
        smard_base_url: str = SMARD_BASE_URL,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.csv_path = csv_path
        self.smard_base_url = smard_base_url
        self._http_client = http_client

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def perceive(self) -> MarketSnapshot:
        """Read latest market data from all configured sources and merge into a MarketSnapshot.

        Returns:
            A fully validated MarketSnapshot.

        Raises:
            PerceptionError: If any data source is unavailable or malformed.
        """
        rows = self.read_csv_prices(self.csv_path)
        if not rows:
            raise PerceptionError(
                f"No valid price rows found in CSV file: {self.csv_path}"
            )

        # Use the most recent price row
        latest_row = max(rows, key=lambda r: r.timestamp)

        smard = self.fetch_smard_snapshot()

        return MarketSnapshot(
            timestamp=latest_row.timestamp,
            spot_price_eur_mwh=latest_row.price_eur_mwh,
            demand_mw=smard.demand_mw,
            wind_production_mw=smard.wind_production_mw,
        )

    def read_csv_prices(self, path: str) -> list[PriceRow]:
        """Parse a CSV file of electricity prices into validated PriceRow objects.

        Rows with invalid data (e.g. non-positive price) are skipped with a warning.

        Args:
            path: Path to the CSV file. Must have columns: timestamp, price_eur_mwh, region.

        Returns:
            List of valid PriceRow objects (may be empty if all rows are invalid).

        Raises:
            PerceptionError: If the file is not found or required columns are missing.
        """
        try:
            f = open(path, newline="", encoding="utf-8")
        except FileNotFoundError:
            raise PerceptionError(f"CSV file not found: {path}")

        rows: list[PriceRow] = []
        with f:
            reader = csv.DictReader(f)
            required_columns = {"timestamp", "price_eur_mwh"}
            if reader.fieldnames is None or not required_columns.issubset(
                set(reader.fieldnames)
            ):
                raise PerceptionError(
                    f"CSV file is missing required columns {required_columns}. "
                    f"Found: {reader.fieldnames}"
                )

            for raw_row in reader:
                # INVARIANT: all rows in `rows` are valid PriceRow instances
                try:
                    row = PriceRow.model_validate(raw_row)
                    rows.append(row)
                except Exception as exc:
                    logger.warning("Skipping invalid CSV row %s — %s", raw_row, exc)

        return rows

    def fetch_smard_snapshot(self) -> SMARDSnapshot:
        """Fetch current demand and wind production from the SMARD API.

        Retries up to _MAX_RETRIES times with exponential backoff.

        Returns:
            A SMARDSnapshot with demand_mw and wind_production_mw.

        Raises:
            PerceptionError: After exhausting all retry attempts.
        """
        last_exc: Exception | None = None

        for attempt in range(_MAX_RETRIES):
            try:
                return self._do_fetch_smard()
            except Exception as exc:
                last_exc = exc
                wait = _BACKOFF_BASE * (2 ** attempt)
                logger.warning(
                    "SMARD API attempt %d/%d failed: %s. Retrying in %.1fs…",
                    attempt + 1,
                    _MAX_RETRIES,
                    exc,
                    wait,
                )
                time.sleep(wait)

        raise PerceptionError(
            f"SMARD API unreachable after {_MAX_RETRIES} attempts: {last_exc}"
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _do_fetch_smard(self) -> SMARDSnapshot:
        """Single attempt to fetch data from the SMARD API.

        The SMARD API returns time-series data. We take the most recent
        non-null entry for demand and wind production.
        """
        client = self._http_client or httpx.Client(timeout=10.0)

        # Fetch demand
        demand_mw = self._fetch_smard_series(client, SMARD_DEMAND_INDEX)
        # Fetch wind onshore
        wind_mw = self._fetch_smard_series(client, SMARD_WIND_INDEX)

        return SMARDSnapshot(
            demand_mw=demand_mw,
            wind_production_mw=wind_mw,
            timestamp=datetime.now(tz=timezone.utc),
        )

    def _fetch_smard_series(self, client: httpx.Client, index: int) -> float:
        """Fetch the latest value for a single SMARD data series.

        SMARD API uses a two-step pattern:
          1. GET /chart_data/{index}/{region}/index_hour.json  → list of week timestamps
          2. GET /chart_data/{index}/{region}/{index}_{region}_hour_{ts}.json → series data

        Args:
            client: httpx.Client to use for the request.
            index: SMARD series index (e.g. 410 for demand).

        Returns:
            The most recent non-null value in MW.

        Raises:
            PerceptionError: If the response is malformed or contains no data.
        """
        base = self.smard_base_url  # e.g. https://www.smard.de/app/chart_data

        # Step 1: get the index of available weekly files
        index_url = f"{base}/{index}/{SMARD_REGION}/index_{SMARD_RESOLUTION}.json"
        resp = client.get(index_url)
        resp.raise_for_status()
        timestamps: list[int] = resp.json().get("timestamps", [])
        if not timestamps:
            raise PerceptionError(
                f"SMARD index for series {index} returned no timestamps"
            )

        # Step 2: fetch the most recent weekly data file
        latest_ts = timestamps[-1]
        data_url = (
            f"{base}/{index}/{SMARD_REGION}/"
            f"{index}_{SMARD_REGION}_{SMARD_RESOLUTION}_{latest_ts}.json"
        )
        resp2 = client.get(data_url)
        resp2.raise_for_status()
        series: list[list[Any]] = resp2.json().get("series", [])

        if not series:
            raise PerceptionError(
                f"SMARD data file for series {index} ts={latest_ts} is empty"
            )

        # Find the most recent non-null value
        for _ts, value in reversed(series):
            if value is not None:
                return float(value)

        raise PerceptionError(
            f"SMARD series {index} contains no non-null values in latest file"
        )
