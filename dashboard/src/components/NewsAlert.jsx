/**
 * NewsAlert — Shows news sentiment and stocks to skip today.
 *
 * The bot fetches news via Marketaux API at 9 AM.
 * This component shows:
 * - Global risk day warning (RBI policy, budget, FII selloff, etc.)
 * - Stocks with negative news (will be skipped by bot)
 * - Stocks with positive news (higher quality setups expected)
 */

import React, { useState } from 'react'

export default function NewsAlert({ newsSentiment }) {
  const [expanded, setExpanded] = useState(false)

  if (!newsSentiment || !newsSentiment.data) {
    return null  // Don't show anything if no news data loaded yet
  }

  const { data, fetched_at } = newsSentiment
  const isGlobalRiskDay = data.global_risk_day === true

  // Separate stocks by sentiment
  const stocks = Object.entries(data).filter(([key]) => key !== 'global_risk_day')
  const skipStocks = stocks.filter(([, v]) => v?.skip_today)
  const positiveStocks = stocks.filter(([, v]) => v?.sentiment === 'positive' && !v?.skip_today)
  const negativeStocks = stocks.filter(([, v]) => v?.sentiment === 'negative' && !v?.skip_today)

  // Only render if there's something worth showing
  const hasAlerts = isGlobalRiskDay || skipStocks.length > 0 || negativeStocks.length > 0

  if (!hasAlerts && positiveStocks.length === 0) return null

  return (
    <div className="bg-gray-900 rounded-xl border border-gray-800 p-5">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-widest">
          News Sentiment
        </h2>
        <div className="flex items-center gap-2">
          {fetched_at && (
            <span className="text-[10px] text-gray-600">
              {new Date(fetched_at).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', hour12: false })}
            </span>
          )}
          <button
            onClick={() => setExpanded(!expanded)}
            className="text-xs text-gray-500 hover:text-gray-300"
          >
            {expanded ? 'less' : 'more'}
          </button>
        </div>
      </div>

      {/* Global risk day banner */}
      {isGlobalRiskDay && (
        <div className="bg-red-900/30 border border-red-700/50 rounded-lg p-3 mb-3">
          <p className="text-xs font-semibold text-red-400">
            Global Risk Day Detected
          </p>
          <p className="text-xs text-gray-400 mt-0.5">
            Major market event detected (RBI policy / budget / FII selloff).
            Bot is extra cautious today.
          </p>
        </div>
      )}

      {/* Stocks to skip */}
      {skipStocks.length > 0 && (
        <div className="mb-3">
          <p className="text-xs text-gray-500 mb-1.5">
            Skipped today (earnings / major news):
          </p>
          <div className="flex flex-wrap gap-1">
            {skipStocks.map(([symbol]) => (
              <span
                key={symbol}
                className="text-[10px] bg-red-900/30 text-red-400 border border-red-800/50 px-2 py-0.5 rounded"
              >
                {symbol}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Positive sentiment stocks */}
      {positiveStocks.length > 0 && (
        <div className="mb-2">
          <p className="text-xs text-gray-500 mb-1.5">Positive news:</p>
          <div className="flex flex-wrap gap-1">
            {positiveStocks.slice(0, expanded ? undefined : 5).map(([symbol, data]) => (
              <span
                key={symbol}
                className="text-[10px] bg-green-900/30 text-green-400 border border-green-800/50 px-2 py-0.5 rounded"
                title={data.headlines?.[0] || ''}
              >
                {symbol}
              </span>
            ))}
            {!expanded && positiveStocks.length > 5 && (
              <span className="text-[10px] text-gray-600 py-0.5">
                +{positiveStocks.length - 5} more
              </span>
            )}
          </div>
        </div>
      )}

      {/* Negative sentiment (not skipped but flagged) */}
      {expanded && negativeStocks.length > 0 && (
        <div>
          <p className="text-xs text-gray-500 mb-1.5">Negative sentiment (proceed with caution):</p>
          <div className="flex flex-wrap gap-1">
            {negativeStocks.map(([symbol, data]) => (
              <span
                key={symbol}
                className="text-[10px] bg-orange-900/30 text-orange-400 border border-orange-800/50 px-2 py-0.5 rounded"
                title={data.headlines?.[0] || ''}
              >
                {symbol}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
