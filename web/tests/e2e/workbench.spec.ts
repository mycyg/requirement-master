import { expect, test, type Browser, type Page } from "@playwright/test";

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

test("核心工作中台浏览器流：在线接单人、DDL、日程、网盘留言和 TTS 友好错误", async ({ browser }) => {
  const consoleErrors: string[] = [];
  const workerNick = `e2e-worker-${stamp()}`;
  const ownerNick = `e2e-owner-${stamp()}`;
  const projectName = `E2E 项目 ${stamp()}`;
  const projectSlug = `e2e-${stamp()}`;
  const requirementText = `请做一个 E2E 验证用工作台小组件 ${stamp()}`;
  const calendarTitle = `E2E 日程 ${stamp()}`;
  const commentText = `需求补充：请在 ${projectName} 的工作台增加 E2E 导出按钮。`;

  const workerContext = await keepWorkerOnline(browser, workerNick);
  const ownerContext = await browser.newContext({ locale: "zh-CN" });
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

    await page.getByPlaceholder(/写清楚/).fill(requirementText);
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
