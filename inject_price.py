"""
inject_price.py — append a new price row to the CSV while the demo is running.

Usage:
    python inject_price.py 28.00    # inject a specific price (triggers ALERT)
    python inject_price.py 95.00    # inject a high price (LOG only)
    python inject_price.py          # inject a random price between 20 and 100

The demo.py watcher detects the new row within 1 second and reacts.
"""

from __future__ import annotations

import random
import sys
from datetime import datetime, timezone
from pathlib import Path

CSV_PATH = Path("data/fake_energy_prices.csv")


def inject(price: float) -> None:
    ts = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    row = f"{ts},{price:.2f},DE\n"

    with CSV_PATH.open("a", encoding="utf-8") as f:
        f.write(row)

    print(f"✅ Injected: timestamp={ts}  price={price:.2f} EUR/MWh")
    print(f"   The agent will react within ~1 second.")


def main() -> None:
    if len(sys.argv) > 1:
        try:
            price = float(sys.argv[1])
        except ValueError:
            print(f"❌ Invalid price: {sys.argv[1]}  (must be a number)")
            sys.exit(1)
    else:
        price = round(random.uniform(20.0, 100.0), 2)
        print(f"  No price given — using random: {price:.2f} EUR/MWh")

    inject(price)


if __name__ == "__main__":
    main()
