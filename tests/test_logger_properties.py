"""Property-based tests for DecisionLogger.

Property 4: Decision Always Logged
Property 5: S3 Key Determinism
**Validates: Requirements 5.1, 6.3**
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from uuid import uuid4

import boto3
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from moto import mock_aws

from agent.logger import DecisionLogger
from agent.models import (
    ActionType,
    LogEntry,
    MarketSnapshot,
    TradeDecision,
    TradeSignal,
)

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

BUCKET_NAME = "test-trading-logs"
AWS_REGION = "eu-central-1"

positive_float = st.floats(min_value=0.01, max_value=1_000_000.0, allow_nan=False, allow_infinity=False)
rationale_str = st.text(min_size=10, max_size=200)
confidence_float = st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)


def build_snapshot(price: float = 65.0, demand: float = 50000.0, wind: float = 15000.0) -> MarketSnapshot:
    return MarketSnapshot(
        timestamp=datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc),
        spot_price_eur_mwh=price,
        demand_mw=demand,
        wind_production_mw=wind,
    )


def setup_aws_env():
    """Set up mocked AWS credentials."""
    os.environ["AWS_ACCESS_KEY_ID"] = "testing"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
    os.environ["AWS_SECURITY_TOKEN"] = "testing"
    os.environ["AWS_SESSION_TOKEN"] = "testing"
    os.environ["AWS_DEFAULT_REGION"] = AWS_REGION


# ---------------------------------------------------------------------------
# Property 5: S3 Key Determinism
# **Validates: Requirements 6.3**
# ---------------------------------------------------------------------------


@given(
    rationale=rationale_str,
    confidence=confidence_float,
    action=st.sampled_from(list(ActionType)),
    signal=st.sampled_from(list(TradeSignal)),
)
def test_s3_key_determinism(
    rationale: str,
    confidence: float,
    action: ActionType,
    signal: TradeSignal,
) -> None:
    """Property 5: build_s3_key(d) returns the identical string on every call.

    The key is a pure function of the decision's timestamp and id.
    **Validates: Requirements 6.3**
    """
    snapshot = build_snapshot()
    decision = TradeDecision(
        timestamp=datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc),
        snapshot=snapshot,
        action=action,
        signal=signal,
        rationale=rationale,
        confidence=confidence,
    )

    logger_svc = DecisionLogger(bucket_name=BUCKET_NAME)

    key1 = logger_svc.build_s3_key(decision)
    key2 = logger_svc.build_s3_key(decision)
    key3 = logger_svc.build_s3_key(decision)

    assert key1 == key2 == key3
    assert key1.startswith("logs/2024-01-15/")
    assert key1.endswith(".json")
    assert str(decision.id) in key1


# ---------------------------------------------------------------------------
# Property 4: Decision Always Logged
# **Validates: Requirements 5.1**
# ---------------------------------------------------------------------------


@settings(deadline=None)
@given(
    rationale=rationale_str,
    confidence=confidence_float,
    action=st.sampled_from(list(ActionType)),
    signal=st.sampled_from(list(TradeSignal)),
)
def test_decision_always_logged(
    rationale: str,
    confidence: float,
    action: ActionType,
    signal: TradeSignal,
) -> None:
    """Property 4: log(d) always produces a LogEntry for any valid TradeDecision.

    **Validates: Requirements 5.1**
    """
    setup_aws_env()

    with mock_aws():
        s3 = boto3.client("s3", region_name=AWS_REGION)
        s3.create_bucket(
            Bucket=BUCKET_NAME,
            CreateBucketConfiguration={"LocationConstraint": AWS_REGION},
        )

        snapshot = build_snapshot()
        decision = TradeDecision(
            timestamp=datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc),
            snapshot=snapshot,
            action=action,
            signal=signal,
            rationale=rationale,
            confidence=confidence,
        )

        logger_svc = DecisionLogger(bucket_name=BUCKET_NAME, s3_client=s3)
        entry = logger_svc.log(decision)

        assert isinstance(entry, LogEntry)
        assert entry.decision_id == decision.id
        assert entry.s3_key == logger_svc.build_s3_key(decision)
        assert entry.uploaded_at is not None
