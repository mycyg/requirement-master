import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig, devices } from "@playwright/test";

const webDir = path.dirname(fileURLToPath(import.meta.url));
const rootDir = path.resolve(webDir, "..");
const runId = process.env.YQGL_E2E_RUN_ID || `${Date.now()}-${process.pid}`;
const runtimeDir = path.join(rootDir, ".e2e", runId);
const dataDir = path.join(runtimeDir, "data");
const dbPath = path.join(runtimeDir, "e2e.db").replace(/\\/g, "/");
const apiPort = process.env.YQGL_E2E_API_PORT || "18080";
const webPort = process.env.YQGL_E2E_WEB_PORT || "15173";
const apiBase = `http://127.0.0.1:${apiPort}`;
const webBase = `http://127.0.0.1:${webPort}`;

fs.mkdirSync(dataDir, { recursive: true });

export default defineConfig({
  testDir: "./tests/e2e",
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [["list"], ["html", { open: "never", outputFolder: "playwright-report" }]],
  use: {
    baseURL: webBase,
    locale: "zh-CN",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  webServer: [
    {
      command: `python -m uvicorn main:app --app-dir app --host 127.0.0.1 --port ${apiPort}`,
      cwd: rootDir,
      url: `${apiBase}/api/health`,
      timeout: 30_000,
      reuseExistingServer: false,
      env: {
        ...process.env,
        APP_ENV: "development",
        COOKIE_SECRET: "e2e-cookie-secret",
        DATABASE_URL: `sqlite:///${dbPath}`,
        DATA_DIR: dataDir,
        INTERNAL_BASE_URL: apiBase,
        LLM_API_KEY: "",
      },
    },
    {
      command: `npm run dev -- --host 127.0.0.1 --port ${webPort}`,
      cwd: webDir,
      url: webBase,
      timeout: 30_000,
      reuseExistingServer: false,
      env: {
        ...process.env,
        YQGL_BASE: apiBase,
      },
    },
  ],
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
});
