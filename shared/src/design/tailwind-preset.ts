import type { Config } from "tailwindcss";

/**
 * Tailwind preset for Aurora Glass design system.
 * Both web and the Tauri client front-end import this via `presets: [preset]`.
 *
 * All colors point to CSS variables defined in `./tokens.css`, so theme
 * switching (light/dark) happens via `<html data-theme="...">`.
 */
const preset = {
  darkMode: ["class", '[data-theme="dark"]'],
  theme: {
    extend: {
      colors: {
        ink: {
          DEFAULT: "var(--ink)",
          soft: "var(--ink-soft)",
          muted: "var(--ink-muted)",
          faint: "var(--ink-faint)",
        },
        line: {
          DEFAULT: "var(--line)",
          strong: "var(--line-strong)",
        },
        canvas: {
          DEFAULT: "var(--bg-canvas)",
          2: "var(--bg-canvas-2)",
          3: "var(--bg-canvas-3)",
        },
        surface: {
          DEFAULT: "var(--surface)",
          strong: "var(--surface-strong)",
          quiet: "var(--surface-quiet)",
          sunken: "var(--surface-sunken)",
        },
        accent: {
          DEFAULT: "var(--accent)",
          hover: "var(--accent-hover)",
          soft: "var(--accent-soft)",
        },
        "accent-2": {
          DEFAULT: "var(--accent-2)",
          soft: "var(--accent-2-soft)",
        },
        success: { DEFAULT: "var(--success)", soft: "var(--success-soft)" },
        warn: { DEFAULT: "var(--warn)", soft: "var(--warn-soft)" },
        error: { DEFAULT: "var(--error)", soft: "var(--error-soft)" },
        info: { DEFAULT: "var(--info)", soft: "var(--info-soft)" },
      },
      borderRadius: {
        xs: "6px",
        sm: "10px",
        md: "14px",
        lg: "20px",
        xl: "28px",
        pill: "9999px",
      },
      boxShadow: {
        e1: "var(--shadow-1)",
        e2: "var(--shadow-2)",
        e3: "var(--shadow-3)",
        e4: "var(--shadow-4)",
        e5: "var(--shadow-5)",
      },
      backdropBlur: {
        "1": "8px",
        "2": "16px",
        "3": "24px",
        "4": "40px",
      },
      backdropSaturate: {
        glass: "140%",
        strong: "150%",
        extreme: "160%",
      },
      fontFamily: {
        sans: [
          "Inter",
          "PingFang SC",
          "HarmonyOS Sans SC",
          "Microsoft YaHei",
          "Segoe UI",
          "system-ui",
          "sans-serif",
        ],
        mono: [
          "JetBrains Mono",
          "Fira Code",
          "SF Mono",
          "Cascadia Mono",
          "Consolas",
          "monospace",
        ],
      },
      fontSize: {
        display: ["2.5rem", { lineHeight: "1.1", letterSpacing: "-0.02em", fontWeight: "700" }],
        h1: ["1.875rem", { lineHeight: "1.2", letterSpacing: "-0.015em", fontWeight: "700" }],
        h2: ["1.5rem", { lineHeight: "1.25", letterSpacing: "-0.01em", fontWeight: "650" }],
        h3: ["1.25rem", { lineHeight: "1.35", fontWeight: "600" }],
        h4: ["1.0625rem", { lineHeight: "1.45", fontWeight: "600" }],
        body: ["0.9375rem", { lineHeight: "1.55", fontWeight: "450" }],
        "body-sm": ["0.875rem", { lineHeight: "1.55", fontWeight: "450" }],
        caption: ["0.8125rem", { lineHeight: "1.45", fontWeight: "500" }],
        eyebrow: ["0.6875rem", { lineHeight: "1.2", letterSpacing: "0.12em", fontWeight: "600" }],
      },
      spacing: {
        "0.5": "2px",
        "1.5": "6px",
        "2.5": "10px",
        "3.5": "14px",
      },
      transitionTimingFunction: {
        "out-soft": "cubic-bezier(0.22,1,0.36,1)",
        "in-out-glide": "cubic-bezier(0.65,0,0.35,1)",
        spring: "cubic-bezier(0.34,1.56,0.64,1)",
      },
      transitionDuration: {
        fast: "150ms",
        base: "250ms",
        slow: "400ms",
      },
      keyframes: {
        "fade-up": {
          from: { opacity: "0", transform: "translateY(4px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
        "slide-right": {
          from: { opacity: "0", transform: "translateX(16px)" },
          to: { opacity: "1", transform: "translateX(0)" },
        },
        "scale-in": {
          from: { opacity: "0", transform: "scale(0.96)" },
          to: { opacity: "1", transform: "scale(1)" },
        },
        "pulse-accent": {
          "0%,100%": { boxShadow: "0 0 0 0 var(--accent-soft)" },
          "50%": { boxShadow: "0 0 0 6px var(--accent-soft)" },
        },
        shimmer: {
          "0%": { backgroundPosition: "-200% 0" },
          "100%": { backgroundPosition: "200% 0" },
        },
      },
      animation: {
        "fade-up": "fade-up 250ms cubic-bezier(0.22,1,0.36,1) both",
        "slide-right": "slide-right 250ms cubic-bezier(0.22,1,0.36,1) both",
        "scale-in": "scale-in 250ms cubic-bezier(0.34,1.56,0.64,1) both",
        "pulse-accent": "pulse-accent 1600ms ease-in-out infinite",
        shimmer: "shimmer 1400ms linear infinite",
      },
    },
  },
  plugins: [],
} satisfies Partial<Config>;

export default preset;
