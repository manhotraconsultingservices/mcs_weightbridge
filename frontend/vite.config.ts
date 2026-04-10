import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'path'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: parseInt(process.env.PORT || '9000'),
    host: '0.0.0.0',
    strictPort: true,
    proxy: {
      '/api': {
        target: 'http://localhost:9003',
        changeOrigin: true,
      },
      '/ws': {
        target: 'ws://localhost:9003',
        ws: true,
      },
      '/uploads': {
        target: 'http://localhost:9003',
        changeOrigin: true,
      },
    },
  },
  build: {
    // SECURITY: Never emit source maps in production — they expose original TypeScript source
    sourcemap: false,
    // Minify with esbuild (default) — good enough obfuscation for business logic
    minify: 'esbuild',
    // Raise chunk size warning threshold (avoids noisy warnings, not a security setting)
    chunkSizeWarningLimit: 1500,
    rollupOptions: {
      output: {
        // Randomise chunk filenames with content hash — prevents predictable file enumeration
        chunkFileNames: 'assets/[hash].js',
        entryFileNames: 'assets/[hash].js',
        assetFileNames: 'assets/[hash][extname]',
        // Split vendor code into separate chunks (caching efficiency)
        manualChunks(id) {
          if (id.includes('node_modules')) {
            if (id.includes('recharts') || id.includes('d3-')) return 'charts';
            if (id.includes('react-router')) return 'router';
            if (id.includes('react')) return 'react';
            return 'vendor';
          }
        },
      },
    },
  },
})
