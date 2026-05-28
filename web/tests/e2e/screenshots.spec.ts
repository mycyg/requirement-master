/**
 * Visual sweep — visit every reachable page in light + dark mode,
 * full-page screenshot to screenshots/aurora/. Used as a manual review
 * artefact; passes as long as nothing crashes.
 */
import fs from "node:fs";
import path from "node:path";
import { expect, test, type Page } from "@playwright/test";

const OUT = path.resolve(process.cwd(), "..", "screenshots", "aurora");

fs.mkdirSync(OUT, { recursive: true });

function stamp(): string {
  return Date.now().toString(36) + Math.random().toString(36).slice(2, 5);
}

async function identify(page: Page, nickname: string) {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: /昵称/ })).toBeVisible();
  await page.getByPlaceholder(/比如/).fill(nickname);
  await page.getByRole("button", { name: /进入/ }).click();
  await expect(page.getByText(nickname, { exact: true })).toBeVisible({ timeout: 10_000 });
}

async function setTheme(page: Page, mode: "light" | "dark") {
  await page.evaluate((m) => {
    document.documentElement.setAttribute("data-theme", m);
    try {
      localStorage.setItem("yqgl.theme", m);
    } catch {}
  }, mode);
  await page.waitForTimeout(200);
}

async function shoot(page: Page, name: string) {
  const p = path.join(OUT, name);
  await page.screenshot({ path: p, fullPage: true });
}

const SHOTS = [
  { path: "/", file: "01-home" },
  { path: "/dashboard", file: "02-dashboard" },
  { path: "/knowledge", file: "03-knowledge" },
  { path: "/planning", file: "04-planning" },
  { path: "/health", file: "05-health" },
  { path: "/calendar", file: "06-calendar" },
  { path: "/notifications", file: "07-notifications" },
  { path: "/drive", file: "08-drive" },
];

test("视觉巡检：每页 light + dark 截图", async ({ page }) => {
  await identify(page, `shot-${stamp()}`);

  for (const mode of ["light", "dark"] as const) {
    await setTheme(page, mode);
    for (const s of SHOTS) {
      await page.goto(s.path);
      await page.waitForLoadState("domcontentloaded");
      await page.waitForTimeout(500);
      await shoot(page, `${s.file}.${mode}.png`);
    }
  }
});

test("交互流截图：5 步 wizard + 看板下拉 + ⌘K + 主题切换", async ({ page }) => {
  await identify(page, `flow-${stamp()}`);
  await setTheme(page, "light");

  // Glass top nav + dropdown open
  await page.getByRole("button", { name: /看板/ }).first().click();
  await page.waitForTimeout(200);
  await shoot(page, "20-boards-dropdown-open.light.png");
  await page.keyboard.press("Escape");

  // ⌘K palette
  await page.keyboard.press("Control+k").catch(() => page.keyboard.press("Meta+k"));
  await page.waitForTimeout(200);
  await shoot(page, "21-command-menu.light.png");
  await page.getByPlaceholder(/搜索命令/).fill("排期");
  await page.waitForTimeout(200);
  await shoot(page, "22-command-menu-search.light.png");
  await page.keyboard.press("Escape");

  // Dark variant
  await setTheme(page, "dark");
  await page.keyboard.press("Control+k").catch(() => page.keyboard.press("Meta+k"));
  await page.waitForTimeout(200);
  await shoot(page, "23-command-menu.dark.png");
  await page.keyboard.press("Escape");

  // 5-step wizard (create project + go to wizard)
  await setTheme(page, "light");
  const name = `Shot ${stamp()}`;
  const slug = `shot-${stamp()}`.toLowerCase();
  await page.getByRole("button", { name: /新建项目/ }).click();
  await page.getByPlaceholder(/项目名/).fill(name);
  await page.getByPlaceholder(/slug/).fill(slug);
  await page.getByRole("button", { name: "创建" }).click();
  await page.getByRole("link", { name: new RegExp(name) }).first().click();
  await page.getByRole("link", { name: /提一条新需求/ }).click();
  await page.waitForTimeout(300);
  await shoot(page, "30-wizard-step1.light.png");
  await page.locator("textarea").first().fill("视觉巡检需求示例");
  await page.getByRole("button", { name: /下一步/ }).click();
  await page.waitForTimeout(300);
  await shoot(page, "31-wizard-step2-assignee.light.png");
  await page.getByRole("button", { name: /下一步/ }).click();
  await page.waitForTimeout(300);
  await shoot(page, "32-wizard-step3-due.light.png");
});
