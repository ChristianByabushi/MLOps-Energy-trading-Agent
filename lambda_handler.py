"""AWS Lambda entry point for the MLOps Energy Trading Agent."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from agent.config import AgentConfig
from agent.react_agent import ReActAgent

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """AWS Lambda handler for the energy trading agent.

    Executes one full ReActAgent cycle per invocation.

    Args:
        event: Lambda event payload (not used by the agent directly).
        context: Lambda context object (not used by the agent directly).

    Returns:
        HTTP-style response dict with statusCode and body.
        - 200: AgentRunResult serialised as JSON on success.
        - 500: Error message on unhandled exception.
    """
    try:
        config = AgentConfig.from_env()
        agent = ReActAgent(config=config)
        result = asyncio.run(agent.run_cycle())

        return {
            "statusCode": 200,
            "body": json.loads(result.model_dump_json()),
        }

    except Exception as exc:
        logger.error("Unhandled exception in Lambda handler: %s", exc, exc_info=True)
        return {
            "statusCode": 500,
            "body": {"error": str(exc)},
        }
