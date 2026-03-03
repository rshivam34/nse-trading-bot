/** @type {import('tailwindcss').Config} */
export default {
  content: [
    './index.html',
    './src/**/*.{js,jsx,ts,tsx}',
  ],
  theme: {
    extend: {
      colors: {
        // Custom colors for trading dashboard
        profit: '#22c55e',   // Green for profit
        loss: '#ef4444',     // Red for loss
        neutral: '#94a3b8',  // Gray for neutral
      },
    },
  },
  plugins: [],
}
