import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'
import { fileURLToPath } from 'url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],

  // ── Build output ────────────────────────────────────────────────────────────
  // `npm run build` emits compiled assets directly into the FastAPI static
  // serving directory.  The Python server mounts this directory at /web and
  // serves index.html at GET /.
  build: {
    // Absolute path: <repo_root>/core/web/
    outDir: path.resolve(__dirname, '../core/web'),

    // Wipe the output directory on every build so stale chunks are removed.
    emptyOutDir: true,

    // Produce source maps for production debugging (optional — remove to ship
    // smaller bundles in a locked-down deployment).
    sourcemap: false,

    rollupOptions: {
      // Explicit entry point — Vite auto-detects index.html but being explicit
      // prevents surprises when the project root is not the CWD.
      input: path.resolve(__dirname, 'index.html'),
    },
  },

  // ── Dev server ──────────────────────────────────────────────────────────────
  // Proxies API calls to the running FastAPI server during local development
  // so the React dev-server and the Python backend co-exist without CORS issues.
  server: {
    port: 5173,
    proxy: {
      '/api':      { target: 'http://127.0.0.1:50000', changeOrigin: true },
      '/command':  { target: 'http://127.0.0.1:50000', changeOrigin: true },
      '/stream':   { target: 'http://127.0.0.1:50000', changeOrigin: true },
      '/telemetry':{ target: 'http://127.0.0.1:50000', changeOrigin: true },
      '/health':   { target: 'http://127.0.0.1:50000', changeOrigin: true },
    },
  },

  // ── Path aliases ────────────────────────────────────────────────────────────
  resolve: {
    alias: {
      '@': path.resolve(__dirname, 'src'),
    },
  },
})
