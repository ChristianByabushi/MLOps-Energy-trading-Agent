"""
reset_demo.py — restore everything to a clean state before a demo.

Resets:
  - data/fake_energy_prices.csv  (removes any injected rows)
  - demo_log.txt                 (cleared)
  - demo_decisions.jsonl         (cleared)

Run this before every demo session:
    python reset_demo.py
"""

from pathlib import Path

ORIGINAL_CSV = """\
timestamp,price_eur_mwh,region
2024-01-15T00:00:00,42.50,DE
2024-01-15T01:00:00,38.75,DE
2024-01-15T02:00:00,35.20,DE
2024-01-15T03:00:00,33.10,DE
2024-01-15T04:00:00,31.80,DE
2024-01-15T05:00:00,36.40,DE
2024-01-15T06:00:00,48.90,DE
2024-01-15T07:00:00,62.30,DE
2024-01-15T08:00:00,75.60,DE
2024-01-15T09:00:00,80.20,DE
2024-01-15T10:00:00,78.50,DE
2024-01-15T11:00:00,72.10,DE
2024-01-15T12:00:00,65.40,DE
2024-01-15T13:00:00,60.80,DE
2024-01-15T14:00:00,58.30,DE
2024-01-15T15:00:00,55.70,DE
2024-01-15T16:00:00,59.20,DE
2024-01-15T17:00:00,68.90,DE
2024-01-15T18:00:00,82.40,DE
2024-01-15T19:00:00,88.60,DE
2024-01-15T20:00:00,85.30,DE
2024-01-15T21:00:00,76.20,DE
2024-01-15T22:00:00,63.50,DE
2024-01-15T23:00:00,52.80,DE
"""

def main() -> None:
    Path("data/fake_energy_prices.csv").write_text(ORIGINAL_CSV, encoding="utf-8")
    print("✅ data/fake_energy_prices.csv  — reset to 24 original rows")

    Path("demo_log.txt").write_text("", encoding="utf-8")
    print("✅ demo_log.txt                 — cleared")

    Path("demo_decisions.jsonl").write_text("", encoding="utf-8")
    print("✅ demo_decisions.jsonl         — cleared")

    print("\n  Ready. Now run:")
    print("    Terminal 1:  python demo.py")
    print("    Terminal 2:  python inject_price.py 28.00\n")

if __name__ == "__main__":
    main()
