import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Dev: the engine runs on :8000; Vite proxies API and websockets so everything is one origin.
export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    allowedHosts: true,
    proxy: {
      '/api': 'http://localhost:8000',
      '/ws': { target: 'ws://localhost:8000', ws: true },
    },
  },
})
