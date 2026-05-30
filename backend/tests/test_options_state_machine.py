"""
Characterization tests for OptionsManager.check_for_signal() ORB state machine.
=============================================================================

WHY THIS EXISTS
---------------
The F&O entry is an ORB breakout -> retest -> confirm state machine (one per
index). A code trace on 2026-05-30 found that the two "failed breakout"
branches in check_for_signal() are UNREACHABLE: the retest tests are evaluated
before the failed tests in the same elif-chain, and the retest condition has no
upper/lower bound, so it always wins. Effect: a failed breakout is mislabeled a
"retest", and each index LATCHES to its first breakout direction for the whole
day -- it can never flip even if the first breakout fails and price trends the
other way.

These tests pin the CORRECT contract:
  - happy path: a clean breakout->retest->confirm still yields a signal
    (regression guard -- must pass before AND after any fix)
  - flip: after a failed breakout, the index can take the opposite direction
    (FAILS on current code; should pass once the retest window is bounded)
  - isolation: a NIFTY failed-breakout must not wipe BANKNIFTY's state
    (forward guard for the line-193 reset-target typo, which only bites once
    the failed branch becomes reachable)

HOW TO RUN
----------
  python backend/tests/test_options_state_machine.py        # standalone, no deps
  pytest backend/tests/test_options_state_machine.py         # if pytest installed
"""

import os
import sys

# Allow `from config import ...` / `from core...` no matter the cwd.
_BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

from config import config
from core.options_manager import OptionsManager, OptionPosition


# --- helpers ---------------------------------------------------------------

NIFTY_HIGH = 24000.0
NIFTY_LOW = 23800.0          # range 200 / mid 23900 = 0.84% -> inside [0.2, 1.5]
MID = (NIFTY_HIGH + NIFTY_LOW) / 2
BUF = MID * 0.001            # 0.1% breakout buffer used by the manager (~23.9)


def _mgr_with_nifty_orb():
    mgr = OptionsManager(config.trading, broker=None)
    # update_orb_range(index, ltp, high, low) locks the opening range.
    mgr.update_orb_range("NIFTY", MID, NIFTY_HIGH, NIFTY_LOW)
    return mgr


# --- tests -----------------------------------------------------------------

def test_happy_path_call_signal_still_fires():
    """A clean CALL breakout -> retest -> confirm must produce a CE signal.

    Regression guard: any fix to the retest logic must NOT kill the normal path.
    """
    mgr = _mgr_with_nifty_orb()

    assert mgr.check_for_signal("NIFTY", NIFTY_HIGH + BUF + 6) is None   # CALL breakout
    assert mgr._nifty_state and mgr._nifty_state["direction"] == "CALL"

    assert mgr.check_for_signal("NIFTY", NIFTY_HIGH + 2) is None         # retest near high
    sig = mgr.check_for_signal("NIFTY", NIFTY_HIGH + BUF + 16)           # bounce confirm

    assert sig is not None, "happy-path breakout->retest->confirm produced NO signal"
    assert sig["option_type"] == "CE", f"expected CE, got {sig['option_type']}"


def test_index_can_flip_direction_after_failed_breakout():
    """After a failed PUT breakout, NIFTY must be able to fire a CALL.

    Sequence: PUT breakout (below low) -> price reverses up THROUGH the range
    (failed) -> strong CALL breakout -> retest -> confirm.

    On current code this FAILS: the failed PUT is mislabeled "PUT retesting",
    so the state is latched to PUT and the CALL confirm never fires.
    """
    mgr = _mgr_with_nifty_orb()

    # 1) PUT breakout: price below ORB low - buffer
    assert mgr.check_for_signal("NIFTY", NIFTY_LOW - BUF - 5) is None
    assert mgr._nifty_state and mgr._nifty_state["direction"] == "PUT"

    # 2) Failed PUT: price reverses back UP well into the range
    mgr.check_for_signal("NIFTY", MID)

    # 3) Clean CALL breakout -> retest -> confirm
    mgr.check_for_signal("NIFTY", NIFTY_HIGH + BUF + 6)    # CALL breakout
    mgr.check_for_signal("NIFTY", NIFTY_HIGH + 2)          # retest near high
    sig = mgr.check_for_signal("NIFTY", NIFTY_HIGH + BUF + 16)  # confirm

    assert sig is not None and sig["option_type"] == "CE", (
        "index is latched to its first breakout direction and cannot flip "
        "after a failed breakout (unbounded retest mislabels the reversal)"
    )


def test_nifty_failed_breakout_does_not_clobber_banknifty():
    """A NIFTY failed breakout must not reset BANKNIFTY's in-progress state.

    Forward guard for the line-193 typo (resets _banknifty_state inside the
    NIFTY branch). Currently passes only because that branch is dead; it must
    keep passing once the failed branch is made reachable.
    """
    mgr = _mgr_with_nifty_orb()

    # BANKNIFTY gets its own valid ORB + an active CALL breakout state.
    bn_high, bn_low = 55200.0, 54800.0
    bn_buf = ((bn_high + bn_low) / 2) * 0.001
    mgr.update_orb_range("BANKNIFTY", (bn_high + bn_low) / 2, bn_high, bn_low)
    mgr.check_for_signal("BANKNIFTY", bn_high + bn_buf + 5)   # BANKNIFTY CALL breakout
    assert mgr._banknifty_state is not None

    # NIFTY: PUT breakout, then failed (reverses up into range).
    mgr.check_for_signal("NIFTY", NIFTY_LOW - BUF - 5)
    mgr.check_for_signal("NIFTY", MID)

    assert mgr._banknifty_state is not None, (
        "NIFTY failed-breakout wiped BANKNIFTY's state (line-193 reset target)"
    )


# --- F&O daily-loss circuit breaker (added 2026-05-30) ---------------------

def test_loss_gate_blocks_after_max_losses():
    """Once the day's F&O loss count hits the cap, a perfect setup is blocked.

    Also asserts the gate sits BEFORE the state machine (breakout not tracked).
    """
    mgr = _mgr_with_nifty_orb()
    mgr.losses_today = mgr.max_options_losses_per_day  # at the cap
    assert mgr.check_for_signal("NIFTY", NIFTY_HIGH + BUF + 6) is None
    assert mgr._nifty_state is None, "gate should block before breakout tracking"


def test_loss_gate_blocks_after_rupee_limit():
    """Once cumulative realized F&O loss breaches the rupee cap, entries stop."""
    mgr = _mgr_with_nifty_orb()
    opt_capital = getattr(config.trading, "options_capital_allocation", 30000.0)
    cap = opt_capital * (mgr.options_daily_loss_limit_pct / 100.0)
    mgr.realized_pnl_today = -(cap + 1)
    assert mgr.check_for_signal("NIFTY", NIFTY_HIGH + BUF + 6) is None


def test_gate_open_when_within_limits():
    """Sanity: with no losses, the happy path still fires (gate not over-eager)."""
    mgr = _mgr_with_nifty_orb()
    assert mgr.losses_today == 0 and mgr.realized_pnl_today == 0.0
    mgr.check_for_signal("NIFTY", NIFTY_HIGH + BUF + 6)   # breakout
    mgr.check_for_signal("NIFTY", NIFTY_HIGH + 2)         # retest
    sig = mgr.check_for_signal("NIFTY", NIFTY_HIGH + BUF + 16)  # confirm
    assert sig is not None and sig["option_type"] == "CE"


def test_close_option_updates_loss_counters():
    """A losing close must increment losses_today and reduce realized_pnl_today."""
    mgr = _mgr_with_nifty_orb()  # broker=None -> no real order placed
    pos = OptionPosition(
        index="NIFTY", option_type="CE", strike=23900.0, symbol="TESTCE",
        token="1", lot_size=65, quantity=65, entry_premium=100.0,
        current_premium=70.0,
    )
    mgr.open_positions.append(pos)
    mgr._close_option(pos, 70.0, "SL")   # -30 premium x 65 = -1950 gross
    assert mgr.losses_today == 1
    assert mgr.realized_pnl_today < 0
    assert pos not in mgr.open_positions


# --- Per-trade deployment cap (added 2026-05-30, replaces premium cap) -------

def test_deploy_cap_allows_normal_nifty():
    """A normal NIFTY lot (Rs.150 x 65 = Rs.9,750, 14% of 70K) is sized 1 lot."""
    mgr = OptionsManager(config.trading, broker=None)
    sized = mgr._size_position(premium=150.0, lot_size=65)
    assert sized is not None, "normal NIFTY trade should NOT be blocked"
    lots, qty, deploy = sized
    assert lots >= 1 and qty == lots * 65
    assert deploy <= mgr._max_deploy() + 1e-6, "deploy must stay under the cap"


def test_deploy_cap_blocks_real_banknifty():
    """Real BANKNIFTY (Rs.2000 x 30 = Rs.60,000 = 86% of 70K) is SKIPPED.

    This is the whole point of the change: never force an oversized 1-lot trade.
    """
    mgr = OptionsManager(config.trading, broker=None)
    assert mgr._size_position(premium=2000.0, lot_size=30) is None


def test_deploy_cap_blocks_high_premium_nifty():
    """High-premium NIFTY (Rs.700 x 65 = Rs.45,500 = 65% of 70K) is SKIPPED too.

    The old premium cap (Rs.700) would have ALLOWED this 65%-of-bucket trade;
    the deploy cap correctly blocks it.
    """
    mgr = OptionsManager(config.trading, broker=None)
    assert mgr._size_position(premium=700.0, lot_size=65) is None


def test_deploy_cap_scales_down_cheap_options():
    """A cheap option scales to multiple lots but never exceeds the cap or 10."""
    mgr = OptionsManager(config.trading, broker=None)
    lots, qty, deploy = mgr._size_position(premium=50.0, lot_size=65)
    assert deploy <= mgr._max_deploy() + 1e-6
    assert 1 <= lots <= 10


def test_deploy_cap_worst_loss_under_daily_gate():
    """Invariant: max single-trade deploy x SL% must stay <= the daily loss gate.

    This is WHY the cap is 25% (not 30%): 25% x 30% SL = 7.5% < 8% gate.
    Guards against someone bumping options_max_deploy_pct above the safe value.
    """
    mgr = OptionsManager(config.trading, broker=None)
    sl_pct = config.trading.options_sl_pct / 100.0           # 0.30
    bucket = config.trading.options_capital_allocation
    gate = bucket * (mgr.options_daily_loss_limit_pct / 100.0)
    worst_single_trade_loss = mgr._max_deploy() * sl_pct
    assert worst_single_trade_loss <= gate, (
        f"one trade can lose Rs.{worst_single_trade_loss:.0f} which EXCEEDS the "
        f"daily gate Rs.{gate:.0f} — lower options_max_deploy_pct"
    )


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    failures = 0
    for fn in tests:
        try:
            fn()
            print(f"PASS  {fn.__name__}")
        except AssertionError as e:
            failures += 1
            print(f"FAIL  {fn.__name__}\n        {e}")
        except Exception as e:  # noqa: BLE001 - surface setup errors clearly
            failures += 1
            print(f"ERROR {fn.__name__}\n        {type(e).__name__}: {e}")
    print("=" * 60)
    print("ALL PASSED" if failures == 0 else f"{failures} FAILED / {len(tests)} total")
    sys.exit(1 if failures else 0)
