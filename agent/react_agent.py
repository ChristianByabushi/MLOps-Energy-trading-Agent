"""ReActAgent: orchestrates the perceive → reason → act cycle using PydanticAI."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

import openai
from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from agent.alert import AlertService
from agent.config import AgentConfig
from agent.dispatcher import ActionDispatcher
from agent.logger import DecisionLogger
from agent.models import (
    ActionType,
    AgentRunResult,
    MarketSnapshot,
    PerceptionError,
    TradeDecision,
    TradeSignal,
)
from agent.perceiver import MarketPerceiver

logger = logging.getLogger(__name__)

_MAX_LLM_RETRIES = 3

# Fallback decision used when LLM validation fails after all retries
_FALLBACK_DECISION_KWARGS = {
    "action": ActionType.LOG,
    "signal": TradeSignal.HOLD,
    "rationale": "Validation failed after retries",
    "confidence": 0.0,
}


class ReActAgent:
    """Orchestrates the ReAct (Reason + Act) loop for energy trading decisions.

    Executes one full perceive → reason → act cycle per invocation.
    """

    def __init__(
        self,
        config: AgentConfig | None = None,
        perceiver: MarketPerceiver | None = None,
        dispatcher: ActionDispatcher | None = None,
        pydantic_agent: Agent | None = None,
    ) -> None:
        self.config = config or AgentConfig()
        self.perceiver = perceiver or MarketPerceiver(csv_path=self.config.csv_path)

        # Build a fully-configured AlertService and DecisionLogger from config
        # so SMTP credentials, S3 bucket, etc. are all wired in automatically.
        if dispatcher is None:
            alert_service = AlertService(
                slack_webhook_url=self.config.slack_webhook_url,
                smtp_host=self.config.smtp_host,
                smtp_port=self.config.smtp_port,
                smtp_user=self.config.smtp_user,
                smtp_password=self.config.smtp_password,
                alert_email_to=self.config.alert_email_to,
            )
            decision_logger = DecisionLogger(
                bucket_name=self.config.s3_bucket_name,
                aws_region=self.config.aws_region,
                aws_access_key_id=self.config.aws_access_key_id,
                aws_secret_access_key=self.config.aws_secret_access_key,
            )
            dispatcher = ActionDispatcher(
                decision_logger=decision_logger,
                alert_service=alert_service,
                alert_threshold=self.config.alert_threshold,
            )
        self.dispatcher = dispatcher
        self._pydantic_agent = pydantic_agent

    @property
    def agent(self) -> Agent:
        """Lazy-initialise the PydanticAI Agent."""
        if self._pydantic_agent is None:
            # OpenAIProvider accepts base_url + api_key directly, or a
            # pre-built AsyncOpenAI client — works with any OpenAI-compatible
            # gateway such as the CMU AI Gateway.
            provider_kwargs: dict = {
                "api_key": self.config.openai_api_key or "sk-placeholder",
            }
            if self.config.openai_base_url:
                provider_kwargs["base_url"] = self.config.openai_base_url

            provider = OpenAIProvider(**provider_kwargs)
            model = OpenAIChatModel(self.config.openai_model, provider=provider)

            self._pydantic_agent = Agent(
                model=model,
                output_type=TradeDecision,
                instructions=(
                    "You are an energy trading analyst. "
                    "Given market data, reason about price stability and return a structured "
                    "trade decision as JSON. "
                    "Consider demand, wind production, and current spot price. "
                    "Your response must be a valid TradeDecision with: "
                    "action (LOG/TRADE/ALERT), signal (BUY/SELL/HOLD), "
                    "rationale (at least 10 characters), and confidence (0.0-1.0)."
                ),
            )
        return self._pydantic_agent

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run_cycle(self) -> AgentRunResult:
        """Execute one full perceive → reason → act cycle.

        Returns:
            AgentRunResult with decision, log entry, and action flags.

        Raises:
            PerceptionError: If the perceive step fails (propagated to Lambda handler).
        """
        started_at = datetime.now(tz=timezone.utc)

        # Step 1: Perceive — raises PerceptionError on failure (propagated)
        snapshot: MarketSnapshot = self.perceiver.perceive()
        logger.info(
            "Perceived market snapshot: price=%.2f, demand=%.0f, wind=%.0f",
            snapshot.spot_price_eur_mwh,
            snapshot.demand_mw,
            snapshot.wind_production_mw,
        )

        # Step 2: Reason — LLM call with retry logic
        decision = await self._reason(snapshot)

        # Step 3: Act — dispatch the decision
        action_result = self.dispatcher.dispatch(decision)

        completed_at = datetime.now(tz=timezone.utc)

        return AgentRunResult(
            started_at=started_at,
            completed_at=completed_at,
            decision=decision,
            log_entry=action_result.log_entry,
            alert_sent=action_result.alert_sent,
            trade_executed=action_result.trade_executed,
        )

    def build_prompt(self, snapshot: MarketSnapshot) -> str:
        """Construct the reasoning prompt from a market snapshot.

        Includes all numeric fields from the snapshot.

        Args:
            snapshot: The current market snapshot.

        Returns:
            A non-empty prompt string for the LLM.
        """
        return (
            f"Current energy market data for Germany:\n"
            f"- Spot price: {snapshot.spot_price_eur_mwh:.4f} EUR/MWh\n"
            f"- Electricity demand: {snapshot.demand_mw:.4f} MW\n"
            f"- Wind production: {snapshot.wind_production_mw:.4f} MW\n"
            f"- Wind ratio (wind/demand): {snapshot.wind_ratio:.4f}\n"
            f"- Timestamp: {snapshot.timestamp.isoformat()}\n\n"
            f"Based on this data, provide a structured trade decision. "
            f"Consider whether the price is stable, rising, or falling, "
            f"and whether wind production is high or low relative to demand."
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _reason(self, snapshot: MarketSnapshot) -> TradeDecision:
        """Run the LLM reasoning step with retry logic.

        Retries up to _MAX_LLM_RETRIES times on validation failure.
        Falls back to a default decision after exhausting retries.

        Args:
            snapshot: The current market snapshot.

        Returns:
            A validated TradeDecision.
        """
        prompt = self.build_prompt(snapshot)
        last_error: Exception | None = None

        for attempt in range(_MAX_LLM_RETRIES):
            try:
                result = await self.agent.run(prompt)
                decision: TradeDecision = result.output
                # Inject the snapshot into the decision (LLM may not include it)
                if decision.snapshot is None or decision.snapshot != snapshot:
                    decision = decision.model_copy(update={"snapshot": snapshot})
                logger.info(
                    "LLM decision on attempt %d: action=%s, signal=%s, confidence=%.2f",
                    attempt + 1,
                    decision.action,
                    decision.signal,
                    decision.confidence,
                )
                return decision
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "LLM reasoning attempt %d/%d failed: %s",
                    attempt + 1,
                    _MAX_LLM_RETRIES,
                    exc,
                )

        # All retries exhausted — use fallback decision
        logger.error(
            "LLM reasoning failed after %d attempts. Using fallback decision. Last error: %s",
            _MAX_LLM_RETRIES,
            last_error,
        )
        return TradeDecision(
            timestamp=datetime.now(tz=timezone.utc),
            snapshot=snapshot,
            **_FALLBACK_DECISION_KWARGS,
        )
