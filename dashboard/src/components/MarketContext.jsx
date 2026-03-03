/**
 * MarketContext — NIFTY direction + market regime + VIX indicator.
 *
 * New in this version:
 * - Market regime badge (TRENDING / RANGE_BOUND / VOLATILE / GAP_DAY)
 * - VIX indicator (India VIX level -- higher = more volatile/risky)
 * - Regime is determined at 10:30 AM and affects position sizing
 */

import React from 'react'
import { formatPercent } from '../utils/formatters.js'

const DIRECTION_CONFIG = {
  BULLISH: {
    icon: '↑',
    label: 'BULLISH',
    bg: 'bg-green-900/40',
    border: 'border-green-700/50',
    text: 'text-green-400',
    dot: 'bg-green-400',
    description: 'NIFTY is trending up. Bot may take LONG trades.',
  },
  BEARISH: {
    icon: '↓',
    label: 'BEARISH',
    bg: 'bg-red-900/40',
    border: 'border-red-700/50',
    text: 'text-red-400',
    dot: 'bg-red-400',
    description: 'NIFTY is trending down. Bot may take SHORT trades.',
  },
  NEUTRAL: {
    icon: '→',
    label: 'NEUTRAL',
    bg: 'bg-gray-800',
    border: 'border-gray-700',
    text: 'text-gray-300',
    dot: 'bg-gray-400',
    description: 'NIFTY is sideways. Bot trades with extra caution.',
  },
}

const REGIME_CONFIG = {
  TRENDING: {
    label: 'TRENDING',
    bg: 'bg-green-900/30',
    text: 'text-green-400',
    desc: 'Strong momentum. Position sizes at 110% (more aggressive).',
  },
  RANGE_BOUND: {
    label: 'RANGE-BOUND',
    bg: 'bg-blue-900/30',
    text: 'text-blue-400',
    desc: 'Choppy. Normal position sizing.',
  },
  VOLATILE: {
    label: 'VOLATILE',
    bg: 'bg-orange-900/30',
    text: 'text-orange-400',
    desc: 'VIX high. Position sizes at 70%, wider SL, score threshold raised.',
  },
  GAP_DAY: {
    label: 'GAP DAY',
    bg: 'bg-yellow-900/30',
    text: 'text-yellow-400',
    desc: 'Large gap from yesterday. Waiting for gap fill before trading.',
  },
  UNKNOWN: {
    label: 'DETERMINING...',
    bg: 'bg-gray-800',
    text: 'text-gray-500',
    desc: 'Regime determined at 10:30 AM.',
  },
}

export default function MarketContext({ marketContext, botStatus, regime }) {
  const direction = marketContext?.nifty_direction || 'NEUTRAL'
  const niftyLtp = marketContext?.nifty_ltp || 0
  const changePct = marketContext?.nifty_change_pct || 0
  const vix = marketContext?.vix || regime?.vix || 0

  const cfg = DIRECTION_CONFIG[direction] || DIRECTION_CONFIG.NEUTRAL
  const regimeName = regime?.regime || 'UNKNOWN'
  const regimeCfg = REGIME_CONFIG[regimeName] || REGIME_CONFIG.UNKNOWN
  const determinedAt = regime?.determined_at

  const botState = botStatus?.state || 'unknown'

  return (
    <div className="bg-gray-900 rounded-xl border border-gray-800 p-5">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-widest">
          Market Context
        </h2>
        {/* Bot status */}
        <div className="flex items-center gap-2">
          <span
            className={`w-2 h-2 rounded-full ${
              botState === 'running' ? 'bg-green-400 live-dot' : 'bg-gray-600'
            }`}
          />
          <span className="text-xs text-gray-400 capitalize">{botState}</span>
        </div>
      </div>

      {/* NIFTY direction */}
      <div className={`rounded-lg border p-3 mb-3 ${cfg.bg} ${cfg.border}`}>
        <div className="flex items-center gap-3">
          <span className={`text-2xl font-bold ${cfg.text}`}>{cfg.icon}</span>
          <div>
            <p className={`text-base font-bold ${cfg.text}`}>{cfg.label}</p>
            {niftyLtp > 0 && (
              <p className="text-xs text-gray-400 mt-0.5">
                NIFTY 50: {niftyLtp.toLocaleString('en-IN')}
                <span className={`ml-2 ${cfg.text}`}>{formatPercent(changePct)}</span>
              </p>
            )}
          </div>
        </div>
        <p className="text-xs text-gray-500 mt-1.5">{cfg.description}</p>
      </div>

      {/* Market regime */}
      <div className={`rounded-lg p-3 mb-3 ${regimeCfg.bg}`}>
        <div className="flex items-center justify-between mb-1">
          <span className="text-xs text-gray-500">Market Regime</span>
          {determinedAt && (
            <span className="text-[10px] text-gray-600">
              Set at {determinedAt}
            </span>
          )}
        </div>
        <p className={`text-sm font-bold ${regimeCfg.text}`}>{regimeCfg.label}</p>
        <p className="text-xs text-gray-500 mt-0.5">{regimeCfg.desc}</p>
        {regime?.size_multiplier && regime.size_multiplier !== 1.0 && (
          <p className={`text-xs mt-1 ${regimeCfg.text}`}>
            Size: {regime.size_multiplier}x
          </p>
        )}
      </div>

      {/* VIX indicator */}
      {vix > 0 && (
        <div className="rounded-lg bg-gray-800 p-3">
          <div className="flex items-center justify-between">
            <span className="text-xs text-gray-500">India VIX</span>
            <span
              className={`text-sm font-bold ${
                vix > 20
                  ? 'text-red-400'
                  : vix > 15
                  ? 'text-orange-400'
                  : 'text-green-400'
              }`}
            >
              {vix.toFixed(1)}
            </span>
          </div>
          <div className="mt-1.5 h-1.5 bg-gray-700 rounded-full overflow-hidden">
            <div
              className={`h-full rounded-full ${
                vix > 20 ? 'bg-red-500' : vix > 15 ? 'bg-orange-500' : 'bg-green-500'
              }`}
              style={{ width: `${Math.min((vix / 30) * 100, 100)}%` }}
            />
          </div>
          <div className="flex justify-between text-[10px] text-gray-600 mt-0.5">
            <span>Low (0)</span>
            <span>High (&gt;20)</span>
          </div>
        </div>
      )}
    </div>
  )
}
