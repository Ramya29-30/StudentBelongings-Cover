import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

// Dev: `npm run dev` serves the UI on :5173 and proxies /api to the FastAPI backend on :8000.
// Prod: `npm run build` emits ../frontend/dist, which FastAPI serves (same origin => HttpOnly cookie auth, no CORS).
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: { '/api': 'http://localhost:8000' } },
  test: { environment: 'jsdom', globals: true, setupFiles: './src/test/setup.ts', css: false },
  build: { outDir: '../frontend/dist', emptyOutDir: true, sourcemap: false },
});
