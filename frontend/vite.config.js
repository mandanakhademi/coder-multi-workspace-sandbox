import { defineConfig } from 'vite'

export default defineConfig({
  server: {
    host: '0.0.0.0',
    port: 3000,
    allowedHosts: true,
    proxy: {
      '/api': {
        target: 'http://backend:8000', // Points to the internal docker-compose service name
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, '') // Cleans the prefix before hitting FastAPI
      }
    }
  }
})
