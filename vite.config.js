import { defineConfig } from "vite";

export default defineConfig({
  root: "frontend",
  base: "./",
  build: {
    outDir: "../public",
    emptyOutDir: true,
    sourcemap: false,
  },
  server: {
    port: 5173,
    proxy: {
      "/api": "http://localhost:8000",
      "/ws": { target: "ws://localhost:8000", ws: true },
    },
  },
});
