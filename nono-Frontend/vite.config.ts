import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'   // 需要安装 @types/node 或直接引用

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: 5173,
    strictPort: true,
    open: true,
    proxy: {
      '/api': {
        target: 'http://10.71.199.207:8080',
        changeOrigin: true,
      },
    },
  },
})