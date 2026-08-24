import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// During local dev (`npm run dev`) the frontend proxies API calls to the
// FastAPI dev server; in production the backend serves the built static
// files directly, so no proxy is needed there.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": "http://localhost:8000",
    },
  },
  build: {
    outDir: "dist",
  },
});
