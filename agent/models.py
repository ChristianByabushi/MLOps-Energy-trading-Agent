"""Core data models for the MLOps Energy Trading Agent."""

from __future__ import annotations

import logging
from datetime import datetime
from enum import Enum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, model_validator

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class ActionType(str, Enum):
    """Possible action types the agent can decide on."""

    LOG = "LOG"
    TRADE = "TRADE"
    ALERT = "ALERT"


class TradeSignal(str, Enum):
    """Trading signals the agent can emit."""

    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


# ---------------------------------------------------------------------------
# Market data models
# ---------------------------------------------------------------------------


class PriceRow(BaseModel):
    """A single row of electricity price data from the CSV feed."""

    timestamp: datetime
    price_eur_mwh: float = Field(gt=0, description="Spot price in EUR/MWh, must be positive")
    region: str = Field(default="DE", description="Market region, defaults to Germany")


class MarketSnapshot(BaseModel):
    """Merged market state: price, demand, wind production, and derived wind ratio."""

    timestamp: datetime
    spot_price_eur_mwh: float = Field(gt=0, description="Current spot price in EUR/MWh")
    demand_mw: float = Field(gt=0, description="Current electricity demand in MW")
    wind_production_mw: float = Field(ge=0, description="Current wind production in MW")
    wind_ratio: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Wind production as a fraction of demand (auto-computed)",
    )

    @model_validator(mode="after")
    def compute_wind_ratio(self) -> "MarketSnapshot":
        """Auto-compute wind_ratio = wind_production_mw / demand_mw, clamped to [0, 1]."""
        ratio = self.wind_production_mw / self.demand_mw
        self.wind_ratio = max(0.0, min(1.0, ratio))
        return self


# ---------------------------------------------------------------------------
# Decision models
# ---------------------------------------------------------------------------


class TradeDecision(BaseModel):
    """Structured trade decision produced by the LLM reasoning step."""

    id: UUID = Field(default_factory=uuid4, description="Unique decision identifier (UUID4)")
    timestamp: datetime = Field(description="When the decision was made")
    snapshot: MarketSnapshot = Field(description="Market snapshot that drove this decision")
    action: ActionType = Field(description="Action to take: LOG, TRADE, or ALERT")
    signal: TradeSignal = Field(description="Trading signal: BUY, SELL, or HOLD")
    rationale: str = Field(
        min_length=10,
        description="LLM reasoning explanation (at least 10 characters)",
    )
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence score in [0.0, 1.0]")


# ---------------------------------------------------------------------------
# Result / output models
# ---------------------------------------------------------------------------


class LogEntry(BaseModel):
    """Record of a successful S3 upload."""

    s3_key: str = Field(description="S3 object key where the decision was stored")
    decision_id: UUID = Field(description="ID of the decision that was logged")
    uploaded_at: datetime = Field(description="Timestamp of the successful upload")


class AlertMessage(BaseModel):
    """Structured message sent to Slack or Email when a price threshold is breached."""

    subject: str = Field(description="Alert subject line")
    body: str = Field(description="Alert body text")
    snapshot: MarketSnapshot = Field(description="Market snapshot that triggered the alert")
    threshold: float = Field(description="The price threshold that was breached")
    channel: str = Field(description="Delivery channel: 'slack' or 'email'")


class ActionResult(BaseModel):
    """Reflects which actions were taken during a single dispatch call."""

    logged: bool = Field(default=False, description="Whether the decision was logged to S3")
    trade_executed: bool = Field(default=False, description="Whether a mock trade was executed")
    alert_sent: bool = Field(default=False, description="Whether an alert was sent")
    log_entry: LogEntry | None = Field(default=None, description="The log entry if logging succeeded")


class AgentRunResult(BaseModel):
    """Outcome of a single agent perceive → reason → act cycle."""

    run_id: UUID = Field(default_factory=uuid4, description="Unique run identifier")
    started_at: datetime = Field(description="When the cycle started")
    completed_at: datetime = Field(description="When the cycle completed")
    decision: TradeDecision = Field(description="The trade decision produced")
    log_entry: LogEntry | None = Field(default=None, description="S3 log entry if logging succeeded")
    alert_sent: bool = Field(default=False, description="Whether an alert was sent")
    trade_executed: bool = Field(default=False, description="Whether a mock trade was executed")
    error: str | None = Field(default=None, description="Error message if the cycle failed")


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class PerceptionError(Exception):
    """Raised when a data source is unavailable or malformed."""


class StorageError(Exception):
    """Raised when an S3 upload fails after retries."""
