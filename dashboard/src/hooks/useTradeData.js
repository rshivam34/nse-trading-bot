/**
 * useTradeData — Aggregated trading state from Firebase.
 *
 * Reads all Firebase paths and combines them into a single clean state object.
 * All components subscribe through this hook, not directly to Firebase.
 *
 * New paths added:
 * - /regime         -- market regime (TRENDING/VOLATILE/etc.)
 * - /analytics      -- strategy breakdown + score distribution
 * - /premarket_status -- pre-market check results
 */

import { useFirebase, useFirebaseList } from './useFirebase.js'

export function useTradeData() {
  // Portfolio: capital, net P&L, gross P&L, charges paid
  const { data: portfolio, loading: portfolioLoading } = useFirebase('portfolio', {
    current_capital: 0,
    initial_capital: 0,
    day_pnl: 0,          // NET P&L (after charges) — the real number
    day_gross_pnl: 0,    // Gross P&L (before charges)
    brokerage_paid_today: 0,
    total_pnl: 0,
    total_return_pct: 0,
    trades_today: 0,
  })

  // Signals: today's trading signals (ORB / VWAP / EMA / SR breakout)
  const { list: signals, loading: signalsLoading } = useFirebaseList('signals')

  // Trades: completed/closed trades (includes score, slippage, net_pnl)
  const { list: tradeHistory, loading: tradesLoading } = useFirebaseList('trades')

  // Open positions: currently active trades
  const { data: openPositionsRaw, loading: positionsLoading } = useFirebase('positions', {})

  // Bot status: running / stopped / error
  const { data: botStatus, loading: statusLoading } = useFirebase('status', { state: 'unknown' })

  // Market context: NIFTY direction, LTP, change %, VIX
  const { data: marketContext } = useFirebase('market_context', {
    nifty_direction: 'NEUTRAL',
    nifty_ltp: 0,
    nifty_change_pct: 0,
    vix: 0,
  })

  // Market regime: TRENDING / RANGE_BOUND / VOLATILE / GAP_DAY
  const { data: regime } = useFirebase('regime', {
    regime: 'UNKNOWN',
    nifty_change_pct: 0,
    vix: 0,
    size_multiplier: 1.0,
    determined_at: null,
  })

  // Analytics: strategy breakdown, score distribution, totals
  const { data: analytics } = useFirebase('analytics', {
    total_trades: 0,
    win_rate_pct: 0,
    total_net_pnl: 0,
    total_charges: 0,
    avg_score: 0,
    strategy_breakdown: {},
    score_distribution: {},
  })

  // Pre-market status: margin OK, holiday check, news loaded, etc.
  const { data: premarketStatus } = useFirebase('premarket_status', {
    checks_passed: false,
    is_trading_day: true,
    margin_ok: false,
    message: '',
  })

  // Kill switch: set by dashboard button
  const { data: killSwitch } = useFirebase('kill_switch', { active: false })

  // Today's report (end-of-day)
  const { data: todayReport } = useFirebase(
    `reports/${new Date().toISOString().split('T')[0]}`,
    null
  )

  // Convert open positions object { SYMBOL: data } to an array
  const openPositions = openPositionsRaw
    ? Object.entries(openPositionsRaw).map(([symbol, data]) => ({
        symbol,
        ...data,
      }))
    : []

  const isLoading =
    portfolioLoading || signalsLoading || tradesLoading || positionsLoading || statusLoading

  return {
    portfolio,
    signals,
    openPositions,
    tradeHistory,
    botStatus,
    marketContext,
    regime,
    analytics,
    premarketStatus,
    killSwitch,
    todayReport,
    isLoading,
  }
}
