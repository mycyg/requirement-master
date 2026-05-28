/**
 * Visual sweep of the Tauri client front-end (loaded from vite dev at 5174).
 * Auth + invoke are mocked via `__YQGL_MOCK_INVOKE__`. We mount Hub once,
 * then drive navigation by mutating the URL hash inside the same SPA session
 * — that way HashRouter sees a real popstate and React re-renders the route
 * instead of reloading the whole bundle (which we observed renders blank for
 * non-default hashes when started from a fresh document).
 */
import fs from "node:fs";
import path from "node:path";
import { expect, test, type Page } from "@playwright/test";

const OUT = path.resolve(process.cwd(), "..", "screenshots", "aurora", "client");
fs.mkdirSync(OUT, { recursive: true });

const CLIENT_BASE = "http://127.0.0.1:5174";

const ROUTES: { hash: string; file: string }[] = [
  { hash: "#/",              file: "01-hub" },
  { hash: "#/inbox",         file: "02-inbox" },
  { hash: "#/settings",      file: "03-settings" },
  { hash: "#/me/workload",   file: "04-my-workload" },
  { hash: "#/me/calendar",   file: "05-my-calendar" },
  { hash: "#/me/knowledge",  file: "06-knowledge" },
  { hash: "#/me/pulse",      file: "07-project-pulse" },
  { hash: "#/onboarding",    file: "08-onboarding" },
];

async function shoot(page: Page, name: string) {
  await page.screenshot({ path: path.join(OUT, name), fullPage: false });
}

test.use({ baseURL: CLIENT_BASE, viewport: { width: 1280, height: 800 } });

test("客户端 9 个路由：light + dark 截图", async ({ page, request }) => {
  // Real backend identify so worker token exists.
  const idRes = await request.post("http://192.168.0.224:8080/api/auth/identify", {
    data: { nickname: "小光" },
  });
  expect(idRes.ok()).toBeTruthy();
  const cookies = idRes.headers()["set-cookie"];
  const cookiePart = cookies!.split(";")[0];
  const [name, value] = cookiePart.split("=");
  const regRes = await request.post("http://192.168.0.224:8080/api/client-devices/register", {
    data: { device_name: "client-spec", platform: "win32" },
    headers: { Cookie: `${name}=${value}` },
  });
  const clientToken = (await regRes.json()).client_token;

  // Mock Tauri invoke so React components don't throw.
  await page.addInitScript(([tok, nick]) => {
    (window as any).__YQGL_MOCK_INVOKE__ = async (cmd: string) => {
      if (cmd === "get_config") {
        return {
          server_ip: "192.168.0.224", server_port: 8080,
          server_url: "http://192.168.0.224:8080",
          nickname: nick, cookie_token: "session", client_token: tok,
          sync_root: "D:\\工作需求", drive_sync_root: "D:\\工作需求\\项目网盘",
          drive_sync_enabled: false, drive_sync_mode: "download",
          drive_sync_paused: false, availability_status: "free",
          availability_text: null, reminder_offsets_minutes: [1440, 120, 0],
          theme: "auto",
        };
      }
      if (cmd === "me") return { id: "fake", nickname: nick };
      if (cmd === "list_my" || cmd === "list_public_pool") return [];
      if (cmd === "list_workspaces") return [];
      if (cmd === "get_requirement") return null;
      if (cmd === "test_server") return { ok: true, status: 200 };
      return {};
    };
  }, [clientToken, "小光"]);

  // Some client pages (Inbox/MyWorkload/Knowledge/ProjectPulse/Calendar) hit
  // `/api/...` directly via clientFetch. Stub them so they get plausible
  // empty data instead of a 401 (which crashes `.map()` and tears down React).
  await page.route(/\/api\/(notifications|planning\/workload|project-health|calendar\/events|knowledge\/search)/, async (route) => {
    await route.fulfill({
      status: 200, contentType: "application/json",
      body: route.request().url().includes("workload") ? JSON.stringify([{
            user_id: "fake", nickname: "小光", is_online: true,
            availability_status: "free", availability_text: null,
            task_count: 3, estimate_hours: 18.5, capacity_hours: 30,
            load_percent: 62, overdue_count: 1, blocked_count: 0, due_this_week_count: 2,
            requirements: [
              { id: "r1", code: "DEMO-001", title: "客户端 E2E 截图", project_id: "p1", project_slug: "demo", status: "doing", due_at: new Date(Date.now()+86400000).toISOString(), estimate_hours: 6, progress_percent: 55, blocked_reason: null },
              { id: "r2", code: "DEMO-002", title: "毛玻璃面板调优", project_id: "p1", project_slug: "demo", status: "claimed", due_at: new Date(Date.now()+172800000).toISOString(), estimate_hours: 4, progress_percent: 20, blocked_reason: null },
            ],
          }])
          : route.request().url().includes("project-health") ? JSON.stringify([
            { project_id: "p1", project_name: "Demo 项目", project_slug: "demo", score: 82, risk_level: "healthy", risks: [], overdue_count: 1, blocked_count: 0, unclaimed_count: 0, due_soon_count: 2, revision_count: 0, change_count: 0, active_count: 5, accepted_count: 12, throughput_30d: 12, avg_cycle_hours: 18 },
            { project_id: "p2", project_name: "客户端重构", project_slug: "client", score: 65, risk_level: "watch", risks: ["1 项逾期", "2 项临期"], overdue_count: 1, blocked_count: 0, unclaimed_count: 0, due_soon_count: 2, revision_count: 0, change_count: 0, active_count: 3, accepted_count: 4, throughput_30d: 6, avg_cycle_hours: 22 },
          ])
          : route.request().url().includes("calendar/events") ? JSON.stringify([
            { id: "e1", title: "DEMO-001 截止", description: null, event_type: "requirement_due", requirement_id: "r1", project_id: "p1", start_at: null, end_at: new Date(Date.now()+86400000).toISOString(), participant_user_ids: ["fake"] },
            { id: "e2", title: "团队周会", description: null, event_type: "custom", requirement_id: null, project_id: "p1", start_at: new Date(Date.now()+3600000).toISOString(), end_at: new Date(Date.now()+7200000).toISOString(), participant_user_ids: ["fake"] },
          ])
          : route.request().url().includes("knowledge/search") ? '{"query":"","hits":[]}'
          : JSON.stringify([
            { id: "n1", type: "requirement.ready", severity: "high", title: "新工单来了 DEMO-001", body: "客户端 E2E 截图", target_url: null, requirement_id: "r1", read_at: null, created_at: new Date().toISOString() },
            { id: "n2", type: "deadline.due_24h", severity: "normal", title: "DEMO-002 还有 24 小时", body: null, target_url: null, requirement_id: "r2", read_at: null, created_at: new Date().toISOString() },
          ]),
    });
  });
  await page.route(/\/api\/auth\/me/, async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: '{"id":"fake","nickname":"小光"}' });
  });

  // Mount once at hub
  await page.goto(`${CLIENT_BASE}/#/`);
  await page.waitForLoadState("domcontentloaded");
  await page.waitForFunction(() => {
    const r = document.getElementById("root");
    return !!(r && r.children.length > 0);
  }, { timeout: 8000 });

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

    for (const r of ROUTES) {
      // In-app navigation via location.hash so HashRouter does its thing
      // without a full document reload (which is what was rendering blank).
      await page.evaluate((h) => {
        window.location.hash = h.replace(/^#/, "");
      }, r.hash);
      await page.waitForTimeout(900);
      await shoot(page, `${r.file}.${theme}.png`);
    }
  }
});
