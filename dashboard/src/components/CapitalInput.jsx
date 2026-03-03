/**
 * CapitalInput — Let the user update their starting capital.
 * This writes to Firebase so the bot can pick it up.
 *
 * Why capital matters:
 * - Position sizes are calculated as a % of capital
 * - Risk limits (2% per trade, 3% daily) are based on capital
 * - Starting with the right number = correct position sizes
 */

import React, { useState } from 'react'
import { ref, set } from 'firebase/database'
import { db } from '../firebase.js'
import { formatCurrency } from '../utils/formatters.js'

export default function CapitalInput({ portfolio }) {
  const currentCapital = portfolio?.current_capital || 0
  const initialCapital = portfolio?.initial_capital || 0

  const [inputValue, setInputValue] = useState('')
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState('')

  async function handleSave() {
    const amount = parseFloat(inputValue)

    if (!inputValue || isNaN(amount)) {
      setError('Please enter a valid number')
      return
    }
    if (amount < 100) {
      setError('Minimum capital is ₹100')
      return
    }
    if (amount > 1000000) {
      setError('Maximum capital is ₹10,00,000 (10 lakhs)')
      return
    }

    setSaving(true)
    setError('')
    try {
      // Update the initial_capital in Firebase
      // The bot reads this on next startup
      await set(ref(db, 'config/initial_capital'), amount)
      setSaved(true)
      setInputValue('')
      setTimeout(() => setSaved(false), 3000)
    } catch (err) {
      setError('Failed to save. Check Firebase connection.')
    } finally {
      setSaving(false)
    }
  }

  function handleKeyDown(e) {
    if (e.key === 'Enter') handleSave()
  }

  // Risk calculations to show the user
  const maxRiskPerTrade = initialCapital * 0.02  // 2%
  const dailyLossLimit = initialCapital * 0.03   // 3%

  return (
    <div className="bg-gray-900 rounded-xl border border-gray-800 p-5">
      <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-widest mb-4">
        Capital Settings
      </h2>

      {/* Current capital display */}
      <div className="mb-4 p-3 bg-gray-800 rounded-lg">
        <div className="flex justify-between items-center">
          <span className="text-xs text-gray-500">Bot's Capital</span>
          <span className="text-sm font-bold text-white">
            {formatCurrency(currentCapital)}
          </span>
        </div>
        {initialCapital > 0 && (
          <div className="flex justify-between items-center mt-1">
            <span className="text-xs text-gray-500">Starting Capital</span>
            <span className="text-xs text-gray-400">{formatCurrency(initialCapital)}</span>
          </div>
        )}
      </div>

      {/* Risk summary */}
      {initialCapital > 0 && (
        <div className="grid grid-cols-2 gap-2 mb-4">
          <div className="bg-gray-800/60 rounded-lg p-2 text-center">
            <p className="text-[10px] text-gray-500">Max Risk / Trade</p>
            <p className="text-xs font-semibold text-yellow-400">{formatCurrency(maxRiskPerTrade)}</p>
            <p className="text-[10px] text-gray-600">(2%)</p>
          </div>
          <div className="bg-gray-800/60 rounded-lg p-2 text-center">
            <p className="text-[10px] text-gray-500">Daily Loss Limit</p>
            <p className="text-xs font-semibold text-red-400">{formatCurrency(dailyLossLimit)}</p>
            <p className="text-[10px] text-gray-600">(3%)</p>
          </div>
        </div>
      )}

      {/* Input to update capital */}
      <div className="space-y-2">
        <label className="text-xs text-gray-400">Update Starting Capital (₹)</label>
        <div className="flex gap-2">
          <div className="flex-1 relative">
            <span className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500 text-sm">₹</span>
            <input
              type="number"
              value={inputValue}
              onChange={(e) => { setInputValue(e.target.value); setError('') }}
              onKeyDown={handleKeyDown}
              placeholder="e.g. 1000"
              min="100"
              max="1000000"
              className="w-full bg-gray-800 border border-gray-700 focus:border-indigo-500 text-white rounded-lg pl-7 pr-3 py-2 text-sm outline-none transition-colors"
            />
          </div>
          <button
            onClick={handleSave}
            disabled={saving || !inputValue}
            className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 disabled:bg-gray-700 disabled:text-gray-500 text-white text-sm font-medium rounded-lg transition-colors min-w-[60px]"
          >
            {saving ? '...' : saved ? '✓' : 'Save'}
          </button>
        </div>

        {error && <p className="text-xs text-red-400">{error}</p>}
        {saved && <p className="text-xs text-green-400">✓ Capital updated! Restart bot to apply.</p>}

        <p className="text-[10px] text-gray-600">
          Note: Capital changes take effect on next bot restart.
        </p>
      </div>
    </div>
  )
}
