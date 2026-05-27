// Vite/PostCSS picks this up when invoked from the client-tauri folder.
// Content paths are relative to this file (the project root for vite).
import preset from "../shared/src/design/tailwind-preset";

/** @type {import('tailwindcss').Config} */
export default {
  presets: [preset],
  content: [
    "./web-src/index.html",
    "./web-src/src/**/*.{ts,tsx}",
    "../shared/src/**/*.{ts,tsx}",
  ],
};
