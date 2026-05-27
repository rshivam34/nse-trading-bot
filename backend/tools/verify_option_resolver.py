"""Standalone verification for the master-driven option resolver.

Run on the VM (where the live instrument master + venv live):
    cd /home/ubuntu/nse-trading-bot/backend
    ../.venv/bin/python tools/verify_option_resolver.py

Proves:
  1. The OLD hand-built symbol (BANKNIFTY28MAY2026...) is NOT in the master
     (reproduces the live zero-trades bug).
  2. resolve_option() finds REAL tradeable NIFTY + BANKNIFTY options, returning
     a token and the broker's real lot size.
Exits non-zero on any failure so it can gate a deploy.
"""
import json
import sys
from pathlib import Path

# Allow `from core.broker import resolve_option` when run from backend/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.broker import resolve_option  # noqa: E402

MASTER = Path("logs/scrip_master.json")


def main() -> None:
    master = json.load(open(MASTER))
    print(f"master entries: {len(master)}")
    failures = []

    # 1. Reproduce the bug: the old hand-built symbol must NOT exist.
    old = "BANKNIFTY28MAY202655200CE"
    exists = any(e.get("symbol") == old and e.get("exch_seg") == "NFO" for e in master)
    print(f"[bug-repro] old symbol {old} present? {exists}  (expect False)")
    if exists:
        failures.append("old hand-built symbol unexpectedly exists")

    # 2. The resolver must find real, tradeable options.
    checks = [
        ("NIFTY", "CE", 24000), ("NIFTY", "PE", 24000),
        ("BANKNIFTY", "CE", 55200), ("BANKNIFTY", "PE", 55200),
    ]
    for index, opt_type, strike in checks:
        r = resolve_option(master, index, opt_type, strike)
        if not r or not r.get("token"):
            print(f"[FAIL] resolve_option({index}, {opt_type}, {strike}) -> {r}")
            failures.append(f"{index} {opt_type} unresolved")
            continue
        print(
            f"[ok]  {index} {opt_type} {strike} -> {r['symbol']} | exp {r['expiry']} "
            f"| strike {r['strike']} | lot {r['lot_size']} | token {r['token']}"
        )
        if not r["symbol"].endswith(opt_type) or index not in r["symbol"]:
            failures.append(f"{index} {opt_type} resolved to suspicious symbol {r['symbol']}")
        if r["lot_size"] <= 0:
            failures.append(f"{index} {opt_type} has non-positive lot size")

    if failures:
        print("\nRESULT: FAIL ->", failures)
        sys.exit(1)
    print("\nRESULT: PASS — resolver returns real broker instruments with tokens + lot sizes")


if __name__ == "__main__":
    main()
