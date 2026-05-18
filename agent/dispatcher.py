"""ActionDispatcher: routes TradeDecision to the correct action handlers."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from agent.alert import AlertService
from agent.logger import DecisionLogger
from agent.models import (
    ActionResult,
    ActionType,
    AlertMessage,
    MarketSnapshot,
    TradeDecision,
    TradeSignal,
)

logger = logging.getLogger(__name__)


@dataclass
class TradeResult:
    """Result of a mock trade execution."""

    signal: TradeSignal
    executed_at: datetime
    status: str = "mock_executed"
    order_id: str = "MOCK-ORDER-001"


class ActionDispatcher:
    """Routes a TradeDecision to the correct action handlers.

    Logging is unconditional — every decision is always logged regardless of action type.
    Trading and alerting are conditional on the decision's action type.
    """

    def __init__(
        self,
        decision_logger: DecisionLogger | None = None,
        alert_service: AlertService | None = None,
        alert_threshold: float = 50.0,
    ) -> None:
        self.decision_logger = decision_logger or DecisionLogger()
        self.alert_service = alert_service or AlertService()
        self.alert_threshold = alert_threshold

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def dispatch(self, decision: TradeDecision) -> ActionResult:
        """Route a TradeDecision to the appropriate action handlers.

        Logging is unconditional.
        Price-threshold alerting is unconditional — fires whenever
        spot_price < alert_threshold regardless of the LLM's action choice.
        Trading is conditional on the LLM choosing ActionType.TRADE.

        Args:
            decision: The trade decision to dispatch.

        Returns:
            ActionResult reflecting which actions were taken.
        """
        result = ActionResult()

        # Step 1: Always log the decision (unconditional)
        try:
            log_entry = self.decision_logger.log(decision)
            result.logged = True
            result.log_entry = log_entry
            logger.info("Decision %s logged successfully.", decision.id)
        except Exception as exc:
            logger.error("Failed to log decision %s: %s", decision.id, exc)
            result.logged = False

        # Step 2: Price-threshold alert — fires unconditionally when price < threshold
        # This is independent of the LLM's action choice.
        if self.alert_service.should_alert(decision.snapshot, self.alert_threshold):
            logger.info(
                "Price %.2f < threshold %.2f — sending alert email.",
                decision.snapshot.spot_price_eur_mwh,
                self.alert_threshold,
            )
            self.trigger_alert(decision.snapshot, decision.rationale)
            result.alert_sent = True

        # Step 3: Execute mock trade only when LLM explicitly chose TRADE
        if decision.action == ActionType.TRADE:
            trade_result = self.execute_mock_trade(decision.signal)
            result.trade_executed = True
            logger.info(
                "Mock trade executed for decision %s: signal=%s, order_id=%s",
                decision.id,
                trade_result.signal,
                trade_result.order_id,
            )

        return result

    def execute_mock_trade(self, signal: TradeSignal) -> TradeResult:
        """Execute a mock trade via a stub (no real API call).

        Args:
            signal: The trading signal (BUY, SELL, or HOLD).

        Returns:
            A TradeResult with mock execution details.
        """
        logger.info("Executing mock trade with signal: %s", signal)
        return TradeResult(
            signal=signal,
            executed_at=datetime.now(tz=timezone.utc),
            status="mock_executed",
            order_id=f"MOCK-{signal.value}-{datetime.now(tz=timezone.utc).strftime('%Y%m%d%H%M%S')}",
        )

    def trigger_alert(self, snapshot: MarketSnapshot, reason: str) -> None:
        """Send a Slack or Email alert for a threshold breach or agent decision.

        Args:
            snapshot: The market snapshot that triggered the alert.
            reason: The reason for the alert (from the decision's rationale).
        """
        message = AlertMessage(
            subject=f"⚡ Energy Trading Alert: {snapshot.spot_price_eur_mwh:.2f} EUR/MWh",
            body=(
                f"Alert triggered by agent decision.\n"
                f"Reason: {reason}\n"
                f"Current: {snapshot.spot_price_eur_mwh:.2f} EUR/MWh\n"
                f"Demand: {snapshot.demand_mw:.0f} MW | "
                f"Wind: {snapshot.wind_production_mw:.0f} MW"
            ),
            snapshot=snapshot,
            threshold=self.alert_threshold,
            channel="slack",
        )
        self.alert_service.send_slack(message)
        # Also send email if configured (channel field is informational only)
        message_email = message.model_copy(update={"channel": "email"})
        self.alert_service.send_email(message_email)
