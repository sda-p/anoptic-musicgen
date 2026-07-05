import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev server (port 5173) proxies the API + WebSocket to the FastAPI backend
// (port 8765), so `npm run dev` gives HMR against the real engine. `npm run
// build` emits dist/, which the FastAPI server mounts at / for single-process
// runs.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: "http://127.0.0.1:8765", changeOrigin: true },
      "/ws": { target: "ws://127.0.0.1:8765", ws: true },
    },
  },
  build: { outDir: "dist", emptyOutDir: true },
});
