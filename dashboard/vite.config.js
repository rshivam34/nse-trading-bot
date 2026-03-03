import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// GitHub Pages serves from /nse-trading-bot/ subfolder
// Change this to '/' if you're using a custom domain
const BASE_URL = '/nse-trading-bot/'

export default defineConfig({
  plugins: [react()],
  base: BASE_URL,
  build: {
    outDir: 'dist',
    sourcemap: false,
  },
})
