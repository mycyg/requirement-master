# 需求管理大师 · Requirement Master

> 老板的需求永远说不清？那就别让他说，让 AI 替他说清。
> 产品一句「你看着改」当场把你送走？把他推进 AI 澄清流程，问到他自己都懂。
> 接单人问「附件呢 / DDL 呢 / 谁验收」，派活人回「我以为你懂」——行，现在系统替你追到底。
>
> **EN** — Boss can't describe what he wants? Don't make him — make the AI drag it out of him.
> PM says "just tweak it however" and your brain blue-screens? Shove him into the AI clarify flow until *he* understands his own request.
> Worker asks "attachments? deadline? who signs off?" and the dispatcher goes "I assumed you knew" — cool, the system now interrogates him for you.

**需求管理大师 / Requirement Master** 是一个**局域网工作中台**：Web 端负责派活、澄清、验收、看全局；Rust/Tauri 本地端负责接活、同步文件、系统通知、工作区进度和交付。一句话——把「群里口嗨」变成「可追踪、可交付、可验收」的项目流水线。

**EN** — A **LAN-only work hub**. The Web side dispatches, clarifies, accepts, and shows the big picture; the Rust/Tauri desktop side claims work, syncs files, fires OS notifications, tracks workspace progress, and delivers. In one line: it turns "vibes in a group chat" into a *trackable, deliverable, sign-off-able* pipeline.

![Rust 毛玻璃客户端 / Rust frosted-glass client](screenshots/readme/rust-client-glass.png)

> 截图说明：README 只用 `screenshots/readme/` 里裁干净的图，不放报错图、不放桌面隐私、不拿聊天窗口祭天。
> Screenshot policy: only clean crops from `screenshots/readme/`. No error dumps, no desktop privacy leaks, no chat windows sacrificed to the demo gods.

---

## 这玩意儿到底治啥病 · What it actually fixes

- 老板说「做个差不多的」→ AI 先追问，追到能落地为止。
- 产品说「先这样、再那样」→ 需求有状态、有 DDL、有负责人，不靠玄学记忆。
- 接单人说「我不知道谁让我干的」→ 每条需求都有负责人、协作者、工作区、交付记录。
- 文件在群里反复横跳 → 项目网盘统一收口，能预览、能回收、能进知识库。
- 会开完大家都很感动 → 录音/文本自动出纪要，还能识别「新增需求 / 需求变更」。
- 领导问「项目健康吗」→ 健康度、排期、通知、知识库一把梭，别再手搓周报。

**EN**

- Boss says "make something roughly like X" → the AI keeps asking until it's buildable.
- PM says "this, then that" → requirements have status, a deadline, an owner. No more memory-based archaeology.
- Worker says "I don't even know who assigned this" → every requirement has an owner, collaborators, a workspace, and a delivery record.
- Files ping-ponging in chat → one project drive: preview, trash/restore, and feed into the knowledge base.
- Everyone's "so moved" after a meeting → audio/text auto-generates minutes and flags new-or-changed requirements.
- Leadership asks "is the project healthy?" → health score, planning, notifications, knowledge — all in one. Stop hand-rolling weekly reports.

---

## 双端分工 · Two ends, one job

| 端 / Side | 干啥 / Does | 能接活吗 / Can claim work? |
|---|---|---|
| **Web 派活台 / Web dispatch deck** | 提需求、AI 澄清、指定接单人、看项目/排期/健康/知识库、验收、返工 | ❌ 不能 / No |
| **Rust 毛玻璃本地端 / Rust desktop** | 派活 + 接活 + 本地文件 + 托盘常驻 + 系统通知 + 网盘同步 + 交付 | ✅ 能 / Yes |

Web 是「指挥室」，本地端是「干活桌」。浏览器里**不让你偷偷接单交付**——本地端会带 client device token，服务端硬校验。想绕 UI 直接打接口？后端淡淡地说一句：别闹。

**EN** — Web is the *war room*, the desktop is the *workbench*. The browser **can't secretly claim or deliver** — the desktop carries a client-device token the server hard-verifies. Try to bypass the UI and hit the API raw? The backend just says: nice try.

---

## 截图区 · Screenshots

### 派活台：谁发的活、谁验收、谁背锅，一眼看见 · Dispatch: who sent it, who signs off, who's on the hook

![派活台 / Dispatch deck](screenshots/readme/dispatch-space.png)

### 新建需求：先把话说明白，再让人开干 · New requirement: say it clearly first, then let people build

![新建需求 / New requirement](screenshots/readme/new-requirement.png)

### 项目网盘：文件别再埋在聊天记录第 800 层 · Project drive: stop burying files 800 messages deep

![项目网盘 / Project drive](screenshots/readme/project-drive.png)

### 项目健康度：需求炸没炸，别等老板拍桌才知道 · Project health: know it's on fire before the boss does

![项目健康度 / Project health](screenshots/readme/project-health.png)

---

## 核心功能 · Core features

### 🤖 AI 澄清需求 · AI requirement clarification

用户扔一句「想做个管理系统」，AI 接着追问：谁用、何时要、验收标准、附件在哪、谁负责、DDL 是啥。问清楚后生成摘要，**提交人确认后才能投递**。
提示词全英文写，但给用户看的输出用用户的语言。流式返回「思考中」气泡 + 最终结果，澄清不卡壳。

**EN** — Drop "I want a management system" and the AI fires back: who uses it, when's it due, acceptance criteria, where are the attachments, who owns it, what's the deadline. It then writes a summary, and **only the submitter can ship it after confirming**. Prompts are written in English; user-facing output speaks the user's language. Streams a "thinking…" bubble + final result — no stuck spinners.

### 👥 多接单人 · Multiple assignees

一条需求可以有 1 个负责人 + 多个协作者，每个接单人有自己的个人工作区：工作阶段、进度百分比、阻塞原因、清单、动态。没指定接单人就进公开池，本地端谁接谁成为负责人。

**EN** — One requirement = 1 lead + N collaborators, each with their own workspace: phase, progress %, blockers, checklist, activity feed. No assignee → public pool → whoever claims it on the desktop becomes the lead.

### ⏰ DDL 与日程 · Deadlines & calendar

投递需求**必须**有 DDL。DDL 同步到日程表，本地端按 24 小时 / 2 小时 / 到期 / 逾期提醒。再说「我以为下周五是下下周五」，系统听了都沉默。

**EN** — Shipping a requirement **requires** a deadline. It syncs to the calendar; the desktop reminds at 24h / 2h / due / overdue. Say "I thought next Friday meant the Friday after" one more time — even the system goes quiet.

### 📁 项目网盘 · Project drive

文件夹 / 列表 / 卡片视图，上传、下载、批量下载；PDF / Markdown / 文本 / 代码 / HTML / Office 预览；软删除、回收站、撤回；文件夹留言板——留言经 LLM 判断，普通话入板，**需求变更自动生成需求草稿**。

**EN** — Folder/list/card views; upload, download, bulk download; preview for PDF / Markdown / text / code / HTML / Office; soft-delete, trash, undo; a folder comment board where an LLM reads each comment — chit-chat stays a comment, a **requirement-change auto-spawns a draft requirement**.

### 🎙️ 会议纪要 · Meeting minutes

录音或文本导入 → 后台任务显示进度 → ASR 转写 → LLM 出纪要 → LLM 判断有没有新增/变更需求 → 人工确认后进澄清流程。会议 insight **不直接改原需求**，防止某位老哥会上激情发言直接污染生产状态。

**EN** — Import audio or text → background job shows progress → ASR transcribes → LLM writes minutes → LLM flags new/changed requirements → a human confirms before it enters the clarify flow. Meeting insights **never mutate the original requirement directly** — so one passionate rant in a meeting can't nuke production state.

### 🔎 知识库：不搞 embedding 也能搜 · Knowledge base: search without embeddings

不走向量库路线。后端把项目、需求、会议、留言、工作区、网盘解析文本、交付文档生成 Markdown 语料；搜索和 Agent 问答基于**受控 grep**，答案**必须带证据**。没搜到就说没搜到，绝不「我感觉应该是」。

**EN** — No vector DB. The backend turns projects, requirements, meetings, comments, workspaces, parsed drive text, and delivery docs into a Markdown corpus; search and the Q&A agent run on **controlled grep**, and answers **must cite evidence**. If it's not there, it says so — no "I feel like it's probably…".

### 📊 排期 / 通知 / 健康度 · Planning / notifications / health

- 排期：每人任务数、估算工时、逾期、阻塞、负载。
- 通知中心：未读/已读、跳转目标，本地端关键提醒弹系统通知（Web 端也实时弹 toast）。
- 项目健康度：逾期、阻塞、无人接单、返工率、变更数、吞吐、平均周期。

**EN** — Planning (per-person task count, estimated hours, overdue, blocked, load); a notification center (unread/read, deep links; desktop fires OS notifications, web pops live toasts); project health (overdue, blocked, unclaimed, rework rate, change count, throughput, avg cycle time).

---

## 快速开始 · Quick start

### Web 端 · Web

内网地址 / LAN address:

```text
http://192.168.5.53:8080/
```

提需求是项目级路径——先进项目，再点「新建需求」/ Requirements are project-scoped — open a project, then "New requirement":

```text
http://192.168.5.53:8080/p/<项目ID / projectId>/new
```

### Windows 一行装 · Windows one-liner

```powershell
powershell -ExecutionPolicy Bypass -c "iwr -UseBasicParsing http://192.168.5.53:8080/client/install.ps1 | iex"
```

装完会有：桌面快捷方式 `YQGL Workbench`、开机启动、本地配置、托盘常驻。
右下角找不到图标？先展开系统托盘隐藏区——多半不是它没上班，是 Windows 把它藏起来摸鱼了。

**EN** — You get a `YQGL Workbench` shortcut, autostart, local config, and a tray resident. Can't find the tray icon? Expand the hidden tray area first — it's not slacking, Windows just hid it.

### macOS 原生包 · macOS native build

Windows 机器**没法可靠地硬搓** macOS Tauri 包（Apple 那套工具链得在 Mac 上跑），所以走 GitHub Actions 在 macOS runner 上编 **Universal 包**（Apple Silicon + Intel 通吃）。**现在已经发布了**，直接去 Web 顶部下载条点 **macOS 客户端** 按钮就行。Windows 老哥点 Windows，Mac 老哥点 macOS，别再把 `.exe` 塞进 Mac 里念咒了。

```text
最新构建 / latest:  Release  client-macos-v0.3.1
工作流 / workflow:  .github/workflows/build-macos-client.yml  →  "Build macOS Client"
```

⚠️ 这是**未签名测试包**：首次打开会被 Gatekeeper 拦，内网真人测试**右键 → 打开**即可。想像正经软件那样双击丝滑，需要 Apple Developer 证书签名 + 公证（苹果税，懂的都懂）。

**EN** — A Windows box **can't reliably cross-build** a macOS Tauri bundle (Apple's toolchain needs a Mac), so CI builds a **Universal** DMG on a macOS runner (Apple Silicon + Intel). **It's published now** — just hit the **macOS 客户端** button in the web download banner. Windows folks click Windows, Mac folks click macOS; stop shoving `.exe` files into a Mac and chanting incantations. It's an **unsigned test build**: Gatekeeper blocks the first open, so **right-click → Open** for internal testing. Want a frictionless double-click? That needs an Apple Developer signature + notarization (the Apple tax — you know the deal).

### Linux / macOS 辅助脚本 · Linux/macOS helper script

```bash
curl -fsSL http://192.168.5.53:8080/client/install.sh | bash
```

主要用于辅助安装/启动；完整毛玻璃桌面体验以 Windows Tauri 客户端为主。
Mainly for install/launch help; the full frosted-glass desktop experience is the Windows Tauri client.

---

## 本地端首次设置 · First-run setup

客户端首次启动走 4 步 / First launch, 4 steps:

1. 填服务端 IP / Server IP, e.g. `192.168.5.53`
2. 填昵称 / Pick a nickname
3. 选本地工作目录 / Choose a local work folder
4. 完成设备注册 / Finish device registration

项目网盘同步当前只开放 **关 / 仅下载**（two-way 同步还在保护性内测）。毕竟文件同步这玩意儿，做对了叫效率工具，做歪了叫硬盘烟花。

**EN** — Drive sync currently offers **Off / Download-only** (two-way is in protective beta). File sync done right is a productivity tool; done wrong it's disk fireworks.

---

## 开发启动 · Dev

```powershell
# 后端 / backend
python -m uvicorn main:app --app-dir app --reload --host 127.0.0.1 --port 8080

# Web 派活台 / web
npm run dev --workspace=web

# 本地端前端壳 / desktop webview shell
npm run dev --workspace=client-tauri -- --host 127.0.0.1 --port 5174
```

---

## 验证命令 · Verify

```powershell
# 后端 smoke（无 LLM，临时 SQLite）/ backend smoke (no LLM, temp SQLite)
python scripts\smoke_workflow.py

# 全量构建（shared + web + client webview）/ full build
npm run build

# Web E2E（自带临时后端）/ web E2E (spins its own backend)
cd web; npx playwright test --project=chromium

# Rust 原生客户端 / native Rust client
cargo check --manifest-path client-tauri\src-tauri\Cargo.toml
npm run tauri:build --workspace=client-tauri
```

macOS Universal 包在 GitHub Actions 的 macOS runner 上构建 / built on a macOS runner in CI:

```bash
npm run tauri:build --workspace=client-tauri -- \
  --bundles dmg,app \
  --target universal-apple-darwin \
  --no-sign
```

---

## 部署 · Deploy

```powershell
npm run build
python scripts\deploy.py        # 后端 app/ + 重启 yqgl-web
python scripts\deploy_web.py    # web/dist 原子切换，零 404 窗口
curl http://192.168.5.53:8080/api/health
```

远端三个服务应为 active + enabled / The three remote services should be active + enabled:

- `yqgl-web`  ← 主服务，**必须单 worker**（SSE 总线/在线状态/去重都是进程内单例，第二个 worker 会脑裂）
- `yqgl-asr`  ← 语音转写（GPU），没起来时前端友好降级，不甩 `Unexpected end of JSON input` 给用户
- `yqgl-tts`  ← 语音合成（GPU），同上

**EN** — `yqgl-web` is the main service and **must run a single worker** (the SSE bus, presence map, and dedup state are in-process singletons — a 2nd worker split-brains them). `yqgl-asr` / `yqgl-tts` are GPU voice services; when down, the frontend degrades gracefully instead of throwing `Unexpected end of JSON input` in your face.

---

## 仓库结构 · Repo layout

```text
app/                  FastAPI 后端：模型、路由、权限、业务服务 / backend
web/                  浏览器派活/管理端 / browser dispatch+admin
client-tauri/         Rust/Tauri 毛玻璃本地工作台 / Rust desktop
client/              一行安装、启动脚本、旧托盘兼容 / installers + legacy tray
shared/               双端共享 UI / 类型 / API client / shared FE lib
scripts/              部署、smoke、E2E、安装验证 / deploy + test scripts
systemd/              yqgl-web / yqgl-asr / yqgl-tts 服务文件 / unit files
screenshots/readme/   README 专用干净截图 / clean README screenshots
```

---

## 技术栈 · Stack

后端 FastAPI + SQLAlchemy 2 + SQLite（WAL，单 worker）；LLM 走 DeepSeek 的 Anthropic 兼容接口（不用 tool_use，强约束 JSON 输出）；前端 React + Vite + 共享设计令牌；桌面端 Tauri v2 + Rust（透明窗 + 毛玻璃 + 托盘 + 深链）。

**EN** — Backend: FastAPI + SQLAlchemy 2 + SQLite (WAL, single worker). LLM: DeepSeek via its Anthropic-compatible API (no tool_use; strict-JSON output). Frontend: React + Vite + shared design tokens. Desktop: Tauri v2 + Rust (transparent window + acrylic + tray + deep links).

---

## License

MIT。拿去整活，但别拿报错截图当宣传图。
MIT. Go wild — just don't use error screenshots as marketing material.
