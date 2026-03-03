/**
 * Trading calculation helpers.
 * Pure functions — no side effects, easy to test.
 */

/**
 * Calculate unrealized P&L for an open position.
 *
 * @param direction "LONG" or "SHORT"
 * @param entryPrice Price we bought/sold at
 * @param currentPrice Current market price
 * @param quantity Number of shares
 * @returns P&L in rupees (positive = profit, negative = loss)
 */
export function calcUnrealizedPnL(direction, entryPrice, currentPrice, quantity) {
  if (!entryPrice || !currentPrice || !quantity) return 0

  if (direction === 'LONG') {
    return (currentPrice - entryPrice) * quantity
  } else {
    return (entryPrice - currentPrice) * quantity
  }
}

/**
 * Calculate what percentage of the stop-loss distance has been traveled.
 * Used for progress bars in OpenPositions.
 *
 * Example: Entry=100, SL=95, Current=97 → 60% of the way to SL
 * Returns 0–100.
 */
export function calcRiskProgress(direction, entryPrice, stopLoss, currentPrice) {
  if (!entryPrice || !stopLoss || !currentPrice) return 0

  const totalRisk = Math.abs(entryPrice - stopLoss)
  if (totalRisk === 0) return 0

  if (direction === 'LONG') {
    const moved = entryPrice - currentPrice  // Negative = moving away from SL (good)
    const progress = (moved / totalRisk) * 100
    return Math.max(0, Math.min(100, progress))  // Clamp 0–100
  } else {
    const moved = currentPrice - entryPrice
    const progress = (moved / totalRisk) * 100
    return Math.max(0, Math.min(100, progress))
  }
}

/**
 * Calculate what percentage of the target distance has been traveled.
 * Used for progress bars showing how close we are to target.
 */
export function calcTargetProgress(direction, entryPrice, target, currentPrice) {
  if (!entryPrice || !target || !currentPrice) return 0

  const totalReward = Math.abs(target - entryPrice)
  if (totalReward === 0) return 0

  if (direction === 'LONG') {
    const moved = currentPrice - entryPrice
    const progress = (moved / totalReward) * 100
    return Math.max(0, Math.min(100, progress))
  } else {
    const moved = entryPrice - currentPrice
    const progress = (moved / totalReward) * 100
    return Math.max(0, Math.min(100, progress))
  }
}

/**
 * Calculate win rate percentage.
 * @param wins Number of winning trades
 * @param total Total number of trades
 * @returns Win rate as 0–100
 */
export function calcWinRate(wins, total) {
  if (!total || total === 0) return 0
  return Math.round((wins / total) * 100)
}

/**
 * Calculate risk-reward ratio from entry, SL, and target.
 * @returns Ratio as a string like "1:1.5"
 */
export function calcRiskReward(entryPrice, stopLoss, target) {
  const risk = Math.abs(entryPrice - stopLoss)
  const reward = Math.abs(target - entryPrice)
  if (risk === 0) return '0'
  return (reward / risk).toFixed(2)
}

/**
 * Aggregate trade history by strategy for StrategyBreakdown.
 * Returns: [{ strategy, trades, wins, winRate, totalPnL }]
 */
export function aggregateByStrategy(trades) {
  if (!trades || trades.length === 0) return []

  const map = {}
  trades.forEach((t) => {
    // Support both old (strategy) and new (strategy_name) field names
    const s = t.strategy_name || t.strategy || 'Unknown'
    // Use net_pnl if available (new field), fall back to pnl
    const pnl = t.net_pnl ?? t.pnl ?? 0

    if (!map[s]) map[s] = { strategy: s, trades: 0, wins: 0, totalPnL: 0 }
    map[s].trades++
    if (pnl > 0) map[s].wins++
    map[s].totalPnL += pnl
  })

  return Object.values(map).map((s) => ({
    ...s,
    totalPnL: Math.round(s.totalPnL * 100) / 100,
    winRate: calcWinRate(s.wins, s.trades),
  }))
}
