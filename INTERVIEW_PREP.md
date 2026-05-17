# Interview Preparation — MLOps Energy Trading Agent

## What is this project?

An **agentic AI pipeline** that monitors the German electricity market in real time, reasons about price stability using an LLM, and autonomously decides whether to log, trade, or alert — all deployed on AWS Lambda and managed with Terraform.

The core loop follows the **ReAct pattern** (Reason + Act): the agent perceives market data, reasons about it with an LLM, then dispatches the right action.

---

## The Idea

The internship description asked for *scalable, maintainable MLOps data pipelines for energy trading*. Instead of a passive pipeline that just moves data, I built an **active agent** that:

1. Pulls live electricity data (spot prices from CSV, demand + wind production from the German SMARD API)
2. Feeds it to an LLM (GPT-4o-mini via PydanticAI) to reason about market conditions
3. Produces a structured, validated decision: **LOG**, **TRADE**, or **ALERT**
4. Dispatches the decision to the right handler — S3 logging, mock trade execution, or Slack/Email alert

This maps directly to what a real energy trading desk needs: automated monitoring, structured decision records, and real-time alerts when prices move.

---

## Architecture Overview

```
EventBridge / HTTP trigger
        │
        ▼
  Lambda Handler
        │
        ▼
   ReActAgent
  ┌─────┴──────┐
  │            │
Perceive     Reason (LLM)
  │            │
  ▼            ▼
MarketPerceiver → MarketSnapshot → TradeDecision
  │                                     │
  ├── CSV (spot prices)                 ▼
  └── SMARD API (demand, wind)    ActionDispatcher
                                  ┌────┼────┐
                                  │    │    │
                                 LOG TRADE ALERT
                                  │    │    │
                                  S3  Mock Slack/
                                      API  Email
```

---

## Technology Choices — and Why

### Python 3.12
The standard for data/ML work. Async support (`asyncio`) is needed for the LLM call. Type hints throughout make the codebase self-documenting and catch bugs early.

### PydanticAI
A newer framework that wraps LLM calls and enforces **structured output** via Pydantic models. Instead of parsing free-text from the LLM, the agent gets a validated `TradeDecision` object back directly. This is critical for a trading system — you cannot act on unvalidated LLM output.

### Pydantic v2
Every piece of data that enters the system — CSV rows, API responses, LLM decisions — is validated through a Pydantic model before use. This is the first line of defence against bad data causing bad trades.

### AWS Lambda
Serverless execution fits the use case perfectly: the agent runs on a schedule (e.g., every hour via EventBridge), costs nothing when idle, and scales automatically. No server to manage.

### AWS S3
Every trade decision is persisted as a structured JSON log at `logs/YYYY-MM-DD/{uuid}.json`. This gives a full audit trail for compliance and model evaluation — a core MLOps requirement.

### Terraform
Infrastructure as code. The S3 bucket, IAM roles, and DynamoDB state lock are all version-controlled and reproducible. The Lambda execution role follows **least-privilege**: only `s3:PutObject` on the logs bucket, nothing else.

### Docker (AWS Lambda container image)
Packaging the Lambda as a container image (using the official `public.ecr.aws/lambda/python:3.12` base) makes dependency management deterministic and the deployment artifact portable.

### GitHub Actions (CI/CD)
- Every push runs the full test suite (`pytest --cov`)
- Merges to `main` build the Docker image, run a `trivy` security scan, and deploy to Lambda
- Branch protection prevents direct pushes to `main`

### Hypothesis (property-based testing)
Beyond unit tests, the project uses **property-based testing** to verify invariants that hold for *all* valid inputs, not just the ones I thought of:
- `PriceRow.price_eur_mwh > 0` always
- `0.0 <= wind_ratio <= 1.0` always
- `TradeDecision` serialises and deserialises without data loss
- Alert fires if and only if price < threshold

### moto (AWS mocking)
S3 interactions in tests use `moto` to mock AWS — no real AWS account needed in CI, no cost, no flakiness.

### httpx
Used for both the SMARD API calls and Slack webhook delivery. Supports both sync and async, has a clean interface for injecting mock clients in tests.

---

## Key Design Decisions

### Retry logic everywhere
- SMARD API: 3 attempts with exponential backoff
- LLM reasoning: 3 retries, then a safe fallback decision (LOG / HOLD / confidence 0.0)
- S3 upload: 1 retry, then writes to `/tmp` and emits a CloudWatch alarm
- Slack/Email: 1 retry, then logs a warning and continues (alerts are non-fatal)

The principle: **transient failures should not crash the agent or lose data**.

### Unconditional logging
Every decision is logged to S3 regardless of action type. This is intentional — you always want a record of what the agent decided and why, even if it just held.

### Fallback decision
If the LLM fails 3 times, the agent doesn't crash. It returns a safe default: `action=LOG, signal=HOLD, confidence=0.0`. The system stays running; the failure is visible in the logs.

### Secrets never in code
API keys, Slack webhook URLs, and AWS credentials are read from environment variables via `AgentConfig` (Pydantic BaseSettings). Nothing sensitive is in the Docker image or source code.

---

## What I Would Add with More Time

- **EventBridge schedule** in Terraform to trigger the Lambda hourly
- **Lambda function resource** in Terraform (currently only IAM + S3 are provisioned)
- **Real trade API integration** (currently a mock stub)
- **Grafana / CloudWatch dashboard** for decision metrics
- **Model evaluation pipeline**: replay historical decisions against actual price movements to measure agent accuracy

---

## Likely Interview Questions

**Q: Why an agent instead of a simple rule-based pipeline?**
A: Rules are brittle. An LLM can reason about combinations of signals (high demand + low wind + rising price) that would require many nested if-statements to encode manually. The agent also produces a *rationale*, which is auditable.

**Q: How do you ensure the LLM output is safe to act on?**
A: PydanticAI enforces `result_type=TradeDecision`. If the LLM returns anything that doesn't validate — wrong enum value, short rationale, confidence out of range — it's rejected and retried. After 3 failures, a safe fallback is used.

**Q: How does this scale?**
A: Lambda scales horizontally by default. Each invocation is stateless. S3 handles concurrent writes. If throughput grows, the same code runs in more Lambda instances without changes.

**Q: What does Terraform manage here?**
A: The S3 trading-logs bucket (with versioning, encryption, public access blocked), a separate S3 bucket for Terraform remote state, DynamoDB for state locking, and the Lambda IAM execution role with least-privilege permissions.

**Q: How do you test without hitting real AWS or the LLM?**
A: `moto` mocks S3 at the boto3 level. PydanticAI's `agent.override()` context manager replaces the LLM with a mock. `httpx` clients are injected as dependencies so tests can pass a mock client. No real external calls in CI.

**Q: What is the SMARD API?**
A: A public API from the German Federal Network Agency that provides real-time electricity grid data — demand, renewable production, prices. It's the live data source for demand and wind production in this project.
