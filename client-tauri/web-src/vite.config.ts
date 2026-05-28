import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

const HERE = path.resolve(__dirname);

export default defineConfig({
  root: HERE,
  plugins: [react()],
  resolve: {
    alias: [
      { find: "@", replacement: path.resolve(HERE, "./src") },
      // Shared package: match subpath first, then bare import.
      { find: /^@yqgl\/shared\/(.*)$/, replacement: path.resolve(HERE, "../../shared/src") + "/$1" },
      { find: /^@yqgl\/shared$/, replacement: path.resolve(HERE, "../../shared/src/index.ts") },
    ],
  },
  server: {
    port: 5174,
    strictPort: true,
    proxy: {
      "/api": process.env.YQGL_BASE || "http://localhost:8080",
    },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
    sourcemap: false,
  },
});
