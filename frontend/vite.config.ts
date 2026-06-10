/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

// The built SPA is served as static files by the FastAPI container (single Cloud Run service).
export default defineConfig({
  plugins: [react()],
  server: {
    // Dev only: proxy API calls to the FastAPI backend. In prod the SPA is same-origin.
    proxy: { '/api': 'http://localhost:8080' },
  },
  build: {
    outDir: 'dist',
  },
  test: {
    environment: 'node',
    include: ['src/**/*.test.ts'],
  },
});
