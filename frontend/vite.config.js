import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      // Frontend calls "/api"; Vite forwards to the FastAPI backend so the
      // browser never deals with cross-origin requests in development.
      '/api': 'http://localhost:8000',
    },
  },
})
