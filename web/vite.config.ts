import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: [
      { find: "@", replacement: path.resolve(__dirname, "./src") },
      // Order matters: subpath rule comes first so `@yqgl/shared/foo` does not
      // accidentally match the bare-package rule below.
      { find: /^@yqgl\/shared\/(.*)$/, replacement: path.resolve(__dirname, "../shared/src") + "/$1" },
      { find: /^@yqgl\/shared$/, replacement: path.resolve(__dirname, "../shared/src/index.ts") },
    ],
  },
  server: {
    port: 5173,
    proxy: {
      // For dev: set YQGL_BASE in your env, or edit here, e.g. "http://localhost:8080"
      "/api": process.env.YQGL_BASE || "http://localhost:8080",
    },
  },
  build: {
    outDir: "dist",
    sourcemap: false,
  },
});
