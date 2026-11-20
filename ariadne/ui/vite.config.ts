import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The built console is served by the Ariadne server under /static/.
export default defineConfig({
  plugins: [react()],
  base: "/static/",
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8917",
    },
  },
});