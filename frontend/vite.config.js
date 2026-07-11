import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig(({ mode }) => {
  const isTest = mode === 'test'
  const env = loadEnv(mode, process.cwd(), 'VITE_')
  const apiProxyTarget =
    env.VITE_API_PROXY_TARGET || process.env.VITE_API_PROXY_TARGET || 'http://127.0.0.1:8080'

  return {
    plugins: [vue()],
    server: {
      host: isTest ? '127.0.0.1' : '0.0.0.0',
      port: 5173,
      hmr: isTest ? false : undefined,
      proxy: {
        '/api': {
          target: apiProxyTarget,
          changeOrigin: true,
        },
      },
    },
    test: {
      environment: 'node',
      globals: true,
    },
  }
})
