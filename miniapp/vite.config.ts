import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    // Telegram loads the Mini App over HTTPS from a tunnel in development;
    // binding all interfaces lets ngrok/cloudflared reach it.
    host: true,
  },
  build: {
    outDir: 'dist',
    sourcemap: true,
  },
})
