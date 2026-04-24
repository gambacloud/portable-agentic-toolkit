import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/ws": {
        target: "ws://localhost:8002",
        ws: true,
      },
      "/api": {
        target: "http://localhost:8002",
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
      // Direct REST calls (no /api prefix needed in prod since same origin)
      "/health": "http://localhost:8002",
      "/models": "http://localhost:8002",
      "/profiles": "http://localhost:8002",
      "/conversations": "http://localhost:8002",
      "/users": "http://localhost:8002",
      "/schedules": "http://localhost:8002",
      "/outputs": "http://localhost:8002",
      "/mcps": "http://localhost:8002",
    },
  },
});
