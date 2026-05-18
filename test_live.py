"""
Live connectivity tests for the CMU AI Gateway.

Run with:  python test_live.py
"""

import asyncio
import os
import sys

# Load .env before importing anything else
from dotenv import load_dotenv
load_dotenv()


# ─────────────────────────────────────────────────────────────────────────────
# Test 1: Raw openai client — simplest possible call
# ─────────────────────────────────────────────────────────────────────────────

def test_raw_openai():
    """Send a plain chat message directly via the openai library."""
    import openai

    api_key = os.environ.get("OPENAI_API_KEY", "")
    base_url = os.environ.get("OPENAI_BASE_URL", "")
    model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

    print(f"\n{'='*60}")
    print("TEST 1: Raw openai client")
    print(f"  base_url : {base_url}")
    print(f"  model    : {model}")
    print(f"  api_key  : {api_key[:8]}...{api_key[-4:] if len(api_key) > 12 else '(short)'}")
    print(f"{'='*60}")

    client = openai.OpenAI(api_key=api_key, base_url=base_url)

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "Reply with exactly: OK"}],
            max_tokens=10,
        )
        reply = response.choices[0].message.content.strip()
        print(f"  ✅ Response: '{reply}'")
        return True
    except Exception as exc:
        print(f"  ❌ Failed: {exc}")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Test 2: PydanticAI agent — same path the real agent uses
# ─────────────────────────────────────────────────────────────────────────────

async def test_pydantic_ai():
    """Send a prompt through PydanticAI with the same setup as ReActAgent."""
    from pydantic_ai import Agent
    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.providers.openai import OpenAIProvider
    from pydantic import BaseModel

    class SimpleReply(BaseModel):
        message: str

    api_key = os.environ.get("OPENAI_API_KEY", "")
    base_url = os.environ.get("OPENAI_BASE_URL", "")
    model_name = os.environ.get("OPENAI_MODEL", "gpt-4.1-mini")

    print(f"\n{'='*60}")
    print("TEST 2: PydanticAI agent (same path as ReActAgent)")
    print(f"{'='*60}")

    provider_kwargs = {"api_key": api_key}
    if base_url:
        provider_kwargs["base_url"] = base_url

    provider = OpenAIProvider(**provider_kwargs)
    model = OpenAIChatModel(model_name, provider=provider)
    agent = Agent(model=model, output_type=SimpleReply,
                  instructions="You are a helpful assistant.")

    try:
        result = await agent.run('Say hello')
        print(f"  ✅ Parsed response: message='{result.output.message}'")
        return True
    except Exception as exc:
        print(f"  ❌ Failed: {exc}")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Test 3: Full agent cycle — perceive (CSV only) + reason + act
# ─────────────────────────────────────────────────────────────────────────────

async def test_full_agent():
    """Run one full ReActAgent cycle using the CSV data and the live LLM."""
    from unittest.mock import MagicMock, patch
    from agent.config import AgentConfig
    from agent.react_agent import ReActAgent
    from agent.perceiver import MarketPerceiver, SMARDSnapshot
    from datetime import datetime, timezone

    print(f"\n{'='*60}")
    print("TEST 3: Full ReActAgent cycle (CSV + live LLM, no real S3)")
    print(f"{'='*60}")

    config = AgentConfig.from_env()

    # Use a mock SMARD snapshot so we don't need internet for the perceive step
    mock_smard = SMARDSnapshot(
        demand_mw=52000.0,
        wind_production_mw=14000.0,
        timestamp=datetime.now(tz=timezone.utc),
    )

    perceiver = MarketPerceiver(csv_path=config.csv_path)

    with patch.object(perceiver, "fetch_smard_snapshot", return_value=mock_smard):
        agent = ReActAgent(config=config, perceiver=perceiver)

        try:
            result = await agent.run_cycle()
            d = result.decision
            print(f"  ✅ Decision received!")
            print(f"     action     : {d.action.value}")
            print(f"     signal     : {d.signal.value}")
            print(f"     confidence : {d.confidence:.2f}")
            print(f"     rationale  : {d.rationale[:80]}...")
            print(f"     duration   : {(result.completed_at - result.started_at).total_seconds():.2f}s")
            return True
        except Exception as exc:
            print(f"  ❌ Failed: {exc}")
            return False


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

async def main():
    print("\n🔍 CMU AI Gateway connectivity tests\n")

    results = []

    # Test 1 — synchronous
    results.append(("Raw openai client",   test_raw_openai()))

    # Test 2 — async
    results.append(("PydanticAI agent",    await test_pydantic_ai()))

    # Test 3 — async, full cycle
    results.append(("Full ReActAgent cycle", await test_full_agent()))

    # Summary
    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    for name, passed in results:
        icon = "✅" if passed else "❌"
        print(f"  {icon}  {name}")

    all_passed = all(r for _, r in results)
    print(f"\n{'All tests passed! 🎉' if all_passed else 'Some tests failed — see errors above.'}")
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
