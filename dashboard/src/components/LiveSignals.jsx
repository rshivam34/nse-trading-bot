/**
 * LiveSignals — Shows real-time trading signals with 0-100 quality scores.
 *
 * New in this version:
 * - Score badge (0-100) with color coding:
 *   90-100 = gold "Exceptional"
 *   80-89  = green "Excellent"
 *   70-79  = blue "Good"
 * - Updated strategy colors (VWAP_BOUNCE, SR_BREAKOUT, EMA_CROSS)
 * - Score replaces the old 0-1 confidence bar
 */

import React from 'react'
import {
  formatCurrency,
  formatTime,
} from '../utils/formatters.js'

// Color config for signal score tiers
const SCORE_TIERS = [
  { min: 90, label: 'Exceptional', bg: 'bg-yellow-900/60', text: 'text-yellow-300', border: 'border-yellow-700/50' },
  { min: 80, label: 'Excellent',   bg: 'bg-green-900/60',  text: 'text-green-300',  border: 'border-green-700/50'  },
  { min: 70, label: 'Good',        bg: 'bg-blue-900/60',   text: 'text-blue-300',   border: 'border-blue-700/50'   },
  { min: 0,  label: 'Weak',        bg: 'bg-gray-800/60',   text: 'text-gray-400',   border: 'border-gray-700/50'   },
]

function getScoreTier(score) {
  return SCORE_TIERS.find((t) => score >= t.min) || SCORE_TIERS[SCORE_TIERS.length - 1]
}

// Color config for each strategy type
const STRATEGY_COLORS = {
  ORB:         'bg-indigo-900/60 text-indigo-300',
  VWAP_BOUNCE: 'bg-purple-900/60 text-purple-300',
  EMA_CROSS:   'bg-orange-900/60 text-orange-300',
  SR_BREAKOUT: 'bg-teal-900/60 text-teal-300',
}

export default function LiveSignals({ signals }) {
  if (!signals || signals.length === 0) {
    return (
      <div className="bg-gray-900 rounded-xl border border-gray-800 p-5">
        <SectionHeader count={0} />
        <div className="flex flex-col items-center justify-center py-10 text-gray-600">
          <span className="text-3xl mb-2">&#x1F4E1;</span>
          <p className="text-sm">Waiting for trading signals...</p>
          <p className="text-xs mt-1">Signals appear after 9:30 AM</p>
        </div>
      </div>
    )
  }

  const recent = signals.slice(0, 10)

  return (
    <div className="bg-gray-900 rounded-xl border border-gray-800 p-5">
      <SectionHeader count={signals.length} />
      <div className="space-y-3 mt-4 max-h-96 overflow-y-auto pr-1">
        {recent.map((signal) => (
          <SignalCard key={signal.id} signal={signal} />
        ))}
      </div>
    </div>
  )
}

function SectionHeader({ count }) {
  return (
    <div className="flex items-center justify-between">
      <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-widest">
        Live Signals
      </h2>
      {count > 0 && (
        <span className="flex items-center gap-1.5">
          <span className="w-1.5 h-1.5 rounded-full bg-green-400 live-dot" />
          <span className="text-xs text-green-400">{count} today</span>
        </span>
      )}
    </div>
  )
}

function SignalCard({ signal }) {
  const isLong = signal.direction === 'LONG'
  const dirColor = isLong ? 'text-green-400' : 'text-red-400'
  const dirBg = isLong
    ? 'bg-green-900/20 border-green-800/40'
    : 'bg-red-900/20 border-red-800/40'

  const score = signal.score || 0
  const tier = getScoreTier(score)
  const stratColor = STRATEGY_COLORS[signal.strategy_name || signal.strategy] || 'bg-gray-700 text-gray-300'

  return (
    <div className={`rounded-lg border p-3 ${dirBg}`}>
      {/* Row 1: Direction, stock name, strategy, score, time */}
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <span className={`font-bold text-sm ${dirColor}`}>
            {isLong ? '▲' : '▼'} {signal.direction}
          </span>
          <span className="font-semibold text-white text-sm">{signal.stock}</span>
          <span className={`text-xs px-1.5 py-0.5 rounded-full ${stratColor}`}>
            {signal.strategy_name || signal.strategy || 'N/A'}
          </span>
        </div>

        <div className="flex items-center gap-2">
          {/* Score badge — the main quality indicator */}
          <ScoreBadge score={score} tier={tier} />
          <span className="text-xs text-gray-500">{formatTime(signal.timestamp)}</span>
        </div>
      </div>

      {/* Row 2: Price levels */}
      <div className="grid grid-cols-3 gap-2 text-xs">
        <PriceBox label="Entry" value={formatCurrency(signal.entry_price)} />
        <PriceBox label="Stop Loss" value={formatCurrency(signal.stop_loss)} color="text-red-400" />
        <PriceBox label="Target" value={formatCurrency(signal.target)} color="text-green-400" />
      </div>

      {/* Row 3: R:R ratio + score breakdown hint */}
      <div className="flex items-center justify-between mt-2 text-xs text-gray-500">
        <span>
          R:R = 1:{signal.risk_reward || signal.risk_reward_ratio || '?'}
        </span>
        <span>Qty: {signal.quantity || '?'}</span>
      </div>

      {/* Signal reason */}
      {signal.reason && (
        <p className="text-xs text-gray-500 mt-1.5 leading-relaxed line-clamp-2">
          {signal.reason}
        </p>
      )}
    </div>
  )
}

function ScoreBadge({ score, tier }) {
  return (
    <div
      className={`flex flex-col items-center px-2 py-1 rounded-lg border ${tier.bg} ${tier.border}`}
      title={`Signal quality: ${tier.label}`}
    >
      <span className={`text-sm font-bold ${tier.text} leading-none`}>{score}</span>
      <span className={`text-[9px] ${tier.text} leading-none mt-0.5`}>{tier.label}</span>
    </div>
  )
}

function PriceBox({ label, value, color = 'text-gray-200' }) {
  return (
    <div className="bg-black/20 rounded p-1.5">
      <p className="text-gray-500 text-[10px] mb-0.5">{label}</p>
      <p className={`font-semibold ${color}`}>{value}</p>
    </div>
  )
}
