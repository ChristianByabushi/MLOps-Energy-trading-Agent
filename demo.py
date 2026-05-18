"""
Energy Trading Agent — Reactive Live Demo
==========================================
The agent watches data/fake_energy_prices.csv for NEW rows.
When you append a row (manually or via inject_price.py), the agent
wakes up, reasons with the LLM, and acts — including sending a real
email if the price drops below the alert threshold.

Run modes:
    python demo.py                   # watch mode — waits for new CSV rows
    python demo.py --replay          # replay all existing rows then watch
    python demo.py --replay --fast   # replay fast (1s between rows)

In a second terminal, inject a price:
    python inject_price.py 28.00     # low price  → triggers ALERT + email
    python inject_price.py 95.00     # high price → LOG only
    python inject_price.py           # random price

What it produces:
  - Live terminal dashboard
  - demo_log.txt          — plain-English log (open in any editor)
  - demo_decisions.jsonl  — one JSON decision per line
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from dotenv import load_dotenv
load_dotenv()

# ── ANSI colours ──────────────────────────────────────────────────────────────
RESET  = "\033[0m";  BOLD   = "\033[1m";  DIM    = "\033[2m"
GREEN  = "\033[92m"; YELLOW = "\033[93m"; RED    = "\033[91m"
CYAN   = "\033[96m"; WHITE  = "\033[97m"; MAGENTA= "\033[95m"

def clr(text: str, colour: str) -> str:
    return f"{colour}{text}{RESET}"

SIGNAL_COLOUR = {"BUY": GREEN, "SELL": RED,  "HOLD": YELLOW}
ACTION_COLOUR  = {"TRADE": GREEN, "ALERT": RED, "LOG": DIM}

CSV_PATH       = Path("data/fake_energy_prices.csv")
LOG_FILE       = Path("demo_log.txt")
DECISIONS_FILE = Path("demo_decisions.jsonl")
POLL_INTERVAL  = 1.0   # seconds between CSV checks


# ── helpers ───────────────────────────────────────────────────────────────────

def clear_screen() -> None:
    os.system("cls" if os.name == "nt" else "clear")

def write_log(line: str) -> None:
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(line + "\n")

def write_decision(result) -> None:
    with DECISIONS_FILE.open("a", encoding="utf-8") as f:
        f.write(result.model_dump_json() + "\n")

def price_bar(price: float, width: int = 28) -> str:
    filled = max(0, min(width, int((price / 100.0) * width)))
    bar = "█" * filled + "░" * (width - filled)
    colour = GREEN if price < 50 else (YELLOW if price < 70 else RED)
    return clr(bar, colour)

def wind_bar(ratio: float, width: int = 18) -> str:
    filled = max(0, min(width, int(ratio * width)))
    bar = "▓" * filled + "░" * (width - filled)
    colour = GREEN if ratio > 0.4 else (YELLOW if ratio > 0.2 else RED)
    return clr(bar, colour)

def wrap(text: str, width: int = 55) -> list[str]:
    words, line, lines = text.split(), "", []
    for w in words:
        if len(line) + len(w) + 1 > width:
            lines.append(line); line = w
        else:
            line = (line + " " + w).strip()
    if line: lines.append(line)
    return lines or [""]

def read_all_csv_rows() -> list[dict]:
    """Read all rows from the CSV, return as list of dicts."""
    if not CSV_PATH.exists():
        return []
    with CSV_PATH.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


# ── dashboard ─────────────────────────────────────────────────────────────────

def print_dashboard(
    cycle: int,
    snapshot,
    result,
    history: list,
    threshold: float,
    watching: bool = True,
) -> None:
    clear_screen()
    d = result.decision
    duration = (result.completed_at - result.started_at).total_seconds()
    sig_c = SIGNAL_COLOUR.get(d.signal.value, WHITE)
    act_c = ACTION_COLOUR.get(d.action.value, WHITE)
    alert_flag = clr("  ⚡ ALERT + EMAIL SENT", RED)  if result.alert_sent  else ""
    trade_flag = clr("  📈 TRADE EXECUTED",    GREEN) if result.trade_executed else ""

    print(clr("╔══════════════════════════════════════════════════════════╗", CYAN))
    print(clr("║     ⚡  MLOps Energy Trading Agent  —  Reactive Demo     ║", CYAN))
    print(clr("╚══════════════════════════════════════════════════════════╝", RESET))
    print()
    print(clr(f"  Cycle #{cycle}   {datetime.now().strftime('%H:%M:%S')}   "
              f"({duration:.1f}s LLM reasoning)", DIM))
    print()

    print(clr("  ── MARKET DATA ──────────────────────────────────────────", WHITE))
    print(f"  Spot price   {price_bar(snapshot.spot_price_eur_mwh)}  "
          f"{clr(f'{snapshot.spot_price_eur_mwh:.2f} EUR/MWh', BOLD)}"
          f"  {clr(f'(alert if < {threshold:.0f})', DIM)}")
    print(f"  Wind ratio   {wind_bar(snapshot.wind_ratio)}  "
          f"{snapshot.wind_ratio:.1%} of demand")
    print(f"  Demand       {snapshot.demand_mw:,.0f} MW   |   "
          f"Wind prod. {snapshot.wind_production_mw:,.0f} MW")
    print()

    print(clr("  ── AI DECISION ───────────────────────────────────────────", WHITE))
    print(f"  Signal       {clr(d.signal.value, sig_c + BOLD)}")
    print(f"  Action       {clr(d.action.value, act_c + BOLD)}{alert_flag}{trade_flag}")
    print(f"  Confidence   {clr(f'{d.confidence:.0%}', BOLD)}")
    print()
    rationale_lines = wrap(d.rationale)
    print(f"  Rationale    {rationale_lines[0]}")
    for l in rationale_lines[1:]:
        print(f"               {l}")
    print()

    if history:
        print(clr("  ── DECISION HISTORY ──────────────────────────────────────", WHITE))
        for h in history[-8:]:
            sc = SIGNAL_COLOUR.get(h["signal"], WHITE)
            ac = ACTION_COLOUR.get(h["action"], WHITE)
            flags = (" ⚡" if h.get("alert") else "") + (" 📈" if h.get("trade") else "")
            ps = f"{h['price']:6.2f}"
            print(f"  {clr(h['time'], DIM)}  price={clr(ps, WHITE)}  "
                  f"signal={clr(h['signal'], sc)}  "
                  f"action={clr(h['action'], ac)}{flags}")
        print()

    print(clr("  ── OUTPUT ────────────────────────────────────────────────", DIM))
    print(clr("  📄 demo_log.txt          plain-English log", DIM))
    print(clr("  📊 demo_decisions.jsonl  structured JSON", DIM))
    print()
    if watching:
        print(clr("  👀 Watching for new rows in data/fake_energy_prices.csv", MAGENTA))
        print(clr("     → In another terminal run:  python inject_price.py 28.00", MAGENTA))
    print(clr("  Press Ctrl+C to stop.", DIM))


def write_plain_log(cycle: int, snapshot, result) -> None:
    d = result.decision
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    alert_note = "  ← ALERT + EMAIL SENT" if result.alert_sent else ""
    trade_note = "  ← TRADE EXECUTED"     if result.trade_executed else ""
    write_log("")
    write_log(f"[{ts}]  Cycle #{cycle}")
    write_log(f"  Market  : {snapshot.spot_price_eur_mwh:.2f} EUR/MWh  |  "
              f"Demand {snapshot.demand_mw:,.0f} MW  |  "
              f"Wind {snapshot.wind_production_mw:,.0f} MW ({snapshot.wind_ratio:.1%})")
    write_log(f"  Decision: {d.signal.value} / {d.action.value}  "
              f"(confidence {d.confidence:.0%}){alert_note}{trade_note}")
    write_log(f"  Reason  : {d.rationale}")
    write_log(f"  {'─'*60}")


# ── core cycle ────────────────────────────────────────────────────────────────

async def run_one_cycle(
    raw_row: dict,
    cycle: int,
    agent,
    history: list,
    threshold: float,
    watching: bool = True,
) -> None:
    """Run one perceive→reason→act cycle for a single CSV row."""
    from agent.perceiver import MarketPerceiver, SMARDSnapshot
    from agent.models import PriceRow

    price  = float(raw_row["price_eur_mwh"])
    demand = 45000 + (price - 30) * 200
    wind   = max(2000, 30000 - (price - 30) * 400)

    mock_smard = SMARDSnapshot(
        demand_mw=demand,
        wind_production_mw=wind,
        timestamp=datetime.now(tz=timezone.utc),
    )
    single_row = PriceRow.model_validate(raw_row)
    perceiver  = MarketPerceiver(csv_path=str(CSV_PATH))

    clear_screen()
    print(clr("╔══════════════════════════════════════════════════════════╗", CYAN))
    print(clr("║     ⚡  MLOps Energy Trading Agent  —  Reactive Demo     ║", CYAN))
    print(clr("╚══════════════════════════════════════════════════════════╝", RESET))
    print()
    print(clr(f"  ⏳ Cycle #{cycle} — new price detected: "
              f"{clr(f'{price:.2f} EUR/MWh', BOLD)}  — asking AI...", DIM))
    print()
    if watching:
        print(clr("  👀 Watching data/fake_energy_prices.csv for new rows", MAGENTA))

    with patch.object(perceiver, "read_csv_prices", return_value=[single_row]), \
         patch.object(perceiver, "fetch_smard_snapshot", return_value=mock_smard):
        agent.perceiver = perceiver
        try:
            result = await agent.run_cycle()
        except Exception as exc:
            print(clr(f"\n  ❌ Cycle #{cycle} failed: {exc}", RED))
            return

    snapshot = result.decision.snapshot
    history.append({
        "time":   datetime.now().strftime("%H:%M:%S"),
        "price":  snapshot.spot_price_eur_mwh,
        "signal": result.decision.signal.value,
        "action": result.decision.action.value,
        "alert":  result.alert_sent,
        "trade":  result.trade_executed,
    })

    print_dashboard(cycle, snapshot, result, history, threshold, watching)
    write_plain_log(cycle, snapshot, result)
    write_decision(result)


# ── main loop ─────────────────────────────────────────────────────────────────

async def run_demo(replay: bool, fast: bool, threshold: float) -> None:
    from agent.config import AgentConfig
    from agent.react_agent import ReActAgent

    config = AgentConfig.from_env()
    config = config.model_copy(update={"alert_threshold": threshold})
    agent  = ReActAgent(config=config)

    # Initialise output files
    LOG_FILE.write_text(
        f"Energy Trading Agent — Reactive Demo Log\n"
        f"Started  : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"Threshold: {threshold:.0f} EUR/MWh  (ALERT + email if price < threshold)\n"
        f"{'═'*62}\n",
        encoding="utf-8",
    )
    DECISIONS_FILE.write_text("", encoding="utf-8")

    history: list[dict] = []
    cycle = 0

    # ── REPLAY MODE: step through existing rows first ─────────────────────────
    if replay:
        existing_rows = read_all_csv_rows()
        if existing_rows:
            print(clr(f"\n  ▶  Replaying {len(existing_rows)} existing rows...\n", CYAN))
            time.sleep(1)
            for raw_row in existing_rows:
                cycle += 1
                await run_one_cycle(raw_row, cycle, agent, history, threshold,
                                    watching=False)
                if fast:
                    time.sleep(1)
                else:
                    for r in range(4, 0, -1):
                        sys.stdout.write(clr(f"\r  Next row in {r}s...   ", DIM))
                        sys.stdout.flush()
                        time.sleep(1)

    # ── WATCH MODE: poll CSV for new rows ─────────────────────────────────────
    known_count = len(read_all_csv_rows())

    clear_screen()
    print(clr("╔══════════════════════════════════════════════════════════╗", CYAN))
    print(clr("║     ⚡  MLOps Energy Trading Agent  —  Reactive Demo     ║", CYAN))
    print(clr("╚══════════════════════════════════════════════════════════╝", RESET))
    print()
    print(clr(f"  ✅ Agent ready.  Watching data/fake_energy_prices.csv", GREEN))
    print(clr(f"  Current rows: {known_count}  |  Alert threshold: {threshold:.0f} EUR/MWh", DIM))
    print()
    print(clr("  To trigger a reaction, open a second terminal and run:", WHITE))
    print(clr("      python inject_price.py 28.00   ← low price  → ALERT + email", GREEN))
    print(clr("      python inject_price.py 95.00   ← high price → LOG only", DIM))
    print(clr("      python inject_price.py          ← random price", DIM))
    print()
    print(clr("  Press Ctrl+C to stop.", DIM))

    while True:
        await asyncio.sleep(POLL_INTERVAL)
        current_rows = read_all_csv_rows()
        new_count = len(current_rows)

        if new_count > known_count:
            # Process every new row (handles multiple rows added at once)
            for raw_row in current_rows[known_count:]:
                cycle += 1
                await run_one_cycle(raw_row, cycle, agent, history, threshold,
                                    watching=True)
            known_count = new_count


# ── entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Reactive Energy Trading Agent demo")
    parser.add_argument("--replay",    action="store_true",
                        help="Replay existing CSV rows before watching for new ones")
    parser.add_argument("--fast",      action="store_true",
                        help="Replay at 1s intervals instead of 5s")
    parser.add_argument("--threshold", type=float, default=50.0,
                        help="Alert threshold in EUR/MWh (default: 50)")
    args = parser.parse_args()

    try:
        asyncio.run(run_demo(
            replay=args.replay,
            fast=args.fast,
            threshold=args.threshold,
        ))
    except KeyboardInterrupt:
        print(clr("\n\n  Demo stopped.", YELLOW))
        print(f"  Check {clr('demo_log.txt', BOLD)} for the full log.\n")


if __name__ == "__main__":
    main()
