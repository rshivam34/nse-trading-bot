/**
 * Firebase Web Configuration
 * ===========================
 * This connects the dashboard to Firebase Realtime Database.
 *
 * !! ACTION REQUIRED !!
 * You need to fill in your Firebase Web App config below.
 * Get it from: Firebase Console → Project Settings → General → Your Apps → Web App
 *
 * These values are SAFE to be public. Firebase security comes from security rules,
 * not from hiding these keys (they're designed to be in frontend code).
 *
 * Steps:
 * 1. Go to https://console.firebase.google.com/project/nse-trading-bot-7bb00/settings/general
 * 2. Scroll down to "Your apps" section
 * 3. If no web app exists, click "Add app" → Web icon → Register
 * 4. Copy the firebaseConfig object values here
 */

import { initializeApp } from 'firebase/app'
import { getDatabase } from 'firebase/database'

const firebaseConfig = {
  apiKey: "AIzaSyDESjKJZqVIsLWrfn7sUNgqhVsF8MinSlU",
  authDomain: "nse-trading-bot-7bb00.firebaseapp.com",
  databaseURL: "https://nse-trading-bot-7bb00-default-rtdb.asia-southeast1.firebasedatabase.app",
  projectId: "nse-trading-bot-7bb00",
  storageBucket: "nse-trading-bot-7bb00.firebasestorage.app",
  messagingSenderId: "956938952832",
  appId: "1:956938952832:web:705cd3fd118fb1c182c665",
}

// Initialize Firebase
const app = initializeApp(firebaseConfig)

// Export the database reference for use in hooks
export const db = getDatabase(app)
export default app
