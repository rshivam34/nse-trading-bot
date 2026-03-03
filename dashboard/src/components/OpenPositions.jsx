/**
 * OpenPositions — Shows active trades with trailing SL indicator.
 *
 * New in this version:
 * - Trailing SL indicator: shows "Trailing Active" badge when trailing SL is on
 * - Shows partial exit status (remaining qty after 1x RR exit)
 * - Shows hold time in minutes
 */

import React from 'react'
import {
  formatCurrency,
  formatPnL,
  formatTime,
  pnlColorClass,
} from '../utils/formatters.js'
import { calcTargetProgress, calcRiskProgress } from '../utils/calculations.js'

export default function OpenPositions({ openPositions }) {
  if (!openPositions || openPositions.length === 0) {
    return (
      <div className="bg-gray-900 rounded-xl border border-gray-800 p-5">
        <SectionHeader count={0} />
        <div className="flex flex-col items-center justify-center py-10 text-gray-600">
          <p className="text-sm">No open positions</p>
          <p className="text-xs mt-1">Trades appear here when executed</p>
        </div>
      </div>
    )
  }

  return (
    <div className="bg-gray-900 rounded-xl border border-gray-800 p-5">
      <SectionHeader count={openPositions.length} />
      <div className="space-y-4 mt-4">
        {openPositions.map((pos) => (
          <PositionCard key={pos.symbol || pos.stock} position={pos} />
        ))}
      </div>
    </div>
  )
}

function SectionHeader({ count }) {
  return (
    <div className="flex items-center justify-between">
      <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-widest">
        Open Positions
      </h2>
      {count > 0 && (
        <span className="text-xs font-semibold bg-indigo-900/60 text-indigo-300 px-2 py-0.5 rounded-full">
          {count} OPEN
        </span>
      )}
    </div>
  )
}

function PositionCard({ position }) {
  const {
    stock,
    symbol,
    direction,
    entry_price,
    entry,
    stop_loss,
    effective_sl,    // After partial exit, SL moved to entry
    trailing_sl,     // Active trailing SL price
    trailing_active, // True when trailing SL is on
    target,
    quantity = 1,
    remaining_quantity,
    partial_exit_done,
    current_price,
    unrealized_pnl = 0,
    realized_pnl = 0,
    updated_at,
    hold_time_min,
    score,
  } = position

  const stockName = stock || symbol || 'Unknown'
  const isLong = direction === 'LONG'
  const entryPrice = entry_price || entry || 0
  const currentPrice = current_price || entryPrice || 0
  const pnl = unrealized_pnl

  // Which SL is currently active?
  const activeSl = trailing_active && trailing_sl
    ? trailing_sl
    : effective_sl && effective_sl !== 0
    ? effective_sl
    : stop_loss

  const pnlColor = pnlColorClass(pnl)
  const dirColor = isLong ? 'text-green-400' : 'text-red-400'
  const dirBorderColor = isLong ? 'border-l-green-500' : 'border-l-red-500'

  const targetProgress = calcTargetProgress(direction, entryPrice, target, currentPrice)
  const slProgress = calcRiskProgress(direction, entryPrice, activeSl, currentPrice)

  return (
    <div className={`bg-gray-800 rounded-lg border-l-4 ${dirBorderColor} p-4`}>
      {/* Header row */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2 flex-wrap">
          <span className={`text-xs font-bold ${dirColor}`}>
            {isLong ? '▲ LONG' : '▼ SHORT'}
          </span>
          <span className="font-bold text-white">{stockName}</span>

          {/* Remaining quantity */}
          <span className="text-xs text-gray-400">
            {remaining_quantity != null ? (
              partial_exit_done
                ? `${remaining_quantity} left (50% exited)`
                : `x ${quantity}`
            ) : `x ${quantity}`}
          </span>

          {/* Trailing SL badge */}
          {trailing_active && (
            <span className="text-[10px] bg-orange-900/60 text-orange-300 px-1.5 py-0.5 rounded">
              Trailing SL
            </span>
          )}

          {/* Score badge */}
          {score > 0 && (
            <span className={`text-[10px] px-1.5 py-0.5 rounded ${
              score >= 90 ? 'bg-yellow-900/60 text-yellow-300' :
              score >= 80 ? 'bg-green-900/60 text-green-300' :
              'bg-blue-900/60 text-blue-300'
            }`}>
              {score}/100
            </span>
          )}
        </div>

        <div className="text-right">
          <p className={`text-lg font-bold ${pnlColor}`}>{formatPnL(pnl)}</p>
          {realized_pnl > 0 && (
            <p className="text-xs text-gray-500">
              +{formatCurrency(realized_pnl)} realized
            </p>
          )}
          {hold_time_min != null && (
            <p className="text-xs text-gray-600">{Math.round(hold_time_min)}m</p>
          )}
        </div>
      </div>

      {/* Price levels */}
      <div className="grid grid-cols-3 gap-2 text-xs mb-3">
        <div className="text-center">
          <p className="text-gray-500 mb-0.5">Entry</p>
          <p className="font-semibold text-gray-200">{formatCurrency(entryPrice)}</p>
        </div>
        <div className="text-center">
          <p className="text-gray-500 mb-0.5">Current</p>
          <p className={`font-bold ${pnlColor}`}>{formatCurrency(currentPrice)}</p>
        </div>
        <div className="text-center">
          <p className="text-gray-500 mb-0.5">Target</p>
          <p className="font-semibold text-green-400">{formatCurrency(target)}</p>
        </div>
      </div>

      {/* Target progress bar */}
      <div className="mb-1.5">
        <div className="flex justify-between text-xs text-gray-500 mb-1">
          <span>Progress to target</span>
          <span>{Math.round(targetProgress)}%</span>
        </div>
        <div className="h-1.5 bg-gray-700 rounded-full overflow-hidden">
          <div
            className="h-full bg-green-500 rounded-full transition-all duration-500"
            style={{ width: `${targetProgress}%` }}
          />
        </div>
      </div>

      {/* Active SL bar */}
      <div>
        <div className="flex justify-between text-xs text-gray-500 mb-1">
          <span className="flex items-center gap-1">
            {trailing_active ? (
              <span className="text-orange-400">Trailing SL</span>
            ) : effective_sl && effective_sl !== stop_loss ? (
              <span className="text-blue-400">SL (at entry)</span>
            ) : (
              'Stop Loss'
            )}
          </span>
          <span className={trailing_active ? 'text-orange-400' : 'text-red-400'}>
            {formatCurrency(activeSl)}
          </span>
        </div>
        <div className="h-1 bg-gray-700 rounded-full overflow-hidden">
          <div
            className={`h-full rounded-full transition-all duration-500 ${
              trailing_active ? 'bg-orange-500' : 'bg-red-500'
            }`}
            style={{ width: `${slProgress}%`, opacity: slProgress > 60 ? 1 : 0.5 }}
          />
        </div>
      </div>
    </div>
  )
}
