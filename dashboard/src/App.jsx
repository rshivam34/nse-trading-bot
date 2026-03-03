/**
 * App.jsx -- Main Dashboard Layout
 * ==================================
 * Assembles all dashboard components. All data from Firebase via useTradeData().
 *
 * Layout (dark theme):
 * ┌──────────────────────────────────────────┐
 * │  Header: Logo + Clock + Bot Status       │
 * ├─────────────┬────────────────────────────┤
 * │ Left (1/3)  │  Right (2/3)               │
 * │ - Portfolio │  - Open Positions (if any) │
 * │ - Market Ctx│  - Live Signals            │
 * │ - News Alert│  - Strategy Breakdown      │
 * │ - Capital   │  - Trade History           │
 * │ - Kill Switch│                           │
 * └─────────────┴────────────────────────────┘
 *
 * New data: regime, analytics, premarket_status, news_sentiment
 */

import React from 'react'
import { useTradeData } from './hooks/useTradeData.js'
import PerformanceCard from './components/PerformanceCard.jsx'
import MarketContext from './components/MarketContext.jsx'
import CapitalInput from './components/CapitalInput.jsx'
import KillSwitch from './components/KillSwitch.jsx'
import LiveSignals from './components/LiveSignals.jsx'
import OpenPositions from './components/OpenPositions.jsx'
import TradeHistory from './components/TradeHistory.jsx'
import StrategyBreakdown from './components/StrategyBreakdown.jsx'
import NewsAlert from './components/NewsAlert.jsx'

export default function App() {
  const {
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
    isLoading,
  } = useTradeData()

  const botState = botStatus?.state || 'unknown'
  const isLive = botState === 'running'

  // Show premarket banner if bot hasn't started yet and there's a message
  const showPremarketBanner =
    !isLive && premarketStatus?.message && botState !== 'stopped'

  return (
    <div className="min-h-screen bg-gray-950">
      {/* Header */}
      <header className="border-b border-gray-800 bg-gray-900/80 backdrop-blur sticky top-0 z-10">
        <div className="max-w-7xl mx-auto px-4 py-3 flex items-center justify-between">
          {/* Logo */}
          <div className="flex items-center gap-3">
            <div>
              <h1 className="text-sm font-bold text-white leading-none">NSE Trading Bot</h1>
              <p className="text-[10px] text-gray-500 leading-none mt-0.5">Intraday Dashboard</p>
            </div>
          </div>

          {/* Center: IST clock */}
          <LiveClock />

          {/* Right: Bot status */}
          <div className="flex items-center gap-2">
            <div
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-semibold ${
                isLive
                  ? 'bg-green-900/50 text-green-400 border border-green-700/50'
                  : 'bg-gray-800 text-gray-400 border border-gray-700'
              }`}
            >
              <span
                className={`w-2 h-2 rounded-full ${isLive ? 'bg-green-400 live-dot' : 'bg-gray-500'}`}
              />
              {isLive ? 'BOT LIVE' : botState.toUpperCase()}
            </div>
          </div>
        </div>
      </header>

      {/* Loading spinner */}
      {isLoading && (
        <div className="max-w-7xl mx-auto px-4 pt-4">
          <div className="bg-gray-900 border border-gray-800 rounded-xl p-4 flex items-center gap-3">
            <div className="w-4 h-4 rounded-full border-2 border-indigo-500 border-t-transparent animate-spin" />
            <span className="text-sm text-gray-400">Connecting to Firebase...</span>
          </div>
        </div>
      )}

      {/* Pre-market status banner (shown before bot starts) */}
      {showPremarketBanner && (
        <div className="max-w-7xl mx-auto px-4 pt-4">
          <div
            className={`rounded-xl border p-4 text-sm ${
              premarketStatus.checks_passed
                ? 'bg-green-900/20 border-green-800/50 text-green-300'
                : premarketStatus.is_trading_day === false
                ? 'bg-orange-900/20 border-orange-800/50 text-orange-300'
                : 'bg-gray-900 border-gray-800 text-gray-400'
            }`}
          >
            {premarketStatus.message}
          </div>
        </div>
      )}

      {/* Main content */}
      <main className="max-w-7xl mx-auto px-4 py-5">
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">

          {/* Left sidebar */}
          <div className="space-y-4">
            <PerformanceCard portfolio={portfolio} />
            <MarketContext
              marketContext={marketContext}
              botStatus={botStatus}
              regime={regime}
            />
            <NewsAlert newsSentiment={null} />
            <CapitalInput portfolio={portfolio} />
            <KillSwitch killSwitch={killSwitch} />
          </div>

          {/* Main content area */}
          <div className="lg:col-span-2 space-y-4">
            {/* Open positions -- shown prominently when trades are active */}
            {openPositions && openPositions.length > 0 && (
              <OpenPositions openPositions={openPositions} />
            )}

            <LiveSignals signals={signals} />

            <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
              <StrategyBreakdown trades={tradeHistory} analytics={analytics} />
              <TradeHistory trades={tradeHistory} />
            </div>
          </div>
        </div>
      </main>

      {/* Footer */}
      <footer className="border-t border-gray-800 mt-8 py-4">
        <div className="max-w-7xl mx-auto px-4 flex items-center justify-between text-xs text-gray-600">
          <span>NSE Trading Bot</span>
          <span>Firebase Realtime DB · Auto-updates every 5s</span>
        </div>
      </footer>
    </div>
  )
}

/**
 * LiveClock -- shows current IST time with market session indicator.
 */
function LiveClock() {
  const [now, setNow] = React.useState(new Date())

  React.useEffect(() => {
    const timer = setInterval(() => setNow(new Date()), 1000)
    return () => clearInterval(timer)
  }, [])

  const timeStr = now.toLocaleTimeString('en-IN', {
    timeZone: 'Asia/Kolkata',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  })

  const dateStr = now.toLocaleDateString('en-IN', {
    timeZone: 'Asia/Kolkata',
    weekday: 'short',
    day: 'numeric',
    month: 'short',
  })

  // Market session detection (IST minutes since midnight)
  const ist = new Date(now.toLocaleString('en-US', { timeZone: 'Asia/Kolkata' }))
  const totalMin = ist.getHours() * 60 + ist.getMinutes()
  const isOrbPeriod = totalMin >= 555 && totalMin < 570   // 9:15-9:30
  const isActiveWindow1 = totalMin >= 570 && totalMin < 660  // 9:30-11:00
  const isLunchLull = totalMin >= 660 && totalMin < 810      // 11:00-13:30
  const isActiveWindow2 = totalMin >= 810 && totalMin < 870  // 13:30-14:30
  const isWindingDown = totalMin >= 870 && totalMin < 930    // 14:30-15:30

  let sessionLabel = 'Market Closed'
  let sessionClass = 'bg-gray-800 text-gray-500'

  if (isOrbPeriod) {
    sessionLabel = 'ORB Period'
    sessionClass = 'bg-yellow-900/50 text-yellow-400 border border-yellow-700/50'
  } else if (isActiveWindow1) {
    sessionLabel = 'Window 1'
    sessionClass = 'bg-green-900/30 text-green-400'
  } else if (isLunchLull) {
    sessionLabel = 'Lunch (50%)'
    sessionClass = 'bg-gray-800 text-gray-400'
  } else if (isActiveWindow2) {
    sessionLabel = 'Window 2'
    sessionClass = 'bg-green-900/30 text-green-400'
  } else if (isWindingDown) {
    sessionLabel = 'Winding Down'
    sessionClass = 'bg-orange-900/30 text-orange-400'
  }

  return (
    <div className="text-center hidden sm:block">
      <div className="flex items-center gap-2">
        <span className="text-lg font-mono font-bold text-white">{timeStr}</span>
        <span className={`text-xs px-2 py-0.5 rounded-full ${sessionClass}`}>
          {sessionLabel}
        </span>
      </div>
      <p className="text-xs text-gray-500">{dateStr} IST</p>
    </div>
  )
}
