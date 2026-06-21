import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Proxy /api to the FastAPI backend so the frontend can fetch without CORS in dev.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": "http://localhost:8000",
    },
  },
});
