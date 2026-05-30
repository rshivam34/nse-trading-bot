"""
F&O entry-funnel analysis (ANALYSIS ONLY — does not touch live code).
=====================================================================

Answers the funnel-review question with REAL index price action (no faked
option premiums): over the last ~60 trading days, how many days does each
entry variant actually trade, and what happens to the index AFTER entry?

Variants compared per index:
  STRAIGHT  : enter the moment price breaks the opening range (no retest)
  RETEST    : enter only after breakout -> pullback to edge -> re-break (the
              live logic, in its bounded/fixed form)

"Outcome" uses pure index excursion until the 14:00 option-exit time, with
NO premium model: for each entry we measure max favorable vs max adverse
index move (in %), and call it a WIN if favorable >= TARGET_PCT is reached
before adverse <= -STOP_PCT. This is directional colour only — it shows
whether breakouts CONTINUE (retest's whole premise) or fade.

Run:  python backend/tests/funnel_analysis.py
Output is ASCII-only and also written to funnel_analysis_result.txt.
"""

import os
import sys
from datetime import time

OUT = os.path.join(os.path.dirname(__file__), "funnel_analysis_result.txt")
_lines = []
def emit(s=""):
    _lines.append(s)

# Proxy thresholds (index %). A ~0.85% favorable move ~= +50% on a typical ATM
# weekly premium (delta ~0.5); ~0.5% adverse ~= -30% SL. Rough, stated openly.
TARGET_PCT = 0.85
STOP_PCT = 0.50

ORB_END = time(9, 30)
ENTRY_CUTOFF = time(12, 0)   # matches config.options_entry_cutoff
EXIT_TIME = time(14, 0)      # matches config.options_exit_time


def load_5m(yf, ticker):
    df = yf.download(ticker, period="60d", interval="5m", progress=False, auto_adjust=False)
    if df is None or len(df) == 0:
        return None
    # yfinance >=1.x returns MultiIndex columns even for a single ticker.
    if hasattr(df.columns, "nlevels") and df.columns.nlevels > 1:
        df.columns = df.columns.get_level_values(0)
    # Normalise tz to IST.
    idx = df.index
    if idx.tz is None:
        df.index = idx.tz_localize("UTC").tz_convert("Asia/Kolkata")
    else:
        df.index = idx.tz_convert("Asia/Kolkata")
    return df


def analyse(df, name, strike_step):
    days = sorted(set(df.index.date))
    funnel = {"days": 0, "valid_range": 0, "breakout": 0, "retest": 0, "confirm": 0}
    straight = {"trades": 0, "win": 0, "loss": 0, "flat": 0}
    retest = {"trades": 0, "win": 0, "loss": 0, "flat": 0}

    for day in days:
        d = df[df.index.date == day]
        d = d[[isinstance(t, type(d.index[0])) for t in d.index]]
        if len(d) < 10:
            continue
        funnel["days"] += 1

        orb = d[[t.time() < ORB_END for t in d.index]]
        if len(orb) < 2:
            continue
        hi = float(orb["High"].max())
        lo = float(orb["Low"].min())
        mid = (hi + lo) / 2.0
        if mid <= 0:
            continue
        rng_pct = (hi - lo) / mid * 100.0
        max_rng = 1.5 if name == "NIFTY" else 3.0
        if rng_pct < 0.2 or rng_pct > max_rng:
            continue
        funnel["valid_range"] += 1

        buf = mid * 0.001
        post = d[[ORB_END <= t.time() <= EXIT_TIME for t in d.index]]
        if len(post) < 2:
            continue

        state = None            # None -> dict(direction, retesting)
        straight_entry = None    # (dir, idx_price) first breakout
        retest_entry = None      # (dir, idx_price) confirmed entry

        closes = [float(c) for c in post["Close"].tolist()]
        times = [t.time() for t in post.index]

        for ltp, tm in zip(closes, times):
            in_window = tm <= ENTRY_CUTOFF

            # STRAIGHT: first breakout in the entry window
            if straight_entry is None and in_window:
                if ltp > hi + buf:
                    straight_entry = ("CALL", ltp); funnel["breakout"] += 1
                elif ltp < lo - buf:
                    straight_entry = ("PUT", ltp); funnel["breakout"] += 1

            # RETEST (bounded): breakout -> pullback past mid-side edge -> re-break
            if retest_entry is None and in_window:
                if state is None:
                    if ltp > hi + buf:
                        state = {"direction": "CALL"}
                    elif ltp < lo - buf:
                        state = {"direction": "PUT"}
                elif "retesting" not in state:
                    if state["direction"] == "CALL":
                        if mid < ltp <= hi * 1.001:
                            state["retesting"] = True; funnel["retest"] += 1
                        elif ltp <= mid:
                            state = None        # failed -> re-arm
                    else:
                        if lo * 0.999 <= ltp < mid:
                            state["retesting"] = True; funnel["retest"] += 1
                        elif ltp >= mid:
                            state = None
                else:
                    if state["direction"] == "CALL" and ltp > hi + buf:
                        retest_entry = ("CALL", ltp); funnel["confirm"] += 1; state = None
                    elif state["direction"] == "PUT" and ltp < lo - buf:
                        retest_entry = ("PUT", ltp); funnel["confirm"] += 1; state = None

        # Outcome by pure index excursion from entry to EXIT_TIME.
        def outcome(entry):
            if entry is None:
                return None
            edir, eidx = entry
            seg = [float(c) for c, t in zip(post["Close"].tolist(),
                   [tt.time() for tt in post.index])]
            # Use all post-entry closes after the entry price first appears.
            try:
                start = next(i for i, c in enumerate(seg) if c == eidx)
            except StopIteration:
                start = 0
            fav = adv = 0.0
            for c in seg[start:]:
                move = (c - eidx) / eidx * 100.0
                if edir == "PUT":
                    move = -move
                fav = max(fav, move)
                adv = min(adv, move)
                if fav >= TARGET_PCT:
                    return "win"
                if adv <= -STOP_PCT:
                    return "loss"
            return "flat"

        so = outcome(straight_entry)
        if so:
            straight["trades"] += 1; straight[so] += 1
        ro = outcome(retest_entry)
        if ro:
            retest["trades"] += 1; retest[ro] += 1

    return funnel, straight, retest


def pct(n, d):
    return f"{(100.0*n/d):.0f}%" if d else "n/a"


def report(name, funnel, straight, retest):
    emit(f"\n===== {name} =====")
    emit(f"trading days analysed         : {funnel['days']}")
    emit(f"  days with valid ORB range   : {funnel['valid_range']}  ({pct(funnel['valid_range'], funnel['days'])} of days)")
    emit(f"  -> breakout occurred        : {funnel['breakout']}  ({pct(funnel['breakout'], funnel['valid_range'])} of valid-range days)")
    emit(f"     -> pulled back (retest)  : {funnel['retest']}  ({pct(funnel['retest'], funnel['breakout'])} of breakouts)")
    emit(f"        -> confirmed (TRADE)  : {funnel['confirm']}  ({pct(funnel['confirm'], funnel['breakout'])} of breakouts)")
    emit("")
    emit(f"  STRAIGHT-breakout entries   : {straight['trades']:>3}  | win {straight['win']}  loss {straight['loss']}  flat {straight['flat']}  | win% of decided {pct(straight['win'], straight['win']+straight['loss'])}")
    emit(f"  RETEST-confirmed entries    : {retest['trades']:>3}  | win {retest['win']}  loss {retest['loss']}  flat {retest['flat']}  | win% of decided {pct(retest['win'], retest['win']+retest['loss'])}")


def main():
    try:
        import yfinance as yf
    except Exception as e:  # noqa: BLE001
        emit(f"yfinance import failed: {e}")
        _flush(); return

    emit("F&O ENTRY-FUNNEL ANALYSIS (real index action, no premium model)")
    emit(f"window: last 60 calendar days of 5m data | target +{TARGET_PCT}% / stop -{STOP_PCT}% (index proxy)")
    emit("NOTE: VIX gate NOT applied here (would only REDUCE counts on crisis days).")

    for ticker, name, step in [("^NSEI", "NIFTY", 50), ("^NSEBANK", "BANKNIFTY", 100)]:
        try:
            df = load_5m(yf, ticker)
        except Exception as e:  # noqa: BLE001
            emit(f"\n{name}: fetch failed ({type(e).__name__}: {str(e)[:80]})")
            continue
        if df is None:
            emit(f"\n{name}: no data returned")
            continue
        f, s, r = analyse(df, name, step)
        report(name, f, s, r)

    emit("\nINTERPRETATION GUIDE:")
    emit("- 'confirmed (TRADE)' is how often the live retest logic fires. If it's a")
    emit("  small fraction of breakouts, the retest requirement is the main funnel.")
    emit("- Compare STRAIGHT vs RETEST win%: if straight-breakout win% is similar or")
    emit("  better, the retest costs trades without improving quality (drop it).")
    emit("  If retest win% is clearly higher, the filter earns its keep (keep it).")
    _flush()


def _flush():
    text = "\n".join(_lines)
    with open(OUT, "w", encoding="ascii", errors="replace") as fh:
        fh.write(text + "\n")
    print(text)


if __name__ == "__main__":
    main()
