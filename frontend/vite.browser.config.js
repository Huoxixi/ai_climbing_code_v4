import {defineConfig} from 'vite'
import vue from '@vitejs/plugin-vue'
import {fileURLToPath} from 'node:url'
import browserModelAssets from './browser-model-assets.mjs'
const assetFileNames=asset=>(asset.names||[asset.name]).some(name=>name?.endsWith('.mjs'))?'assets/[name]-[hash].js':'assets/[name]-[hash][extname]'
export default defineConfig({
  root:fileURLToPath(new URL('.',import.meta.url)),
  publicDir:false,
  plugins:[vue(),browserModelAssets({copy:true})],
  worker:{format:'es',rollupOptions:{output:{assetFileNames}}},
  build:{outDir:'dist-browser',rollupOptions:{input:fileURLToPath(new URL('./browser-replay.html',import.meta.url)),output:{
    // Nginx 1.24 already serves .js as modules; avoid depending on an added .mjs MIME rule.
    assetFileNames,
  }}},
  server:{host:'127.0.0.1',port:4187,strictPort:true,proxy:{'/downloads':{target:process.env.CLIMB_BROWSER_DOWNLOAD_TARGET||'http://127.0.0.1:4317',changeOrigin:false}}},
  preview:{host:'127.0.0.1',port:4187,strictPort:true},
})
