import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'

const root = fileURLToPath(new URL('.', import.meta.url))
const backendTarget = process.env.CLIMB_PREVIEW_BACKEND_TARGET || 'http://127.0.0.1:8004'

// https://vite.dev/config/
export default defineConfig({
  root,
  plugins: [vue(), {name:'photo-preview-redirect',configureServer(server) {server.middlewares.use((req,res,next)=>{if(req.url?.split('?')[0]==='/e2e/harness.html'){res.statusCode=302;res.setHeader('Location','http://127.0.0.1:4176/#/photo-routes');res.end()}else next()})}}],
  preview: {host:'127.0.0.1',port:4176,strictPort:true},
  server: {
    host: '127.0.0.1',
    port: 4176,
    strictPort: true,
    proxy: {
      '/photo-route-assets': {
        target: backendTarget,
        changeOrigin: true,
      },
      '/api': {
        target: backendTarget,
        changeOrigin: true,
      },
      '/images': {
        target: backendTarget,
        changeOrigin: true,
      },
    },
  },
})
