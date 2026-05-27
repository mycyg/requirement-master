import fs from "node:fs";
import path from "node:path";
import { expect, test, type Browser, type BrowserContext, type Page } from "@playwright/test";

const screenshotDir = path.resolve(process.cwd(), "..", "screenshots");

async function saveScreenshot(page: Page, name: string) {
  fs.mkdirSync(screenshotDir, { recursive: true });
  await page.screenshot({ path: path.join(screenshotDir, name), fullPage: true });
}

function stamp(): string {
  return Date.now().toString(36);
}

function localDateTime(minutesFromNow: number): string {
  const d = new Date(Date.now() + minutesFromNow * 60_000);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

async function identify(page: Page, nickname: string) {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "填一个昵称" })).toBeVisible();
  await page.getByPlaceholder(/比如/).fill(nickname);
  await page.getByRole("button", { name: /进入/ }).click();
  await expect(page.getByText(nickname, { exact: true })).toBeVisible();
}

async function keepWorkerOnline(browser: Browser, nickname: string) {
  const context = await browser.newContext({ locale: "zh-CN" });
  const page = await context.newPage();
  await identify(page, nickname);
  await context.request.put("/api/users/me/status", {
    data: { availability_status: "free", availability_text: "在线等单" },
  });
  await page.goto("/dashboard");
  await expect(page.getByRole("heading", { name: /接单看板/ })).toBeVisible();
  await expect(page.getByText("实时在线")).toBeVisible();
  return context;
}

async function enableFakeRecorder(context: BrowserContext) {
  await context.addInitScript(() => {
    const fakeStream = { getTracks: () => [{ stop: () => undefined }] };
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: { getUserMedia: async () => fakeStream },
    });
    class FakeMediaRecorder {
      ondataavailable: ((event: { data: Blob }) => void) | null = null;
      onstop: (() => void) | null = null;
      constructor(_: any, __?: any) {}
      start() {}
      stop() {
        this.ondataavailable?.({ data: new Blob(["fake audio"], { type: "audio/webm" }) });
        this.onstop?.();
      }
    }
    (window as any).MediaRecorder = FakeMediaRecorder;
  });
}

test("核心工作中台浏览器流：在线接单人、DDL、日程、网盘留言和 TTS 友好错误", async ({ browser }) => {
  const consoleErrors: string[] = [];
  const workerNick = `e2e-worker-${stamp()}`;
  const ownerNick = `e2e-owner-${stamp()}`;
  const projectName = `E2E 项目 ${stamp()}`;
  const projectSlug = `e2e-${stamp()}`;
  const requirementText = `请做一个 E2E 验证用工作台小组件 ${stamp()}`;
  const calendarTitle = `E2E 日程 ${stamp()}`;
  const commentText = `需求补充：请在 ${projectName} 的工作台增加 E2E 导出按钮。`;
  const meetingText = `会议记录：需求补充，请给 ${projectName} 增加一个会议导出按钮，并进入需求评估。`;

  const workerContext = await keepWorkerOnline(browser, workerNick);
  const ownerContext = await browser.newContext({ locale: "zh-CN" });
  await enableFakeRecorder(ownerContext);
  await ownerContext.route("**/api/voice/transcribe", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ text: "语音输入 E2E", language: "zh", ms: 12 }),
    });
  });
  const page = await ownerContext.newPage();
  page.on("console", (msg) => {
    if (msg.type() === "error") consoleErrors.push(msg.text());
  });

  try {
    await identify(page, ownerNick);

    await page.getByRole("button", { name: /新建项目/ }).click();
    await page.getByPlaceholder(/项目名/).fill(projectName);
    await page.getByPlaceholder(/slug/).fill(projectSlug);
    await page.getByRole("button", { name: "创建" }).click();
    const projectLink = page.getByRole("link", { name: projectName }).first();
    await expect(projectLink).toBeVisible();
    const projectHref = await projectLink.getAttribute("href");
    expect(projectHref).toMatch(/^\/p\//);

    await projectLink.click();
    await expect(page.getByRole("heading", { name: projectName })).toBeVisible();
    await page.getByRole("link", { name: /提一个需求/ }).click();
    await expect(page.getByRole("heading", { name: "提一个需求" })).toBeVisible();

    const voiceButton = page.getByRole("button", { name: /按住说话/ });
    await voiceButton.dispatchEvent("pointerdown");
    await page.getByRole("button", { name: /松手停止/ }).dispatchEvent("pointerup");
    await expect(page.getByPlaceholder(/写清楚/)).toHaveValue(/语音输入 E2E/);
    await page.getByPlaceholder(/写清楚/).fill(`${requirementText}\n${await page.getByPlaceholder(/写清楚/).inputValue()}`);
    await expect(page.getByRole("button", { name: /下一步：上传附件/ })).toBeDisabled();
    await expect(page.getByText(/\d+ 人在线/)).toBeVisible();
    await expect(page.getByText(workerNick, { exact: true })).toBeVisible();
    await expect(page.getByText("空闲").first()).toBeVisible();
    await page.getByPlaceholder("搜索已登录用户").fill(workerNick);
    const workerCard = page.locator("div.rounded-lg.border.p-2").filter({ hasText: workerNick }).first();
    await expect(workerCard).toBeVisible();
    await workerCard.getByRole("button", { name: "负责人" }).click();
    await expect(page.getByText(workerNick, { exact: true }).first()).toBeVisible();

    await page.getByLabel(/DDL/).fill(localDateTime(24 * 60));
    await page.getByRole("button", { name: /下一步：上传附件/ }).click();
    await expect(page.getByRole("heading", { name: /附件/ })).toBeVisible();

    await page.goto("/calendar");
    await expect(page.getByRole("heading", { name: /日程表/ })).toBeVisible();
    await page.getByPlaceholder(/和接单人/).fill(calendarTitle);
    await page.locator("input[type='datetime-local']").fill(localDateTime(90));
    await page.locator("label").filter({ hasText: workerNick }).getByRole("checkbox").check();
    await page.getByRole("button", { name: /保存日程/ }).click();
    await expect(page.getByText(calendarTitle)).toBeVisible();

    await page.goto(`${projectHref}/drive`);
    await expect(page.getByRole("heading", { name: /项目网盘/ })).toBeVisible();
    await page.locator("input[type='file']").setInputFiles({
      name: "e2e-note.md",
      mimeType: "text/markdown",
      buffer: Buffer.from("# E2E Drive\n\nhello from browser e2e"),
    });
    await expect(page.getByText("e2e-note.md")).toBeVisible();
    await page.getByRole("button", { name: "e2e-note.md" }).click();
    await expect(page.getByText(/E2E Drive/)).toBeVisible();
    await page.getByRole("button", { name: "关闭预览" }).click();

    await page.getByPlaceholder(/在这个文件夹留句话/).fill(commentText);
    await page.getByRole("button", { name: /^留言$/ }).click();
    await expect(page.getByText("已生成草稿")).toBeVisible();
    await expect(page.getByRole("link", { name: "去澄清" })).toBeVisible();

    await page.goto(`${projectHref}/meetings`);
    await expect(page.getByRole("heading", { name: "会议纪要" })).toBeVisible();
    await page.getByPlaceholder(/会议标题/).fill("E2E 会议纪要");
    await page.locator("input[type='file']").setInputFiles({
      name: "e2e-meeting.txt",
      mimeType: "text/plain",
      buffer: Buffer.from(meetingText, "utf-8"),
    });
    await expect(page.getByText("E2E 会议纪要")).toBeVisible();
    await expect(page.getByText(/已生成|处理中/).first()).toBeVisible();
    await expect(page.getByText(/需求评估/)).toBeVisible({ timeout: 20000 });
    await expect(page.getByRole("heading", { name: /需求补充/ })).toBeVisible();
    await saveScreenshot(page, "05_meetings.png");
    await page.getByRole("button", { name: /进入评估/ }).first().click();
    await expect(page.getByRole("link", { name: "去澄清" })).toBeVisible();

    await page.getByRole("button", { name: "设置" }).click();
    await expect(page.getByRole("heading", { name: "设置" })).toBeVisible();
    await expect(page.getByText(/无法读取 TTS 音色/)).toBeVisible();

    expect(consoleErrors.join("\n")).not.toContain("Unexpected end of JSON input");
    expect(consoleErrors.join("\n")).not.toContain("SyntaxError");
  } finally {
    await ownerContext.close();
    await workerContext.close();
  }
});

test("需求个人工作区 UI：进度、阻塞、清单和动态", async ({ browser }) => {
  const context = await browser.newContext({ locale: "zh-CN" });
  const page = await context.newPage();
  await identify(page, `e2e-workspace-${stamp()}`);
  await page.route("**/api/requirements/e2e-workspace", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        id: "e2e-workspace",
        code: "E2E-999",
        project_id: "project-1",
        project_slug: "e2e",
        submitter_nickname: "owner",
        claimed_by_user_id: "me",
        claimed_by_nickname: "e2e worker",
        title: "工作区 UI 验证",
        raw_description: "workspace ui",
        summary_md: "## Goal\n验证个人工作区",
        status: "doing",
        priority: "normal",
        start_at: null,
        due_at: new Date(Date.now() + 86400000).toISOString(),
        source_meeting_id: null,
        source_requirement_id: null,
        claimed_at: null,
        done_at: null,
        delivered_at: null,
        delivery_doc_ready_at: null,
        accepted_at: null,
        sync_state: "synced",
        assignees: [{ user_id: "me", nickname: "e2e worker", role: "lead", assigned_at: new Date().toISOString() }],
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      }),
    });
  });
  await page.route("**/api/requirements/e2e-workspace/attachments", (route) => route.fulfill({ contentType: "application/json", body: "[]" }));
  await page.route("**/api/requirements/e2e-workspace/workspaces", (route) => route.fulfill({
    contentType: "application/json",
    body: JSON.stringify([{
      id: "ws-1",
      requirement_id: "e2e-workspace",
      user_id: "me",
      nickname: "e2e worker",
      phase: "联调",
      progress_percent: 62,
      status_note: "接口已经接好，正在验收页面。",
      blocked_reason: "等一个测试账号。",
      items: [{ id: "item-1", workspace_id: "ws-1", title: "补齐截图", status: "doing", sort_order: 1, created_at: new Date().toISOString(), updated_at: new Date().toISOString() }],
      updates: [{ id: "upd-1", requirement_id: "e2e-workspace", workspace_id: "ws-1", actor_nickname: "e2e worker", kind: "manual", body: "今天推进到联调。", phase: "联调", progress_percent: 62, created_at: new Date().toISOString() }],
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    }]),
  }));
  await page.goto("/r/e2e-workspace");
  await expect(page.getByRole("heading", { name: "工作区 UI 验证" })).toBeVisible();
  await page.getByRole("button", { name: /工作区/ }).click();
  await expect(page.getByText("联调 · 62%")).toBeVisible();
  await expect(page.getByText(/等一个测试账号/)).toBeVisible();
  await expect(page.getByText("补齐截图")).toBeVisible();
  await expect(page.getByText("今天推进到联调。")).toBeVisible();
  await saveScreenshot(page, "06_workspace.png");
  await context.close();
});
