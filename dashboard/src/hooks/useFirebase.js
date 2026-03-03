/**
 * useFirebase — Real-time Firebase data listener hook.
 *
 * This hook subscribes to a Firebase path and returns its value.
 * It updates automatically whenever the backend pushes new data.
 *
 * Example usage:
 *   const portfolio = useFirebase('portfolio')
 *   const signals = useFirebase('signals')
 *
 * How it works:
 * - Firebase's onValue() sets up a WebSocket connection to Firebase
 * - Whenever data at the path changes, the callback fires immediately
 * - React's useState stores the value and triggers a re-render
 * - Cleanup (unsubscribe) happens when the component unmounts
 */

import { useState, useEffect } from 'react'
import { ref, onValue, off } from 'firebase/database'
import { db } from '../firebase.js'

/**
 * @param {string} path - Firebase database path (e.g., 'portfolio', 'signals')
 * @param {any} defaultValue - Value to use before data loads
 * @returns {any} The current value at that Firebase path
 */
export function useFirebase(path, defaultValue = null) {
  const [data, setData] = useState(defaultValue)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    if (!path) return

    const dbRef = ref(db, path)

    // onValue fires immediately with current data, then on every change
    const unsubscribe = onValue(
      dbRef,
      (snapshot) => {
        setData(snapshot.val())  // null if path doesn't exist yet
        setLoading(false)
        setError(null)
      },
      (err) => {
        console.error(`Firebase error at /${path}:`, err)
        setError(err.message)
        setLoading(false)
      }
    )

    // Cleanup: stop listening when component unmounts
    return () => off(dbRef)
  }, [path])

  return { data, loading, error }
}

/**
 * useFirebaseList — Converts a Firebase object (with auto-keys) into an array.
 *
 * Firebase stores push() data like:
 * { "-abc123": {...}, "-def456": {...} }
 *
 * This hook converts that to:
 * [ {id: "-abc123", ...}, {id: "-def456", ...} ]
 *
 * Sorted by timestamp (newest first by default).
 */
export function useFirebaseList(path, { newestFirst = true } = {}) {
  const { data, loading, error } = useFirebase(path, null)

  // Convert object to array and add the Firebase key as 'id'
  const list = data
    ? Object.entries(data).map(([id, value]) => ({ id, ...value }))
    : []

  // Sort by timestamp field
  if (newestFirst) {
    list.sort((a, b) => {
      const tA = new Date(a.timestamp || a.executed_at || 0).getTime()
      const tB = new Date(b.timestamp || b.executed_at || 0).getTime()
      return tB - tA  // Descending (newest first)
    })
  }

  return { list, loading, error }
}
