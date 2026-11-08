/// <reference types="vitest/config" />
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// FastAPI serves the built dashboard itself on 127.0.0.1:8765 (one origin). In development
// this server runs on 127.0.0.1:5173, the only other origin the backend's WebSockets accept,
// and proxies /api (REST and WebSockets) to the backend. Nothing is fetched from anywhere else.
const BACKEND = "http://127.0.0.1:8765";

// The same policy FastAPI sends (app/main.py), so `vite preview` and the browser tests run the
// bundle under it: no inline scripts or styles, nothing from other sites.
const CSP =
  "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; font-src 'self'; " +
  "connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; " +
  "frame-ancestors 'none'";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": { target: BACKEND, ws: true },
    },
  },
  preview: {
    host: "127.0.0.1",
    port: 4173,
    strictPort: true,
    headers: { "Content-Security-Policy": CSP },
  },
  build: {
    outDir: "dist",
    // Never inline assets as data: URLs; the CSP only allows files from RoomCheck itself.
    assetsInlineLimit: 0,
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
    css: false,
  },
});
