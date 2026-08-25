import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'node:path'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { '@': path.resolve(__dirname, 'src') },
  },
  server: {
    host: true,
    port: 5173,
    // Vite 6 rejects requests whose Host header it does not recognise, which
    // is exactly what a tunnel sends. Allow ngrok and friends.
    allowedHosts: ['.ngrok-free.app', '.ngrok.io', '.ngrok.app', '.trycloudflare.com', '.loca.lt'],
    // The frontend calls the API with relative URLs, so a single tunnel to
    // this port serves the whole app. Without this the browser would look for
    // the API on its own machine.
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true },
      '/widget.js': { target: 'http://127.0.0.1:8000', changeOrigin: true },
      '/health': { target: 'http://127.0.0.1:8000', changeOrigin: true },
    },
  },
})
