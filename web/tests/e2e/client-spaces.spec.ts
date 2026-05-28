/**
 * 双 Space + 派活流程的视觉回归。沿用 client-routes.spec.ts 的 invoke 拦截
 * 模式（直接命中 vite dev 5174），但额外覆盖：
 *   - SpaceSwitcher 下拉 + 切换到派活
 *   - HubDispatch 各 dtab
 *   - NewRequirement 5 步 wizard 截图
 *   - TaskDetail 派活视角的 ActionRailDispatch
 *   - ProjectDrive 项目网盘
 *
 * 用 light + dark 两种主题各跑一遍。
 */
import fs from "node:fs";
import path from "node:path";
import { expect, test, type Page } from "@playwright/test";

const OUT = path.resolve(process.cwd(), "..", "screenshots", "aurora", "submitter");
fs.mkdirSync(OUT, { recursive: true });

const CLIENT_BASE = "http://127.0.0.1:5174";

async function shoot(page: Page, name: string) {
  const finalPath = path.join(OUT, name);
  const tmpPath = path.join(OUT, `${name}.${Date.now()}.tmp.png`);
  await page.screenshot({ path: tmpPath, fullPage: false });
  try {
    fs.rmSync(finalPath, { force: true });
    fs.renameSync(tmpPath, finalPath);
  } catch {
    fs.copyFileSync(tmpPath, finalPath);
    fs.rmSync(tmpPath, { force: true });
  }
}

async function skipOnboarding(page: Page) {
  const skip = page.getByRole("button", { name: /跳过引导/ });
  if (await skip.count()) {
    await skip.first().click();
  }
}

test.use({ baseURL: CLIENT_BASE, viewport: { width: 1280, height: 800 } });
test.skip(process.env.YQGL_CLIENT_E2E !== "1", "requires client-tauri dev server; run with YQGL_CLIENT_E2E=1");

test("客户端双 Space + 派活全流程截图", async ({ page }) => {
  const clientToken = "mock-client-token";

  await page.addInitScript(([tok, nick]) => {
    const SAMPLE_REQS = [
      { id: "r-mine-1", code: "DEMO-101", project_id: "p1", project_slug: "demo",
        title: "客户端 双 Space 视觉回归", status: "ready", priority: "normal",
        submitter_user_id: "fake", submitter_nickname: nick,
        due_at: new Date(Date.now() + 86400000).toISOString(), assignees: [] },
      { id: "r-mine-2", code: "DEMO-102", project_id: "p1", project_slug: "demo",
        title: "等接单：派活路径打通", status: "ready", priority: "high",
        submitter_user_id: "fake", submitter_nickname: nick,
        due_at: new Date(Date.now() + 172800000).toISOString(), assignees: [] },
      { id: "r-mine-3", code: "DEMO-103", project_id: "p1", project_slug: "demo",
        title: "等你验收：交付样例", status: "delivered", priority: "normal",
        submitter_user_id: "fake", submitter_nickname: nick,
        due_at: new Date(Date.now() + 600000).toISOString(),
        assignees: [{ user_id: "u2", nickname: "小杨", role: "lead" }] },
    ];
    const SAMPLE_USERS = [
      { id: "u1", nickname: "小光", is_online: true, availability_status: "free" },
      { id: "u2", nickname: "小杨", is_online: true, availability_status: "busy" },
      { id: "u3", nickname: "阿明", is_online: false },
    ];
    const SAMPLE_PROJECTS = [
      { id: "p1", name: "Demo 项目", slug: "demo" },
      { id: "p2", name: "客户端重构", slug: "client" },
    ];
    (window as any).__YQGL_MOCK_INVOKE__ = async (cmd: string, args: any) => {
      switch (cmd) {
        case "get_config":
          return {
            server_ip: "192.168.5.53", server_port: 8080,
            server_url: "http://192.168.5.53:8080",
            nickname: nick, cookie_token: "session", client_token: tok,
            sync_root: "D:\\工作需求", drive_sync_root: "D:\\工作需求\\项目网盘",
            drive_sync_enabled: false, drive_sync_mode: "download",
            drive_sync_paused: false, availability_status: "free",
            availability_text: null, reminder_offsets_minutes: [1440, 120, 0],
            theme: "auto",
          };
        case "me": return { id: "fake", nickname: nick };
        case "list_my": return args?.mine ? SAMPLE_REQS : SAMPLE_REQS.filter((r) => r.status === "ready");
        case "list_public_pool": return SAMPLE_REQS.filter((r) => r.status === "ready");
        case "get_requirement":
          return SAMPLE_REQS.find((r) => r.id === args?.reqId) ?? SAMPLE_REQS[2];
        case "list_workspaces": return [];
        case "list_attachments": return [];
        case "list_my_projects": return SAMPLE_PROJECTS;
        case "list_users": return SAMPLE_USERS;
        case "list_drive_root": return { items: [] };
        case "test_server": return { ok: true, status: 200 };
        case "create_requirement": return { id: "r-new", code: "DEMO-NEW" };
        case "submit_requirement": return { ok: true };
        case "accept_requirement": return { ok: true };
        case "request_revision": return { ok: true };
        default: return {};
      }
    };
  }, [clientToken, "小光"]);

  // Stub the few HTTP routes the SPA hits directly.
  await page.route(/\/api\/(notifications|planning\/workload|project-health|calendar\/events|knowledge\/search|auth\/me)/, async (route) => {
    const url = route.request().url();
    if (url.includes("auth/me")) {
      return route.fulfill({ status: 200, contentType: "application/json", body: '{"id":"fake","nickname":"小光"}' });
    }
    return route.fulfill({ status: 200, contentType: "application/json", body: "[]" });
  });

  await page.goto(`${CLIENT_BASE}/#/`);
  await page.waitForLoadState("domcontentloaded");
  await page.waitForFunction(() => {
    const r = document.getElementById("root");
    return !!(r && r.children.length > 0);
  }, { timeout: 8000 });
  await skipOnboarding(page);

  for (const theme of ["light", "dark"] as const) {
    await page.evaluate((m) => {
      document.documentElement.setAttribute("data-theme", m);
      localStorage.setItem("yqgl.theme", m);
    }, theme);
    await page.addStyleTag({ content: `
      body { background: ${theme === "dark"
        ? "linear-gradient(135deg,#0d0d1a 0%,#1a1530 50%,#1f1029 100%) !important"
        : "linear-gradient(135deg,#e8e6f5 0%,#e3e0f0 50%,#f0e6e9 100%) !important"} }
    ` });

    // Default = 接活 Space (work). Visit Hub.
    await page.evaluate(() => { window.location.hash = "/"; });
    await page.waitForTimeout(600);
    await shoot(page, `01-work-hub.${theme}.png`);

    // Open the Space switcher dropdown, screenshot, then click 派活.
    const chip = page.locator('button[title*="切换工作空间"]').first();
    await chip.click();
    await page.waitForTimeout(250);
    await shoot(page, `02-space-switcher-open.${theme}.png`);
    await page.getByRole("button", { name: /派活/ }).first().click();
    await page.waitForTimeout(700);
    await shoot(page, `03-dispatch-hub-default.${theme}.png`);

    // Each dispatch tab
    for (const dtab of ["drafts", "clarifying", "ready", "working", "review", "accepted"]) {
      await page.evaluate((d) => { window.location.hash = `/?dtab=${d}`; }, dtab);
      await page.waitForTimeout(450);
      await shoot(page, `04-dispatch-${dtab}.${theme}.png`);
    }

    // New requirement wizard
    await page.evaluate(() => { window.location.hash = "/r/new"; });
    await page.waitForTimeout(600);
    await shoot(page, `05-new-req-step0.${theme}.png`);

    // TaskDetail with delivered status — ActionRailDispatch hero
    await page.evaluate(() => { window.location.hash = "/r/r-mine-3"; });
    await page.waitForTimeout(700);
    await shoot(page, `06-task-detail-delivered.${theme}.png`);

    // Project drive picker
    await page.evaluate(() => { window.location.hash = "/p"; });
    await page.waitForTimeout(500);
    await shoot(page, `07-drive-picker.${theme}.png`);

    await page.evaluate(() => { window.location.hash = "/p/p1"; });
    await page.waitForTimeout(500);
    await shoot(page, `08-drive-empty.${theme}.png`);

    // Switch back to 接活 with Ctrl+1
    await page.keyboard.press("Control+1");
    await page.waitForTimeout(400);
    await page.evaluate(() => { window.location.hash = "/"; });
    await page.waitForTimeout(400);
    await shoot(page, `09-back-to-work.${theme}.png`);
  }
});
