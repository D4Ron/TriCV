import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'node:path'

export default defineConfig(({ mode }) => {
  // Windows réserve parfois une plage de ports au démarrage (Hyper-V, Docker) :
  // 8000 peut alors être refusé. API_PROXY_TARGET, posé dans frontend/.env.local,
  // pointe le proxy vers un autre port.
  const api = loadEnv(mode, __dirname, '').API_PROXY_TARGET || 'http://127.0.0.1:8000'

  return {
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
        '/api': { target: api, changeOrigin: true },
        '/widget.js': { target: api, changeOrigin: true },
        '/health': { target: api, changeOrigin: true },
      },
    },
  }
})
