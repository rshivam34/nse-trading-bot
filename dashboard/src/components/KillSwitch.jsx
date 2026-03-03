/**
 * KillSwitch — Emergency stop button.
 * When pressed, sets /kill_switch in Firebase → bot sees it → exits all positions.
 *
 * This is the most important safety feature of the dashboard.
 * Double-confirm before triggering to prevent accidental presses.
 */

import React, { useState } from 'react'
import { ref, set } from 'firebase/database'
import { db } from '../firebase.js'

export default function KillSwitch({ killSwitch }) {
  const [confirming, setConfirming] = useState(false)
  const [activating, setActivating] = useState(false)
  const isActive = killSwitch?.active === true

  async function handleKillSwitch() {
    if (!confirming) {
      // First click: show confirmation
      setConfirming(true)
      // Auto-cancel confirmation after 5 seconds
      setTimeout(() => setConfirming(false), 5000)
      return
    }

    // Second click: actually activate
    setActivating(true)
    try {
      await set(ref(db, 'kill_switch'), {
        active: true,
        triggered_at: new Date().toISOString(),
        triggered_by: 'dashboard',
      })
      setConfirming(false)
    } catch (err) {
      console.error('Kill switch error:', err)
      alert('Failed to activate kill switch. Check your Firebase connection.')
    } finally {
      setActivating(false)
    }
  }

  async function handleReset() {
    try {
      await set(ref(db, 'kill_switch'), {
        active: false,
        reset_at: new Date().toISOString(),
      })
    } catch (err) {
      console.error('Reset error:', err)
    }
  }

  // Kill switch already active
  if (isActive) {
    return (
      <div className="bg-red-950 border border-red-700 rounded-xl p-5">
        <div className="flex items-center gap-3 mb-3">
          <span className="text-2xl">🔴</span>
          <div>
            <h2 className="text-red-400 font-bold text-lg">KILL SWITCH ACTIVE</h2>
            <p className="text-red-300 text-xs">
              Bot is stopping. All positions being closed.
            </p>
          </div>
        </div>
        {killSwitch?.triggered_at && (
          <p className="text-xs text-red-400 mb-3">
            Triggered at: {new Date(killSwitch.triggered_at).toLocaleTimeString('en-IN')}
          </p>
        )}
        <button
          onClick={handleReset}
          className="w-full py-2 px-4 bg-gray-700 hover:bg-gray-600 text-white rounded-lg text-sm font-medium transition-colors"
        >
          Reset Kill Switch (for next session)
        </button>
      </div>
    )
  }

  return (
    <div className="bg-gray-900 rounded-xl border border-gray-800 p-5">
      <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-widest mb-3">
        Emergency Stop
      </h2>

      <p className="text-xs text-gray-400 mb-4">
        Press to immediately stop the bot and exit all open positions at market price.
        Use only in emergencies — exits may be at a loss.
      </p>

      {!confirming ? (
        <button
          onClick={handleKillSwitch}
          className="w-full py-3 px-4 bg-red-900/50 hover:bg-red-800 border border-red-700 text-red-300 hover:text-red-100 rounded-lg text-sm font-bold transition-all duration-200 flex items-center justify-center gap-2"
        >
          <span>🛑</span>
          <span>KILL SWITCH</span>
        </button>
      ) : (
        <div className="space-y-2">
          <p className="text-center text-red-400 text-xs font-semibold animate-pulse">
            ⚠️ Are you sure? This will exit ALL positions immediately!
          </p>
          <button
            onClick={handleKillSwitch}
            disabled={activating}
            className="w-full py-3 px-4 bg-red-600 hover:bg-red-500 text-white rounded-lg text-sm font-bold transition-colors disabled:opacity-60"
          >
            {activating ? 'Activating...' : '⚡ CONFIRM — EXIT ALL NOW'}
          </button>
          <button
            onClick={() => setConfirming(false)}
            className="w-full py-2 px-4 bg-gray-800 hover:bg-gray-700 text-gray-300 rounded-lg text-xs transition-colors"
          >
            Cancel
          </button>
        </div>
      )}

      <p className="text-xs text-gray-600 text-center mt-3">
        Resets automatically on bot restart
      </p>
    </div>
  )
}
