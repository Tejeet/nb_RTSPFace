import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev-server proxy points at a locally running backend; in production
// nginx handles the same /api and /ws routing (see nginx.conf).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: "http://localhost:8000", changeOrigin: true },
      "/ws": { target: "ws://localhost:8000", ws: true },
    },
  },
  build: { outDir: "dist", sourcemap: false },
});
