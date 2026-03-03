/**
 * TradeHistory — Table of closed trades with score, slippage, and net P&L.
 *
 * New columns:
 * - Score: the signal quality score (0-100) that triggered the trade
 * - Net P&L: real profit after brokerage/charges (not gross)
 * - Slippage: difference between signal price and actual fill price
 */

import React, { useState } from 'react'
import {
  formatCurrency,
  formatPnL,
  formatTime,
  pnlColorClass,
} from '../utils/formatters.js'

const STRATEGY_COLORS = {
  ORB:         'bg-indigo-900/60 text-indigo-300',
  VWAP_BOUNCE: 'bg-purple-900/60 text-purple-300',
  EMA_CROSS:   'bg-orange-900/60 text-orange-300',
  SR_BREAKOUT: 'bg-teal-900/60 text-teal-300',
}

export default function TradeHistory({ trades }) {
  const [page, setPage] = useState(0)
  const PER_PAGE = 10

  if (!trades || trades.length === 0) {
    return (
      <div className="bg-gray-900 rounded-xl border border-gray-800 p-5">
        <SectionHeader count={0} />
        <div className="flex flex-col items-center justify-center py-10 text-gray-600">
          <p className="text-sm">No completed trades yet</p>
        </div>
      </div>
    )
  }

  const totalPages = Math.ceil(trades.length / PER_PAGE)
  const paginated = trades.slice(page * PER_PAGE, (page + 1) * PER_PAGE)

  // Use net_pnl if available (new field), fall back to pnl
  const getNetPnl = (t) => t.net_pnl ?? t.pnl ?? 0

  const wins = trades.filter((t) => getNetPnl(t) > 0).length
  const totalNetPnL = trades.reduce((sum, t) => sum + getNetPnl(t), 0)
  const winRate = trades.length > 0 ? Math.round((wins / trades.length) * 100) : 0

  const scores = trades.map((t) => t.score || 0).filter((s) => s > 0)
  const avgScore = scores.length > 0 ? Math.round(scores.reduce((a, b) => a + b, 0) / scores.length) : 0

  return (
    <div className="bg-gray-900 rounded-xl border border-gray-800 p-5">
      <SectionHeader count={trades.length} />

      {/* Quick stats */}
      <div className="grid grid-cols-3 gap-2 mt-3 mb-4">
        <QuickStat label="Win Rate" value={`${winRate}%`} />
        <QuickStat
          label="Net P&L"
          value={formatPnL(totalNetPnL)}
          colorClass={pnlColorClass(totalNetPnL)}
        />
        <QuickStat
          label="Avg Score"
          value={avgScore > 0 ? `${avgScore}/100` : '--'}
          colorClass={avgScore >= 80 ? 'text-green-400' : avgScore >= 70 ? 'text-blue-400' : 'text-gray-400'}
        />
      </div>

      {/* Trade table */}
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-gray-500 border-b border-gray-800">
              <th className="text-left pb-2 font-medium">Stock</th>
              <th className="text-left pb-2 font-medium">Dir</th>
              <th className="text-right pb-2 font-medium">Entry</th>
              <th className="text-right pb-2 font-medium">Exit</th>
              <th className="text-right pb-2 font-medium">Net P&L</th>
              <th className="text-right pb-2 font-medium">Score</th>
              <th className="text-left pb-2 font-medium">Strategy</th>
              <th className="text-right pb-2 font-medium">Time</th>
            </tr>
          </thead>
          <tbody>
            {paginated.map((trade) => (
              <TradeRow key={trade.id} trade={trade} />
            ))}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex justify-center gap-2 mt-3">
          <button
            onClick={() => setPage(Math.max(0, page - 1))}
            disabled={page === 0}
            className="px-2 py-1 text-xs bg-gray-800 hover:bg-gray-700 disabled:opacity-30 rounded"
          >
            Prev
          </button>
          <span className="text-xs text-gray-500 py-1">
            {page + 1} / {totalPages}
          </span>
          <button
            onClick={() => setPage(Math.min(totalPages - 1, page + 1))}
            disabled={page === totalPages - 1}
            className="px-2 py-1 text-xs bg-gray-800 hover:bg-gray-700 disabled:opacity-30 rounded"
          >
            Next
          </button>
        </div>
      )}
    </div>
  )
}

function TradeRow({ trade }) {
  const netPnl = trade.net_pnl ?? trade.pnl ?? 0
  const pnlColor = pnlColorClass(netPnl)
  const isLong = trade.direction === 'LONG'
  const exitReason = trade.exit_reason || ''

  const exitBadge =
    exitReason === 'TARGET'
      ? 'text-green-400'
      : exitReason === 'STOP_LOSS' || exitReason === 'EFFECTIVE_SL'
      ? 'text-red-400'
      : exitReason === 'TRAILING_SL'
      ? 'text-orange-400'
      : 'text-gray-500'

  const score = trade.score || 0
  const scoreColor =
    score >= 90 ? 'text-yellow-400' :
    score >= 80 ? 'text-green-400' :
    score >= 70 ? 'text-blue-400' :
    'text-gray-500'

  const strategy = trade.strategy_name || trade.strategy || '-'

  return (
    <tr className="border-b border-gray-800/50 hover:bg-gray-800/30" title={exitReason}>
      <td className="py-2 font-semibold text-gray-200">{trade.stock}</td>
      <td className="py-2">
        <span className={`font-bold text-[10px] ${isLong ? 'text-green-400' : 'text-red-400'}`}>
          {isLong ? '▲ L' : '▼ S'}
        </span>
      </td>
      <td className="py-2 text-right text-gray-300">
        {formatCurrency(trade.entry_price || trade.entry)}
      </td>
      <td className="py-2 text-right">
        <span className={exitBadge}>{formatCurrency(trade.exit_price || trade.exit)}</span>
      </td>
      <td className={`py-2 text-right font-bold ${pnlColor}`}>
        {formatPnL(netPnl)}
      </td>
      <td className={`py-2 text-right font-semibold ${scoreColor}`}>
        {score > 0 ? score : '--'}
      </td>
      <td className="py-2">
        <StrategyBadge name={strategy} />
      </td>
      <td className="py-2 text-right text-gray-500">
        {formatTime(trade.pushed_at || trade.executed_at || trade.timestamp)}
      </td>
    </tr>
  )
}

function StrategyBadge({ name }) {
  const cls = STRATEGY_COLORS[name] || 'bg-gray-700/60 text-gray-400'
  return (
    <span className={`text-[10px] px-1.5 py-0.5 rounded ${cls}`}>{name || '-'}</span>
  )
}

function QuickStat({ label, value, colorClass = 'text-gray-200' }) {
  return (
    <div className="bg-gray-800 rounded-lg p-2 text-center">
      <p className="text-[10px] text-gray-500 mb-0.5">{label}</p>
      <p className={`text-xs font-bold ${colorClass}`}>{value}</p>
    </div>
  )
}

function SectionHeader({ count }) {
  return (
    <div className="flex items-center justify-between">
      <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-widest">
        Trade History
      </h2>
      {count > 0 && (
        <span className="text-xs text-gray-500">{count} trades</span>
      )}
    </div>
  )
}
