/**
 * Vite Configuration
 *
 * FFmpeg WASM requires SharedArrayBuffer, which needs special HTTP headers.
 * We configure the dev server to include these headers.
 */

import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import commonjs from 'vite-plugin-commonjs'

export default defineConfig({
  plugins: [
    react(),
    commonjs()
  ],

  optimizeDeps: {
    include: [
      '@excalidraw/excalidraw',
      'es6-promise-pool'
    ],
    exclude: ['@ffmpeg/ffmpeg', '@ffmpeg/util']
  },

  // Required headers for FFmpeg WASM (SharedArrayBuffer)
  server: {
    headers: {
      'Cross-Origin-Opener-Policy': 'same-origin',
      'Cross-Origin-Embedder-Policy': 'require-corp'
    }
  },

  define: {
    'process.env': {}
  }
})
