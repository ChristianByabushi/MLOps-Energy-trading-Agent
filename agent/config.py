"""Agent configuration loaded from environment variables."""

from __future__ import annotations

import os

from pydantic import Field
from pydantic_settings import BaseSettings


class AgentConfig(BaseSettings):
    """All runtime configuration for the energy trading agent.

    Values are read from environment variables (case-insensitive).
    Use ``AgentConfig.from_env()`` as the canonical factory in production.
    """

    # Data sources
    csv_path: str = Field(
        default="data/fake_energy_prices.csv",
        description="Path to the CSV price feed file",
    )
    smard_api_url: str = Field(
        default="https://www.smard.de/app/chart_data",
        description="Base URL for the SMARD API",
    )

    # AWS / S3
    s3_bucket_name: str = Field(
        default="trading-logs",
        description="S3 bucket name for decision logs",
    )
    app_aws_region: str = Field(
        default="us-east-1",
        description="AWS region (use APP_AWS_REGION — AWS_REGION is reserved by Lambda)",
    )
    aws_access_key_id: str = Field(
        default="",
        description="AWS access key ID (leave empty to use IAM role in Lambda)",
    )
    aws_secret_access_key: str = Field(
        default="",
        description="AWS secret access key (leave empty to use IAM role in Lambda)",
    )

    # Alerting
    alert_threshold: float = Field(
        default=50.0,
        description="Price threshold in EUR/MWh below which alerts are sent",
    )

    slack_webhook_url: str = Field(
        default="",
        description="Slack incoming webhook URL (empty = disabled)",
    )
    alert_email_to: str = Field(
        default="",
        description="Recipient email address for alerts (empty = disabled)",
    )
    smtp_host: str = Field(default="", description="SMTP server hostname")
    smtp_port: int = Field(default=587, description="SMTP server port")
    smtp_user: str = Field(default="", description="SMTP username")
    smtp_password: str = Field(default="", description="SMTP password")

    # LLM
    openai_api_key: str = Field(
        default="",
        description="OpenAI API key for the LLM reasoning step",
    )
    openai_model: str = Field(
        default="gpt-4.1-mini",
        description="OpenAI model name",
    )
    openai_base_url: str = Field(
        default="",
        description=(
            "Custom OpenAI-compatible base URL (e.g. CMU AI Gateway). "
            "Leave empty to use the default OpenAI endpoint."
        ),
    )

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}

    @classmethod
    def from_env(cls) -> "AgentConfig":
        """Create an AgentConfig by reading all values from environment variables."""
        return cls()
