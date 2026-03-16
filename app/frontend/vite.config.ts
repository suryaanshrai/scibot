import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'path'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, __dirname, '')
  const backendUrl = env.BACKEND_URL || 'http://localhost:8080/api'
  const proxyTarget = backendUrl.replace(/\/api\/?$/, '')

  return {
    plugins: [react(), tailwindcss()],
    envPrefix: ['VITE_', 'BACKEND_'],
    resolve: {
      alias: {
        '@': path.resolve(__dirname, './src'),
      },
    },
    server: {
      port: 5173,
      proxy: {
        '/api': proxyTarget,
      },
    },
  }
})
