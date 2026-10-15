import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// The Tauri shell loads this build from the file system (`frontendDist`), so
// every asset must be relative — an absolute "/assets/..." would resolve
// against the protocol root, not the app directory (ADR-0001: no remote, no
// server to serve from).
//
// `TAURI_ENV_DEBUG` is set by `tauri dev`; Vite's host/port must match
// `devUrl` in src-tauri/tauri.conf.json, so they are bound to one place here.
const host = process.env.TAURI_DEV_HOST || 'localhost'

export default defineConfig({
  plugins: [vue()],
  clearScreen: false,
  base: './',
  build: {
    // Tauri resolves the bundle's own assets; sourcemaps would only bloat it.
    sourcemap: !!process.env.TAURI_ENV_DEBUG,
    target: 'chrome105',
    outDir: 'dist',
    emptyOutDir: true,
  },
  server: {
    port: 5173,
    strictPort: true,
    host: host || false,
    hmr: host ? { protocol: 'ws', host, port: 5174 } : undefined,
    watch: { ignored: ['**/src-tauri/**'] },
  },
  envPrefix: ['VITE_', 'TAURI_ENV_'],
})
