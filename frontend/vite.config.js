import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'

const root = fileURLToPath(new URL('.', import.meta.url))

// https://vite.dev/config/
export default defineConfig({
  root,
  plugins: [vue()],
  server: {
    proxy: {
      '/photo-route-assets': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/images': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})
