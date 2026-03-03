/**
 * Formatting utilities for the trading dashboard.
 * Converts raw numbers into human-readable strings.
 */

/**
 * Format a number as Indian Rupees.
 * Example: 1234567.89 → "₹12,34,567.89"
 * Uses Indian number system (lakhs, crores).
 */
export function formatCurrency(amount, decimals = 2) {
  if (amount === null || amount === undefined || isNaN(amount)) return '₹0.00'

  return new Intl.NumberFormat('en-IN', {
    style: 'currency',
    currency: 'INR',
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(amount)
}

/**
 * Format P&L with a + or - sign.
 * Example: 45.50 → "+₹45.50" | -30.00 → "-₹30.00"
 */
export function formatPnL(amount) {
  if (amount === null || amount === undefined || isNaN(amount)) return '₹0.00'

  const abs = formatCurrency(Math.abs(amount))
  if (amount >= 0) return `+${abs}`
  return `-${abs.replace('₹', '₹')}`
}

/**
 * Format a percentage with sign.
 * Example: 4.55 → "+4.55%" | -2.1 → "-2.10%"
 */
export function formatPercent(value, decimals = 2) {
  if (value === null || value === undefined || isNaN(value)) return '0.00%'
  const sign = value >= 0 ? '+' : ''
  return `${sign}${Number(value).toFixed(decimals)}%`
}

/**
 * Format an ISO timestamp into a readable time.
 * Example: "2026-03-04T09:35:22.123" → "09:35:22"
 */
export function formatTime(isoString) {
  if (!isoString) return '--'
  try {
    const date = new Date(isoString)
    return date.toLocaleTimeString('en-IN', {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false,
    })
  } catch {
    return '--'
  }
}

/**
 * Format a date string.
 * Example: "2026-03-04T09:35:22" → "4 Mar 2026"
 */
export function formatDate(isoString) {
  if (!isoString) return '--'
  try {
    return new Date(isoString).toLocaleDateString('en-IN', {
      day: 'numeric',
      month: 'short',
      year: 'numeric',
    })
  } catch {
    return '--'
  }
}

/**
 * Return the CSS color class based on value sign.
 * Positive → green, Negative → red, Zero → gray
 */
export function pnlColorClass(value) {
  if (!value || value === 0) return 'text-gray-400'
  return value > 0 ? 'text-green-400' : 'text-red-400'
}

/**
 * Format a confidence score (0–1) as a percentage string.
 * Example: 0.85 → "85%"
 */
export function formatConfidence(score) {
  if (score === null || score === undefined) return '0%'
  return `${Math.round(score * 100)}%`
}

/**
 * Abbreviate large numbers.
 * Example: 1234567 → "12.3L" (lakhs), 12345678 → "1.2Cr"
 */
export function formatVolume(num) {
  if (!num) return '0'
  if (num >= 10000000) return `${(num / 10000000).toFixed(1)}Cr`
  if (num >= 100000) return `${(num / 100000).toFixed(1)}L`
  if (num >= 1000) return `${(num / 1000).toFixed(1)}K`
  return num.toString()
}
