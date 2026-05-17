"""Unit tests for DecisionLogger.

Validates: Requirements 6.2, 6.3, 6.4, 6.5, 9.2, 9.3
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import UUID

import boto3
import pytest
from moto import mock_aws

from agent.logger import DecisionLogger
from agent.models import (
    ActionType,
    LogEntry,
    MarketSnapshot,
    StorageError,
    TradeDecision,
    TradeSignal,
)


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

BUCKET_NAME = "test-trading-logs"
AWS_REGION = "eu-central-1"


@pytest.fixture
def sample_snapshot() -> MarketSnapshot:
    return MarketSnapshot(
        timestamp=datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc),
        spot_price_eur_mwh=65.40,
        demand_mw=50000.0,
        wind_production_mw=15000.0,
    )


@pytest.fixture
def sample_decision(sample_snapshot: MarketSnapshot) -> TradeDecision:
    return TradeDecision(
        timestamp=datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc),
        snapshot=sample_snapshot,
        action=ActionType.LOG,
        signal=TradeSignal.HOLD,
        rationale="Market conditions are stable, holding position.",
        confidence=0.75,
    )


@pytest.fixture
def aws_credentials():
    """Mocked AWS credentials for moto."""
    os.environ["AWS_ACCESS_KEY_ID"] = "testing"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
    os.environ["AWS_SECURITY_TOKEN"] = "testing"
    os.environ["AWS_SESSION_TOKEN"] = "testing"
    os.environ["AWS_DEFAULT_REGION"] = AWS_REGION
    yield
    for key in ["AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SECURITY_TOKEN",
                "AWS_SESSION_TOKEN", "AWS_DEFAULT_REGION"]:
        os.environ.pop(key, None)


@pytest.fixture
def s3_bucket(aws_credentials):
    """Create a mocked S3 bucket using moto."""
    with mock_aws():
        s3 = boto3.client("s3", region_name=AWS_REGION)
        s3.create_bucket(
            Bucket=BUCKET_NAME,
            CreateBucketConfiguration={"LocationConstraint": AWS_REGION},
        )
        yield s3


# ---------------------------------------------------------------------------
# build_s3_key
# ---------------------------------------------------------------------------


def test_build_s3_key_format(sample_decision: TradeDecision):
    """Test build_s3_key returns the correct format: logs/YYYY-MM-DD/{uuid}.json"""
    logger_svc = DecisionLogger(bucket_name=BUCKET_NAME)
    key = logger_svc.build_s3_key(sample_decision)

    assert key == f"logs/2024-01-15/{sample_decision.id}.json"
    assert key.startswith("logs/")
    assert key.endswith(".json")


def test_build_s3_key_is_deterministic(sample_decision: TradeDecision):
    """Test build_s3_key returns the same key on every call for the same decision."""
    logger_svc = DecisionLogger(bucket_name=BUCKET_NAME)

    key1 = logger_svc.build_s3_key(sample_decision)
    key2 = logger_svc.build_s3_key(sample_decision)
    key3 = logger_svc.build_s3_key(sample_decision)

    assert key1 == key2 == key3


def test_build_s3_key_uses_decision_timestamp(sample_snapshot: MarketSnapshot):
    """Test build_s3_key uses the decision's timestamp for the date component."""
    decision = TradeDecision(
        timestamp=datetime(2025, 6, 20, 8, 30, 0, tzinfo=timezone.utc),
        snapshot=sample_snapshot,
        action=ActionType.TRADE,
        signal=TradeSignal.BUY,
        rationale="Strong buy signal detected in market data.",
        confidence=0.85,
    )
    logger_svc = DecisionLogger(bucket_name=BUCKET_NAME)
    key = logger_svc.build_s3_key(decision)

    assert "2025-06-20" in key
    assert str(decision.id) in key


# ---------------------------------------------------------------------------
# log — success (moto S3)
# ---------------------------------------------------------------------------


def test_log_uploads_json_to_s3(s3_bucket, sample_decision: TradeDecision):
    """Test log uploads JSON to S3 and returns a LogEntry (using moto)."""
    # s3_bucket fixture already provides a mocked S3 client with the bucket created
    logger_svc = DecisionLogger(bucket_name=BUCKET_NAME, s3_client=s3_bucket)
    entry = logger_svc.log(sample_decision)

    assert isinstance(entry, LogEntry)
    assert entry.s3_key == logger_svc.build_s3_key(sample_decision)
    assert entry.decision_id == sample_decision.id
    assert entry.uploaded_at is not None

    # Verify the object was actually uploaded
    obj = s3_bucket.get_object(Bucket=BUCKET_NAME, Key=entry.s3_key)
    content = json.loads(obj["Body"].read().decode("utf-8"))
    assert str(content["id"]) == str(sample_decision.id)


def test_log_returns_log_entry_with_correct_s3_key(s3_bucket, sample_decision: TradeDecision):
    """Test log returns a LogEntry with the correct S3 key."""
    # s3_bucket fixture already provides a mocked S3 client with the bucket created
    logger_svc = DecisionLogger(bucket_name=BUCKET_NAME, s3_client=s3_bucket)
    entry = logger_svc.log(sample_decision)

    expected_key = f"logs/2024-01-15/{sample_decision.id}.json"
    assert entry.s3_key == expected_key


# ---------------------------------------------------------------------------
# log — failure (raises StorageError after retry)
# ---------------------------------------------------------------------------


def test_log_raises_storage_error_after_one_retry(sample_decision: TradeDecision):
    """Test log raises StorageError after one retry on S3 failure."""
    mock_s3 = MagicMock()
    mock_s3.put_object.side_effect = Exception("S3 connection timeout")

    logger_svc = DecisionLogger(bucket_name=BUCKET_NAME, s3_client=mock_s3)

    with patch("agent.logger.time.sleep"):
        with patch.object(logger_svc, "_emit_cloudwatch_alarm"):
            with pytest.raises(StorageError, match="S3 upload failed after 1 retry"):
                logger_svc.log(sample_decision)

    assert mock_s3.put_object.call_count == 2  # initial + 1 retry


def test_log_writes_tmp_fallback_on_storage_error(sample_decision: TradeDecision, tmp_path):
    """Test log writes to /tmp as fallback when StorageError is raised."""
    mock_s3 = MagicMock()
    mock_s3.put_object.side_effect = Exception("S3 connection timeout")

    logger_svc = DecisionLogger(bucket_name=BUCKET_NAME, s3_client=mock_s3)

    with patch("agent.logger.time.sleep"):
        with patch("agent.logger._TMP_DIR", tmp_path):
            with patch.object(logger_svc, "_emit_cloudwatch_alarm"):
                with pytest.raises(StorageError):
                    logger_svc.log(sample_decision)

    # Verify the fallback file was written
    fallback_file = tmp_path / f"{sample_decision.id}.json"
    assert fallback_file.exists()
    content = json.loads(fallback_file.read_text(encoding="utf-8"))
    assert str(content["id"]) == str(sample_decision.id)
