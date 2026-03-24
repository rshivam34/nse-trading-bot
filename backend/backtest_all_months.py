"""
Run backtests for all available months at Rs.15K and Rs.50K capital.
yfinance 5-min data limited to last 60 days, so only recent months available.
"""

import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from backtest import Backtester

# Months to test (yfinance 5-min limit = last 60 days)
MONTHS = [
    ("2026-01-23", "2026-01-31", "Jan 2026 (partial, 23-31)"),
    ("2026-02-01", "2026-02-28", "Feb 2026 (full)"),
    ("2026-03-01", "2026-03-23", "Mar 2026 (1-23, war period)"),
]

CAPITALS = [15000, 50000]


def run_all():
    print("=" * 90)
    print("  MULTI-MONTH BACKTEST: Rs.15K vs Rs.50K")
    print("  Months: Jan 23-31, Feb (full), Mar 1-23")
    print("=" * 90)

    # Collect all results
    all_results = {}

    for capital in CAPITALS:
        print(f"\n{'#' * 90}")
        print(f"  CAPITAL: Rs.{capital:,}")
        print(f"{'#' * 90}")

        for start, end, label in MONTHS:
            print(f"\n{'~' * 70}")
            print(f"  {label} | Capital: Rs.{capital:,}")
            print(f"{'~' * 70}")

            bt = Backtester()
            bt.set_capital(capital)

            try:
                bt.run(start, end)
            except Exception as e:
                print(f"  ERROR: {e}")
                continue

            # Collect summary
            eq_trades = bt.trades
            eq_wins = sum(1 for t in eq_trades if t.net_pnl > 0)
            eq_gross = sum(t.gross_pnl for t in eq_trades)
            eq_charges = sum(t.charges for t in eq_trades)
            eq_net = sum(t.net_pnl for t in eq_trades)

            key = f"{label}|{capital}"
            all_results[key] = {
                "label": label,
                "capital": capital,
                "eq_trades": len(eq_trades),
                "eq_wins": eq_wins,
                "eq_wr": (eq_wins / len(eq_trades) * 100) if eq_trades else 0,
                "eq_gross": eq_gross,
                "eq_charges": eq_charges,
                "eq_net": eq_net,
                "eq_return": (eq_net / capital * 100) if capital > 0 else 0,
            }

    # Print comparison table
    print(f"\n\n{'=' * 110}")
    print(f"  FINAL COMPARISON: ALL MONTHS x ALL CAPITALS")
    print(f"{'=' * 110}\n")

    print(f"{'Month':<28} {'Capital':>8} {'Trades':>7} {'Win%':>6} {'Gross':>10} {'Charges':>10} {'Net':>10} {'Return':>8}")
    print("-" * 100)

    for key, r in sorted(all_results.items()):
        print(
            f"{r['label']:<28} {r['capital']:>8,} {r['eq_trades']:>7} "
            f"{r['eq_wr']:>5.0f}% {r['eq_gross']:>+10.0f} {r['eq_charges']:>10.0f} "
            f"{r['eq_net']:>+10.0f} {r['eq_return']:>+7.1f}%"
        )

    # Grand totals per capital
    print("-" * 100)
    for capital in CAPITALS:
        cap_results = [r for r in all_results.values() if r['capital'] == capital]
        if not cap_results:
            continue
        total_trades = sum(r['eq_trades'] for r in cap_results)
        total_wins = sum(r['eq_wins'] for r in cap_results)
        total_gross = sum(r['eq_gross'] for r in cap_results)
        total_charges = sum(r['eq_charges'] for r in cap_results)
        total_net = sum(r['eq_net'] for r in cap_results)
        total_return = total_net / capital * 100

        print(
            f"{'TOTAL (3 months)':<28} {capital:>8,} {total_trades:>7} "
            f"{(total_wins/max(total_trades,1)*100):>5.0f}% {total_gross:>+10.0f} {total_charges:>10.0f} "
            f"{total_net:>+10.0f} {total_return:>+7.1f}%"
        )

    print()


if __name__ == "__main__":
    run_all()
