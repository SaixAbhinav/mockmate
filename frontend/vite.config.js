import { resolve } from 'node:path'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  build: {
    // Two entry points, two real files in the bucket (ADR 0033): "/" is the
    // landing page and "/app.html" is the interview itself. Keeping the app
    // as its own HTML file rather than a client-side route is what lets a
    // refresh or a shared link resolve without a CloudFront error-rewrite -
    // the same reason cloudfront.tf deliberately configures none.
    rollupOptions: {
      input: {
        main: resolve(__dirname, 'index.html'),
        app: resolve(__dirname, 'app.html'),
      },
    },
  },
  server: {
    proxy: {
      // Frontend calls "/api"; Vite forwards to the FastAPI backend so the
      // browser never deals with cross-origin requests in development.
      '/api': 'http://localhost:8000',
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.js'],
    css: false,
  },
})
