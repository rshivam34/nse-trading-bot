"""
NSE Bot Control Panel — Desktop GUI
======================================
Single-file Tkinter app for managing the NSE Intraday F&O bot.

Features:
  - Capital + mode configuration (writes to .env and config.py)
  - F&O / Equity toggles
  - Per-segment capital allocation
  - Start / Stop bot with one click
  - Today's live P&L (from trades.csv + logs)
  - Day-on-day historical P&L (last 90 days)
  - Monthly P&L summary
  - Strategy stats (win rate, profit factor, drawdown)

Launch: double-click `nse_bot_control.py` or run `python nse_bot_control.py`
"""

import csv
import os
import re
import subprocess
import sys
import threading
import time
import tkinter as tk
from datetime import datetime, timedelta
from pathlib import Path
from tkinter import messagebox, ttk

# ===================== Paths =====================
PROJECT_ROOT = Path(__file__).resolve().parent
ENV_PATH = PROJECT_ROOT / "backend" / ".env"
CONFIG_PATH = PROJECT_ROOT / "backend" / "config.py"
TRADES_CSV = PROJECT_ROOT / "backend" / "logs" / "trades.csv"
LIVE_BAT = PROJECT_ROOT / "start_bot_live.bat"


# ===================== Config Read/Write Helpers =====================
def read_env_value(key: str, default: str = "") -> str:
    """Read a single key=value line from .env"""
    if not ENV_PATH.exists():
        return default
    pattern = re.compile(rf"^{re.escape(key)}\s*=\s*(.*?)\s*$", re.M)
    text = ENV_PATH.read_text(encoding="utf-8")
    m = pattern.search(text)
    return m.group(1) if m else default


def write_env_value(key: str, value: str):
    """Update a single key=value in .env (preserves other lines)."""
    if not ENV_PATH.exists():
        return
    text = ENV_PATH.read_text(encoding="utf-8")
    pattern = re.compile(rf"^({re.escape(key)})\s*=\s*.*?\s*$", re.M)
    if pattern.search(text):
        text = pattern.sub(rf"\1={value}", text)
    else:
        text += f"\n{key}={value}\n"
    ENV_PATH.write_text(text, encoding="utf-8")


def read_config_value(field: str, default: str = "") -> str:
    """Read a field's value from config.py (matches `field: type = value`)."""
    if not CONFIG_PATH.exists():
        return default
    text = CONFIG_PATH.read_text(encoding="utf-8")
    pattern = re.compile(
        rf"^\s*{re.escape(field)}\s*:\s*[^=]+=\s*([^#\n]+?)(?:\s*#.*)?$",
        re.M,
    )
    m = pattern.search(text)
    return m.group(1).strip() if m else default


def write_config_value(field: str, new_value: str):
    """Update a field's value in config.py (preserves type annotation + comment)."""
    if not CONFIG_PATH.exists():
        return
    text = CONFIG_PATH.read_text(encoding="utf-8")
    # Match: "    field: type = value  # optional comment"
    pattern = re.compile(
        rf"^(\s*{re.escape(field)}\s*:\s*[^=]+=\s*)([^#\n]+?)(\s*#.*)?$",
        re.M,
    )

    def repl(m):
        comment = m.group(3) or ""
        return f"{m.group(1)}{new_value}{comment}"

    new_text = pattern.sub(repl, text, count=1)
    if new_text != text:
        CONFIG_PATH.write_text(new_text, encoding="utf-8")


# ===================== Trade Data =====================
def read_trades() -> list[dict]:
    """Read all trades from logs/trades.csv. Returns list of dicts."""
    if not TRADES_CSV.exists():
        return []
    try:
        with open(TRADES_CSV, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            return list(reader)
    except Exception:
        return []


def parse_trade_pnl(row: dict) -> tuple[str, float]:
    """Returns (date_str, net_pnl). Empty string if can't parse."""
    date_str = row.get("date", "")
    try:
        net = float(row.get("net_pnl", 0))
    except (ValueError, TypeError):
        net = 0.0
    return date_str, net


def todays_stats() -> dict:
    """Compute today's trade count + P&L from trades.csv."""
    today = datetime.now().strftime("%Y-%m-%d")
    trades_today = []
    for row in read_trades():
        if row.get("date", "") == today:
            trades_today.append(row)
    wins = sum(1 for t in trades_today if parse_trade_pnl(t)[1] > 0)
    losses = sum(1 for t in trades_today if parse_trade_pnl(t)[1] <= 0)
    net = sum(parse_trade_pnl(t)[1] for t in trades_today)
    return {
        "trades": len(trades_today),
        "wins": wins,
        "losses": losses,
        "net_pnl": net,
    }


def daily_history(days: int = 90) -> list[dict]:
    """Group trades by date for last N days. Returns list newest-first."""
    cutoff = datetime.now() - timedelta(days=days)
    by_date = {}
    for row in read_trades():
        date_str, net = parse_trade_pnl(row)
        if not date_str:
            continue
        try:
            d = datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            continue
        if d < cutoff:
            continue
        if date_str not in by_date:
            by_date[date_str] = {"date": date_str, "trades": 0, "wins": 0, "losses": 0, "net": 0.0}
        by_date[date_str]["trades"] += 1
        if net > 0:
            by_date[date_str]["wins"] += 1
        else:
            by_date[date_str]["losses"] += 1
        by_date[date_str]["net"] += net
    return sorted(by_date.values(), key=lambda x: x["date"], reverse=True)


def monthly_summary() -> list[dict]:
    """Group trades by month."""
    by_month = {}
    for row in read_trades():
        date_str, net = parse_trade_pnl(row)
        if not date_str:
            continue
        month = date_str[:7]
        if month not in by_month:
            by_month[month] = {"month": month, "trades": 0, "wins": 0, "net": 0.0}
        by_month[month]["trades"] += 1
        if net > 0:
            by_month[month]["wins"] += 1
        by_month[month]["net"] += net
    return sorted(by_month.values(), key=lambda x: x["month"])


def overall_stats() -> dict:
    """Cumulative stats across all trades."""
    trades = read_trades()
    if not trades:
        return {"total": 0, "wins": 0, "losses": 0, "net": 0.0, "win_rate": 0.0,
                "profit_factor": 0.0, "best_day": None, "worst_day": None,
                "best_pnl": 0.0, "worst_pnl": 0.0}
    nets = [parse_trade_pnl(t)[1] for t in trades]
    wins = [n for n in nets if n > 0]
    losses = [n for n in nets if n <= 0]
    win_sum = sum(wins)
    loss_sum = abs(sum(losses)) or 1.0
    daily = daily_history(days=999)
    best = max(daily, key=lambda x: x["net"]) if daily else None
    worst = min(daily, key=lambda x: x["net"]) if daily else None
    return {
        "total": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "net": sum(nets),
        "win_rate": len(wins) * 100 / len(trades) if trades else 0,
        "profit_factor": win_sum / loss_sum,
        "best_day": best["date"] if best else None,
        "best_pnl": best["net"] if best else 0,
        "worst_day": worst["date"] if worst else None,
        "worst_pnl": worst["net"] if worst else 0,
    }


# ===================== Bot Process Management =====================
class BotProcess:
    """Tracks bot subprocess. Single instance."""

    def __init__(self):
        self.proc: subprocess.Popen | None = None

    def is_running(self) -> bool:
        if self.proc is None:
            return False
        return self.proc.poll() is None

    def start(self) -> tuple[bool, str]:
        if self.is_running():
            return False, "Bot is already running."
        if not LIVE_BAT.exists():
            return False, f"Launcher not found: {LIVE_BAT}"
        try:
            self.proc = subprocess.Popen(
                ["cmd.exe", "/c", str(LIVE_BAT)],
                cwd=str(PROJECT_ROOT),
                creationflags=subprocess.CREATE_NEW_CONSOLE,
            )
            return True, f"Bot started (PID {self.proc.pid}). Window opened separately."
        except Exception as e:
            return False, f"Failed to start: {e}"

    def stop(self) -> tuple[bool, str]:
        if not self.is_running():
            return False, "Bot is not running."
        try:
            # Try graceful: send Ctrl+C equivalent via terminate
            self.proc.terminate()
            time.sleep(1)
            if self.is_running():
                self.proc.kill()
            return True, "Bot stopped."
        except Exception as e:
            return False, f"Failed to stop: {e}"


# ===================== GUI =====================
class ControlPanel(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("NSE Trading Bot — Control Panel")
        self.geometry("900x700")
        self.bot = BotProcess()

        # Style
        style = ttk.Style(self)
        try:
            style.theme_use("vista")
        except Exception:
            pass

        # Notebook (tabs)
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=8, pady=8)

        self.tab_control = ttk.Frame(self.notebook)
        self.tab_config = ttk.Frame(self.notebook)
        self.tab_history = ttk.Frame(self.notebook)
        self.tab_analysis = ttk.Frame(self.notebook)

        self.notebook.add(self.tab_control, text="Control")
        self.notebook.add(self.tab_config, text="Configuration")
        self.notebook.add(self.tab_history, text="Daily History")
        self.notebook.add(self.tab_analysis, text="Analysis")

        self._build_control_tab()
        self._build_config_tab()
        self._build_history_tab()
        self._build_analysis_tab()

        # Auto-refresh
        self.after(2000, self._auto_refresh)

    # ─────────── Tab: Control ───────────
    def _build_control_tab(self):
        f = self.tab_control

        # Status card
        status_frame = ttk.LabelFrame(f, text="Bot Status", padding=15)
        status_frame.pack(fill="x", padx=10, pady=10)

        self.status_var = tk.StringVar(value="Stopped ⬤")
        ttk.Label(status_frame, textvariable=self.status_var, font=("Segoe UI", 16, "bold")).pack(pady=5)

        btn_frame = ttk.Frame(status_frame)
        btn_frame.pack(pady=10)
        self.start_btn = ttk.Button(btn_frame, text="▶ START BOT", command=self._start_bot, width=20)
        self.start_btn.pack(side="left", padx=10)
        self.stop_btn = ttk.Button(btn_frame, text="■ STOP BOT", command=self._stop_bot, width=20)
        self.stop_btn.pack(side="left", padx=10)

        # Today's P&L card
        pnl_frame = ttk.LabelFrame(f, text="Today's P&L", padding=15)
        pnl_frame.pack(fill="x", padx=10, pady=10)

        grid = ttk.Frame(pnl_frame)
        grid.pack(fill="x")

        self.today_trades = tk.StringVar(value="0")
        self.today_wins = tk.StringVar(value="0")
        self.today_losses = tk.StringVar(value="0")
        self.today_net = tk.StringVar(value="Rs.0.00")

        for i, (label, var) in enumerate([
            ("Trades", self.today_trades),
            ("Wins", self.today_wins),
            ("Losses", self.today_losses),
            ("Net P&L", self.today_net),
        ]):
            ttk.Label(grid, text=label, font=("Segoe UI", 10)).grid(row=0, column=i, padx=20, pady=5)
            ttk.Label(grid, textvariable=var, font=("Segoe UI", 14, "bold")).grid(row=1, column=i, padx=20)

        # Lifetime stats card
        stats_frame = ttk.LabelFrame(f, text="Lifetime Stats", padding=15)
        stats_frame.pack(fill="x", padx=10, pady=10)

        sg = ttk.Frame(stats_frame)
        sg.pack(fill="x")

        self.life_total = tk.StringVar(value="0")
        self.life_winrate = tk.StringVar(value="0%")
        self.life_pf = tk.StringVar(value="0.00")
        self.life_net = tk.StringVar(value="Rs.0")
        self.life_best = tk.StringVar(value="—")
        self.life_worst = tk.StringVar(value="—")

        rows = [
            ("Total Trades", self.life_total),
            ("Win Rate", self.life_winrate),
            ("Profit Factor", self.life_pf),
            ("Net P&L", self.life_net),
            ("Best Day", self.life_best),
            ("Worst Day", self.life_worst),
        ]
        for i, (label, var) in enumerate(rows):
            r, c = i // 3, i % 3
            ttk.Label(sg, text=label, font=("Segoe UI", 10)).grid(row=r * 2, column=c, padx=20, pady=2, sticky="w")
            ttk.Label(sg, textvariable=var, font=("Segoe UI", 12, "bold")).grid(row=r * 2 + 1, column=c, padx=20, sticky="w")

        # Reminders
        rem = ttk.LabelFrame(f, text="Pre-flight Reminders", padding=15)
        rem.pack(fill="x", padx=10, pady=10)
        reminders = (
            "• Verify your IP is whitelisted at https://smartapi.angelone.in/\n"
            "• Verify ≥ Rs.30K cash in Angel One account\n"
            "• Verify F&O segment is active\n"
            "• Bot self-skips weekends + NSE holidays\n"
            "• Best to start before 9:00 AM IST for full pre-market routine"
        )
        ttk.Label(rem, text=reminders, justify="left", font=("Segoe UI", 9)).pack(anchor="w")

    def _start_bot(self):
        ok, msg = self.bot.start()
        messagebox.showinfo("Start", msg) if ok else messagebox.showerror("Start failed", msg)
        self._update_status()

    def _stop_bot(self):
        if not messagebox.askyesno("Stop", "Stop the bot now? Open positions will be force-exited."):
            return
        ok, msg = self.bot.stop()
        messagebox.showinfo("Stop", msg) if ok else messagebox.showerror("Stop failed", msg)
        self._update_status()

    def _update_status(self):
        if self.bot.is_running():
            self.status_var.set("Running ●")
            self.start_btn.state(["disabled"])
            self.stop_btn.state(["!disabled"])
        else:
            self.status_var.set("Stopped ⬤")
            self.start_btn.state(["!disabled"])
            self.stop_btn.state(["disabled"])

    def _refresh_today_stats(self):
        s = todays_stats()
        self.today_trades.set(str(s["trades"]))
        self.today_wins.set(str(s["wins"]))
        self.today_losses.set(str(s["losses"]))
        sign = "+" if s["net_pnl"] >= 0 else ""
        self.today_net.set(f"Rs.{sign}{s['net_pnl']:,.2f}")

        o = overall_stats()
        self.life_total.set(str(o["total"]))
        self.life_winrate.set(f"{o['win_rate']:.1f}%")
        self.life_pf.set(f"{o['profit_factor']:.2f}")
        sign = "+" if o["net"] >= 0 else ""
        self.life_net.set(f"Rs.{sign}{o['net']:,.2f}")
        self.life_best.set(f"{o['best_day']} (Rs.{o['best_pnl']:+,.0f})" if o["best_day"] else "—")
        self.life_worst.set(f"{o['worst_day']} (Rs.{o['worst_pnl']:+,.0f})" if o["worst_day"] else "—")

    # ─────────── Tab: Configuration ───────────
    def _build_config_tab(self):
        f = self.tab_config

        canvas = tk.Canvas(f, borderwidth=0)
        scroll = ttk.Scrollbar(f, orient="vertical", command=canvas.yview)
        inner = ttk.Frame(canvas)
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        # Capital + Mode
        cap_frame = ttk.LabelFrame(inner, text="Capital & Mode", padding=15)
        cap_frame.pack(fill="x", padx=10, pady=10)

        self.cfg_capital = tk.StringVar(value=read_env_value("INITIAL_CAPITAL", "30000"))
        self.cfg_paper = tk.StringVar(value=read_env_value("PAPER_TRADING", "False"))

        row = 0
        ttk.Label(cap_frame, text="Total Capital (Rs):").grid(row=row, column=0, sticky="w", pady=4)
        ttk.Entry(cap_frame, textvariable=self.cfg_capital, width=15).grid(row=row, column=1, sticky="w")
        row += 1
        ttk.Label(cap_frame, text="Paper Trading:").grid(row=row, column=0, sticky="w", pady=4)
        ttk.Combobox(cap_frame, textvariable=self.cfg_paper, values=["True", "False"], width=12, state="readonly").grid(row=row, column=1, sticky="w")
        ttk.Label(cap_frame, text="(False = REAL MONEY)", font=("Segoe UI", 8), foreground="red").grid(row=row, column=2, sticky="w", padx=5)

        # Equity / F&O toggles
        toggle_frame = ttk.LabelFrame(inner, text="Trading Modes", padding=15)
        toggle_frame.pack(fill="x", padx=10, pady=10)

        self.cfg_equity_enabled = tk.StringVar(value=read_config_value("equity_enabled", "False"))
        self.cfg_options_enabled = tk.StringVar(value=read_config_value("options_enabled", "True"))

        ttk.Label(toggle_frame, text="Equity Intraday Enabled:").grid(row=0, column=0, sticky="w", pady=4)
        ttk.Combobox(toggle_frame, textvariable=self.cfg_equity_enabled, values=["True", "False"], width=12, state="readonly").grid(row=0, column=1, sticky="w")
        ttk.Label(toggle_frame, text="(Backtest shows -3.97% — recommended OFF)", font=("Segoe UI", 8)).grid(row=0, column=2, sticky="w", padx=5)

        ttk.Label(toggle_frame, text="F&O Options Enabled:").grid(row=1, column=0, sticky="w", pady=4)
        ttk.Combobox(toggle_frame, textvariable=self.cfg_options_enabled, values=["True", "False"], width=12, state="readonly").grid(row=1, column=1, sticky="w")
        ttk.Label(toggle_frame, text="(Backtest shows +79% — recommended ON)", font=("Segoe UI", 8)).grid(row=1, column=2, sticky="w", padx=5)

        # Capital allocation
        alloc_frame = ttk.LabelFrame(inner, text="Capital Allocation", padding=15)
        alloc_frame.pack(fill="x", padx=10, pady=10)

        self.cfg_eq_alloc = tk.StringVar(value=read_config_value("equity_capital_allocation", "0.0"))
        self.cfg_op_alloc = tk.StringVar(value=read_config_value("options_capital_allocation", "30000.0"))

        ttk.Label(alloc_frame, text="Equity allocation (Rs):").grid(row=0, column=0, sticky="w", pady=4)
        ttk.Entry(alloc_frame, textvariable=self.cfg_eq_alloc, width=15).grid(row=0, column=1, sticky="w")
        ttk.Label(alloc_frame, text="F&O allocation (Rs):").grid(row=1, column=0, sticky="w", pady=4)
        ttk.Entry(alloc_frame, textvariable=self.cfg_op_alloc, width=15).grid(row=1, column=1, sticky="w")

        # F&O settings
        fno_frame = ttk.LabelFrame(inner, text="F&O Settings", padding=15)
        fno_frame.pack(fill="x", padx=10, pady=10)

        self.cfg_op_max_trades = tk.StringVar(value=read_config_value("options_max_trades_per_day", "4"))
        self.cfg_op_max_premium = tk.StringVar(value=read_config_value("options_max_premium", "700.0"))
        self.cfg_vix_cutoff = tk.StringVar(value=read_config_value("vix_caution_threshold", "18.0"))

        ttk.Label(fno_frame, text="Max F&O trades/day:").grid(row=0, column=0, sticky="w", pady=4)
        ttk.Entry(fno_frame, textvariable=self.cfg_op_max_trades, width=15).grid(row=0, column=1, sticky="w")
        ttk.Label(fno_frame, text="Max option premium (Rs):").grid(row=1, column=0, sticky="w", pady=4)
        ttk.Entry(fno_frame, textvariable=self.cfg_op_max_premium, width=15).grid(row=1, column=1, sticky="w")
        ttk.Label(fno_frame, text="VIX cutoff (skip if above):").grid(row=2, column=0, sticky="w", pady=4)
        ttk.Entry(fno_frame, textvariable=self.cfg_vix_cutoff, width=15).grid(row=2, column=1, sticky="w")

        # Equity settings
        eq_frame = ttk.LabelFrame(inner, text="Equity Settings (when enabled)", padding=15)
        eq_frame.pack(fill="x", padx=10, pady=10)

        self.cfg_max_trades = tk.StringVar(value=read_config_value("max_trades_per_day", "5"))
        self.cfg_min_score = tk.StringVar(value=read_config_value("min_score_to_trade", "80"))
        self.cfg_max_risk = tk.StringVar(value=read_config_value("max_risk_per_trade_pct", "1.5"))

        ttk.Label(eq_frame, text="Max equity trades/day:").grid(row=0, column=0, sticky="w", pady=4)
        ttk.Entry(eq_frame, textvariable=self.cfg_max_trades, width=15).grid(row=0, column=1, sticky="w")
        ttk.Label(eq_frame, text="Min signal score:").grid(row=1, column=0, sticky="w", pady=4)
        ttk.Entry(eq_frame, textvariable=self.cfg_min_score, width=15).grid(row=1, column=1, sticky="w")
        ttk.Label(eq_frame, text="Max risk per trade (%):").grid(row=2, column=0, sticky="w", pady=4)
        ttk.Entry(eq_frame, textvariable=self.cfg_max_risk, width=15).grid(row=2, column=1, sticky="w")

        # Save button
        btn_save = ttk.Button(inner, text="💾 Save All Changes", command=self._save_config, width=25)
        btn_save.pack(pady=20)
        ttk.Label(inner, text="(Changes apply on next bot start. Bot must be stopped to take effect.)",
                  font=("Segoe UI", 9), foreground="gray").pack()

    def _save_config(self):
        try:
            # .env values
            write_env_value("INITIAL_CAPITAL", self.cfg_capital.get())
            write_env_value("PAPER_TRADING", self.cfg_paper.get())

            # config.py values
            write_config_value("equity_enabled", self.cfg_equity_enabled.get())
            write_config_value("options_enabled", self.cfg_options_enabled.get())
            write_config_value("equity_capital_allocation", self.cfg_eq_alloc.get())
            write_config_value("options_capital_allocation", self.cfg_op_alloc.get())
            write_config_value("options_max_trades_per_day", self.cfg_op_max_trades.get())
            write_config_value("options_max_premium", self.cfg_op_max_premium.get())
            write_config_value("vix_caution_threshold", self.cfg_vix_cutoff.get())
            write_config_value("max_trades_per_day", self.cfg_max_trades.get())
            write_config_value("min_score_to_trade", self.cfg_min_score.get())
            write_config_value("max_risk_per_trade_pct", self.cfg_max_risk.get())

            messagebox.showinfo("Saved", "Configuration saved.\n\nChanges take effect on next bot start.\nIf bot is running, stop and restart it.")
        except Exception as e:
            messagebox.showerror("Save failed", str(e))

    # ─────────── Tab: Daily History ───────────
    def _build_history_tab(self):
        f = self.tab_history
        ttk.Label(f, text="Last 90 Days — Day-by-Day P&L", font=("Segoe UI", 12, "bold")).pack(pady=10)

        cols = ("date", "trades", "wins", "losses", "net", "cum")
        self.tree_history = ttk.Treeview(f, columns=cols, show="headings", height=25)
        for col, name, width, anchor in [
            ("date", "Date", 100, "center"),
            ("trades", "Trades", 70, "center"),
            ("wins", "Wins", 60, "center"),
            ("losses", "Losses", 70, "center"),
            ("net", "Net P&L", 130, "e"),
            ("cum", "Cumulative", 130, "e"),
        ]:
            self.tree_history.heading(col, text=name)
            self.tree_history.column(col, width=width, anchor=anchor)
        self.tree_history.pack(fill="both", expand=True, padx=10, pady=10)

        ttk.Button(f, text="🔄 Refresh", command=self._refresh_history).pack(pady=5)

    def _refresh_history(self):
        for item in self.tree_history.get_children():
            self.tree_history.delete(item)
        days = daily_history(days=90)
        days_ascending = list(reversed(days))  # oldest first for cumulative
        cum = 0.0
        cum_map = {}
        for d in days_ascending:
            cum += d["net"]
            cum_map[d["date"]] = cum
        for d in days:
            sign = "+" if d["net"] >= 0 else ""
            csign = "+" if cum_map[d["date"]] >= 0 else ""
            self.tree_history.insert(
                "", "end",
                values=(d["date"], d["trades"], d["wins"], d["losses"],
                        f"Rs.{sign}{d['net']:,.2f}",
                        f"Rs.{csign}{cum_map[d['date']]:,.2f}"),
                tags=("win" if d["net"] > 0 else "loss" if d["net"] < 0 else "flat",)
            )
        self.tree_history.tag_configure("win", foreground="green")
        self.tree_history.tag_configure("loss", foreground="red")

    # ─────────── Tab: Analysis ───────────
    def _build_analysis_tab(self):
        f = self.tab_analysis
        ttk.Label(f, text="Monthly Summary", font=("Segoe UI", 12, "bold")).pack(pady=10)

        cols = ("month", "trades", "wins", "winrate", "net", "ret")
        self.tree_monthly = ttk.Treeview(f, columns=cols, show="headings", height=15)
        for col, name, width, anchor in [
            ("month", "Month", 100, "center"),
            ("trades", "Trades", 80, "center"),
            ("wins", "Wins", 70, "center"),
            ("winrate", "Win %", 80, "e"),
            ("net", "Net P&L", 130, "e"),
            ("ret", "Return %", 100, "e"),
        ]:
            self.tree_monthly.heading(col, text=name)
            self.tree_monthly.column(col, width=width, anchor=anchor)
        self.tree_monthly.pack(fill="x", padx=10, pady=10)

        # Summary stats
        sum_frame = ttk.LabelFrame(f, text="All-Time Summary", padding=15)
        sum_frame.pack(fill="x", padx=10, pady=10)
        self.analysis_text = tk.Text(sum_frame, height=10, font=("Consolas", 10))
        self.analysis_text.pack(fill="both", expand=True)

        ttk.Button(f, text="🔄 Refresh", command=self._refresh_analysis).pack(pady=5)

    def _refresh_analysis(self):
        for item in self.tree_monthly.get_children():
            self.tree_monthly.delete(item)
        months = monthly_summary()
        try:
            cap = float(read_env_value("INITIAL_CAPITAL", "30000"))
        except ValueError:
            cap = 30000
        for m in months:
            wr = (m["wins"] / m["trades"] * 100) if m["trades"] else 0
            ret = (m["net"] / cap * 100) if cap else 0
            sign = "+" if m["net"] >= 0 else ""
            self.tree_monthly.insert(
                "", "end",
                values=(m["month"], m["trades"], m["wins"], f"{wr:.1f}%",
                        f"Rs.{sign}{m['net']:,.2f}", f"{ret:+.2f}%"),
                tags=("win" if m["net"] > 0 else "loss",)
            )
        self.tree_monthly.tag_configure("win", foreground="green")
        self.tree_monthly.tag_configure("loss", foreground="red")

        # Summary
        o = overall_stats()
        text = (
            f"Capital:           Rs.{cap:,.0f}\n"
            f"Total trades:      {o['total']}\n"
            f"Wins / Losses:     {o['wins']} / {o['losses']}\n"
            f"Win rate:          {o['win_rate']:.2f}%\n"
            f"Profit factor:     {o['profit_factor']:.2f}\n"
            f"Net P&L:           Rs.{o['net']:+,.2f}\n"
            f"Return on capital: {(o['net']/cap*100) if cap else 0:+.2f}%\n"
            f"Best day:          {o['best_day']} (Rs.{o['best_pnl']:+,.2f})\n"
            f"Worst day:         {o['worst_day']} (Rs.{o['worst_pnl']:+,.2f})\n"
        )
        self.analysis_text.delete("1.0", "end")
        self.analysis_text.insert("1.0", text)

    # ─────────── Auto refresh ───────────
    def _auto_refresh(self):
        self._update_status()
        self._refresh_today_stats()
        self._refresh_history()
        self._refresh_analysis()
        # Refresh every 10 seconds
        self.after(10000, self._auto_refresh)


# ===================== Main =====================
if __name__ == "__main__":
    app = ControlPanel()
    app.mainloop()
