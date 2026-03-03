/**
 * StrategyBreakdown — Shows which strategies are working.
 *
 * Can use data from two sources (prefers analytics from Firebase):
 * 1. analytics.strategy_breakdown (from trade_analytics.py -- CSV-based, all-time)
 * 2. Aggregated from tradeHistory array (current session only)
 *
 * New: shows VWAP_BOUNCE and SR_BREAKOUT strategies in addition to ORB and EMA_CROSS.
 */

import React from 'react'
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from 'recharts'
import { formatPnL, pnlColorClass } from '../utils/formatters.js'
import { aggregateByStrategy } from '../utils/calculations.js'

const STRATEGY_COLORS = {
  ORB:         '#6366f1',  // Indigo
  VWAP_BOUNCE: '#a855f7',  // Purple
  EMA_CROSS:   '#f97316',  // Orange
  SR_BREAKOUT: '#14b8a6',  // Teal
}

// Short display names for the chart (keeps it compact)
const STRATEGY_SHORT = {
  ORB:         'ORB',
  VWAP_BOUNCE: 'VWAP',
  EMA_CROSS:   'EMA',
  SR_BREAKOUT: 'S/R',
}

export default function StrategyBreakdown({ trades, analytics }) {
  // Prefer analytics (all-time CSV data) over in-memory session data
  let data = []

  if (analytics?.strategy_breakdown && Object.keys(analytics.strategy_breakdown).length > 0) {
    // Build from Firebase analytics (persistent, all-time)
    data = Object.entries(analytics.strategy_breakdown).map(([strategy, stats]) => ({
      strategy,
      shortName: STRATEGY_SHORT[strategy] || strategy,
      trades: stats.trades || 0,
      wins: stats.wins || 0,
      winRate: stats.trades > 0 ? Math.round((stats.wins / stats.trades) * 100) : 0,
      totalPnL: stats.total_pnl || 0,
    }))
  } else {
    // Fall back to in-memory trade history (session only)
    data = aggregateByStrategy(trades || []).map((s) => ({
      ...s,
      shortName: STRATEGY_SHORT[s.strategy] || s.strategy,
    }))
  }

  const isAllTime = analytics?.strategy_breakdown && Object.keys(analytics.strategy_breakdown).length > 0

  return (
    <div className="bg-gray-900 rounded-xl border border-gray-800 p-5">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-widest">
          Strategy Breakdown
        </h2>
        {isAllTime && (
          <span className="text-[10px] text-gray-600">All-time</span>
        )}
      </div>

      {data.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-8 text-gray-600">
          <p className="text-sm">No trades to analyze yet</p>
          <p className="text-xs mt-1">Stats appear after your first trade</p>
        </div>
      ) : (
        <>
          {/* Bar chart: net P&L per strategy */}
          <div className="h-32 mb-4">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={data} barSize={28}>
                <XAxis
                  dataKey="shortName"
                  tick={{ fill: '#6b7280', fontSize: 10 }}
                  axisLine={false}
                  tickLine={false}
                />
                <YAxis hide />
                <Tooltip
                  contentStyle={{
                    backgroundColor: '#1f2937',
                    border: '1px solid #374151',
                    borderRadius: '8px',
                    fontSize: '11px',
                    color: '#e5e7eb',
                  }}
                  formatter={(value, name, props) => [
                    formatPnL(value),
                    `${props.payload.strategy} Net P&L`,
                  ]}
                />
                <Bar dataKey="totalPnL" radius={[4, 4, 0, 0]}>
                  {data.map((entry) => (
                    <Cell
                      key={entry.strategy}
                      fill={
                        entry.totalPnL >= 0
                          ? STRATEGY_COLORS[entry.strategy] || '#6366f1'
                          : '#ef4444'
                      }
                      opacity={0.8}
                    />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>

          {/* Strategy stat rows */}
          <div className="space-y-2">
            {data.map((s) => (
              <StrategyRow key={s.strategy} strategy={s} />
            ))}
          </div>

          {/* Score distribution (if analytics available) */}
          {analytics?.score_distribution && (
            <ScoreDistribution dist={analytics.score_distribution} />
          )}
        </>
      )}
    </div>
  )
}

function StrategyRow({ strategy }) {
  const { strategy: name, trades, wins, winRate, totalPnL } = strategy
  const pnlColor = pnlColorClass(totalPnL)
  const color = STRATEGY_COLORS[name] || '#6b7280'

  return (
    <div className="flex items-center gap-3 bg-gray-800 rounded-lg px-3 py-2">
      <div className="w-2.5 h-2.5 rounded-full flex-shrink-0" style={{ backgroundColor: color }} />
      <span className="text-xs font-semibold text-gray-300 w-20 truncate">{name}</span>
      <span className="text-xs text-gray-500">{trades}T</span>
      <div className="flex-1">
        <div className="h-1.5 bg-gray-700 rounded-full overflow-hidden">
          <div
            className="h-full rounded-full"
            style={{ width: `${winRate}%`, backgroundColor: color, opacity: 0.8 }}
          />
        </div>
      </div>
      <span className="text-xs text-gray-400 w-10 text-right">{winRate}%</span>
      <span className={`text-xs font-bold w-20 text-right ${pnlColor}`}>
        {formatPnL(totalPnL)}
      </span>
    </div>
  )
}

function ScoreDistribution({ dist }) {
  const total = (dist['70-79'] || 0) + (dist['80-89'] || 0) + (dist['90-100'] || 0)
  if (total === 0) return null

  return (
    <div className="mt-3 pt-3 border-t border-gray-800">
      <p className="text-xs text-gray-500 mb-2">Score distribution (trades taken)</p>
      <div className="flex gap-2 text-xs">
        <ScoreTile label="70-79" count={dist['70-79'] || 0} colorClass="bg-blue-900/60 text-blue-300" />
        <ScoreTile label="80-89" count={dist['80-89'] || 0} colorClass="bg-green-900/60 text-green-300" />
        <ScoreTile label="90-100" count={dist['90-100'] || 0} colorClass="bg-yellow-900/60 text-yellow-300" />
      </div>
    </div>
  )
}

function ScoreTile({ label, count, colorClass }) {
  return (
    <div className={`flex-1 rounded p-2 text-center ${colorClass}`}>
      <p className="font-bold">{count}</p>
      <p className="text-[10px] opacity-80">{label}</p>
    </div>
  )
}
