/**
 * PerformanceCard — Daily P&L summary showing gross, charges, and net P&L.
 *
 * Why show all three?
 * At small capital (Rs.1K), brokerage charges (Rs.35-50/trade) can eat
 * a huge % of your profits. You need to see the real picture:
 *   Gross P&L:  +Rs.80   (what price movement made)
 *   Charges:    -Rs.34   (what broker took)
 *   Net P&L:    +Rs.46   (what YOU actually made)
 */

import React from 'react'
import { formatCurrency, formatPnL, formatPercent, pnlColorClass } from '../utils/formatters.js'

const MAX_TRADES = 3  // Max trades per day (from config)

export default function PerformanceCard({ portfolio }) {
  const {
    current_capital = 0,
    initial_capital = 0,
    day_pnl = 0,              // NET P&L (after charges)
    day_gross_pnl = 0,        // Gross P&L (before charges)
    brokerage_paid_today = 0, // Total charges paid today
    total_pnl = 0,
    total_return_pct = 0,
    trades_today = 0,
  } = portfolio || {}

  const netPnlColor = pnlColorClass(day_pnl)
  const grossPnlColor = pnlColorClass(day_gross_pnl)
  const totalPnlColor = pnlColorClass(total_pnl)

  return (
    <div className="bg-gray-900 rounded-xl border border-gray-800 p-5">
      <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-widest mb-4">
        Portfolio Overview
      </h2>

      {/* Current capital -- big prominent number */}
      <div className="mb-4">
        <p className="text-sm text-gray-400">Current Capital</p>
        <p className="text-3xl font-bold text-white mt-1">
          {formatCurrency(current_capital)}
        </p>
        {initial_capital > 0 && (
          <p className="text-xs text-gray-500 mt-0.5">
            Started with {formatCurrency(initial_capital)}
          </p>
        )}
      </div>

      {/* Today's P&L breakdown: gross → charges → net */}
      <div className="bg-gray-800/60 rounded-lg p-3 mb-3 space-y-2">
        <p className="text-xs text-gray-500 uppercase tracking-wider mb-2">Today's P&L</p>

        <PnlRow
          label="Gross P&L"
          value={formatPnL(day_gross_pnl)}
          colorClass={grossPnlColor}
          tooltip="Price movement × quantity (before fees)"
        />

        <PnlRow
          label="Charges"
          value={brokerage_paid_today > 0 ? `-${formatCurrency(brokerage_paid_today)}` : formatCurrency(0)}
          colorClass={brokerage_paid_today > 0 ? 'text-orange-400' : 'text-gray-400'}
          tooltip="Brokerage + STT + GST + exchange fees"
        />

        <div className="border-t border-gray-700 pt-2">
          <PnlRow
            label="Net P&L"
            value={formatPnL(day_pnl)}
            colorClass={netPnlColor}
            bold
            tooltip="What you actually made after all charges"
          />
        </div>
      </div>

      {/* Total return since bot started */}
      <div className="grid grid-cols-2 gap-2 mb-3">
        <StatBox
          label="Total P&L"
          value={formatPnL(total_pnl)}
          colorClass={totalPnlColor}
        />
        <StatBox
          label="Total Return"
          value={formatPercent(total_return_pct)}
          colorClass={totalPnlColor}
        />
      </div>

      {/* Trades taken today with progress bar */}
      <div className="pt-2 border-t border-gray-800">
        <div className="flex items-center justify-between mb-1.5">
          <span className="text-xs text-gray-500">Trades today</span>
          <span className="text-sm font-semibold text-white">
            {trades_today} / {MAX_TRADES}
          </span>
        </div>
        <div className="h-1.5 bg-gray-800 rounded-full overflow-hidden">
          <div
            className={`h-full rounded-full transition-all duration-500 ${
              trades_today >= MAX_TRADES
                ? 'bg-red-500'
                : trades_today >= MAX_TRADES - 1
                ? 'bg-yellow-500'
                : 'bg-indigo-500'
            }`}
            style={{ width: `${Math.min((trades_today / MAX_TRADES) * 100, 100)}%` }}
          />
        </div>
        {trades_today >= MAX_TRADES && (
          <p className="text-xs text-orange-400 mt-1">
            Daily trade limit reached. No new trades.
          </p>
        )}
      </div>
    </div>
  )
}

function PnlRow({ label, value, colorClass, bold = false, tooltip }) {
  return (
    <div className="flex items-center justify-between" title={tooltip}>
      <span className={`text-xs ${bold ? 'text-gray-300 font-medium' : 'text-gray-500'}`}>
        {label}
      </span>
      <span className={`text-sm ${bold ? 'font-bold' : 'font-semibold'} ${colorClass}`}>
        {value}
      </span>
    </div>
  )
}

function StatBox({ label, value, colorClass }) {
  return (
    <div className="bg-gray-800 rounded-lg p-3">
      <p className="text-xs text-gray-500 mb-1">{label}</p>
      <p className={`text-sm font-bold ${colorClass}`}>{value}</p>
    </div>
  )
}
