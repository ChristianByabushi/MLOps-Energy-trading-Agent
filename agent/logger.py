"""DecisionLogger: serialises TradeDecision objects to JSON and uploads them to S3."""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from agent.models import LogEntry, StorageError, TradeDecision

logger = logging.getLogger(__name__)

_RETRY_WAIT = 1.0  # seconds to wait before retry
_TMP_DIR = Path("/tmp")


class DecisionLogger:
    """Persists TradeDecision objects as structured JSON logs in AWS S3.

    Falls back to /tmp on StorageError and emits a CloudWatch alarm.
    """

    def __init__(
        self,
        bucket_name: str | None = None,
        s3_client=None,
        aws_region: str = "eu-central-1",
    ) -> None:
        self.bucket_name = bucket_name or os.environ.get("S3_BUCKET_NAME", "trading-logs")
        self._s3_client = s3_client
        self.aws_region = aws_region

    @property
    def s3_client(self):
        """Lazy-initialise the boto3 S3 client."""
        if self._s3_client is None:
            self._s3_client = boto3.client("s3", region_name=self.aws_region)
        return self._s3_client

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build_s3_key(self, decision: TradeDecision) -> str:
        """Generate a deterministic S3 key for the given decision.

        Format: logs/YYYY-MM-DD/{uuid}.json

        Args:
            decision: The trade decision to generate a key for.

        Returns:
            S3 object key string.
        """
        date_str = decision.timestamp.strftime("%Y-%m-%d")
        return f"logs/{date_str}/{decision.id}.json"

    def log(self, decision: TradeDecision) -> LogEntry:
        """Serialise a TradeDecision to JSON and upload it to S3.

        Retries once on failure. If still failing, writes to /tmp as fallback
        and emits a CloudWatch alarm.

        Args:
            decision: The trade decision to log.

        Returns:
            LogEntry with the S3 key and upload timestamp.

        Raises:
            StorageError: If the S3 upload fails after one retry.
        """
        
        key = self.build_s3_key(decision)
        payload = decision.model_dump_json(indent=2)

        last_exc: Exception | None = None

        for attempt in range(2):  # try once, retry once
            try:
                self.s3_client.put_object(
                    Bucket=self.bucket_name,
                    Key=key,
                    Body=payload.encode("utf-8"),
                    ContentType="application/json",
                )
                uploaded_at = datetime.now(tz=timezone.utc)
                logger.info("Decision %s logged to s3://%s/%s", decision.id, self.bucket_name, key)
                return LogEntry(
                    s3_key=key,
                    decision_id=decision.id,
                    uploaded_at=uploaded_at,
                )
            except (BotoCoreError, ClientError, Exception) as exc:
                last_exc = exc
                if attempt == 0:
                    logger.warning(
                        "S3 upload attempt 1 failed for decision %s: %s. Retrying in %.1fs…",
                        decision.id,
                        exc,
                        _RETRY_WAIT,
                    )
                    time.sleep(_RETRY_WAIT)

        # Both attempts failed — write to /tmp as fallback
        self._write_tmp_fallback(decision, payload, key)
        raise StorageError(
            f"S3 upload failed after 1 retry for decision {decision.id}: {last_exc}"
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _write_tmp_fallback(
        self, decision: TradeDecision, payload: str, s3_key: str
    ) -> None:
        """Write the decision payload to /tmp as a fallback and emit a CloudWatch alarm.

        Args:
            decision: The trade decision that failed to upload.
            payload: JSON string of the decision.
            s3_key: The S3 key that was attempted.
        """
        try:
            tmp_file = _TMP_DIR / f"{decision.id}.json"
            tmp_file.write_text(payload, encoding="utf-8")
            logger.error(
                "StorageError: decision %s written to fallback %s. "
                "CloudWatch alarm: S3UploadFailure",
                decision.id,
                tmp_file,
            )
            # Emit a CloudWatch metric alarm (best-effort; non-fatal if it fails)
            self._emit_cloudwatch_alarm(str(decision.id))
        except Exception as exc:
            logger.error("Failed to write /tmp fallback for decision %s: %s", decision.id, exc)

    def _emit_cloudwatch_alarm(self, decision_id: str) -> None:
        """Emit a CloudWatch custom metric to signal an S3 upload failure.

        This is best-effort: failures are logged but not raised.
        """
        try:
            cw_client = boto3.client("cloudwatch", region_name=self.aws_region)
            cw_client.put_metric_data(
                Namespace="EnergyTradingAgent",
                MetricData=[
                    {
                        "MetricName": "S3UploadFailure",
                        "Value": 1.0,
                        "Unit": "Count",
                        "Dimensions": [
                            {"Name": "DecisionId", "Value": decision_id}
                        ],
                    }
                ],
            )
        except Exception as exc:
            logger.warning("Failed to emit CloudWatch alarm: %s", exc)
