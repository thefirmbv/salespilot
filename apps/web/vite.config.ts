import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { "@": path.resolve(__dirname, "./src") },
  },
  server: {
    host: true,
    port: 5173,
    proxy: {
      // In dev, requests to /api/* go to the FastAPI container.
      "/api": {
        target: "http://api:8000",
        changeOrigin: true,
      },
    },
  },
});
