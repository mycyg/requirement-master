# 需求管理大师

> 你老板的需求永远说不清？那为什么不让他说清呢？
>
> 产品经理一句“你看着改”，你当场大脑蓝屏？那就把他推进 AI 澄清流程。
>
> 接单人问“附件呢、DDL 呢、谁验收呢”，派活人说“我以为你懂”？很好，现在系统会替你问到他懂。

**需求管理大师** 是一个内网工作中台：Web 端负责派活、澄清、验收和看全局；Rust/Tauri 本地端负责接活、同步文件、系统通知、工作区进度和交付。

一句话：把“群里口嗨”变成“可追踪、可交付、可验收”的项目流水线。

![Rust 毛玻璃客户端](screenshots/readme/rust-client-glass.png)

截图说明：README 只使用 `screenshots/readme/` 下的干净裁剪图，不放报错图，不放桌面隐私，不拿聊天窗口祭天。

## 这玩意儿解决啥

- 老板说“做个差不多的”：AI 先追问，追到能落地。
- 产品说“先这样后那样”：需求有状态、有 DDL、有负责人，不再靠玄学记忆。
- 接单人说“我不知道谁让我干的”：每个需求都有负责人、协作者、工作区和交付记录。
- 文件在群里飞来飞去：项目网盘统一放，能预览，能回收，能进知识库。
- 会议开完大家都很感动：录音/文本生成纪要，自动识别新增需求或需求变更。
- 领导问“项目健康吗”：健康度、排期、通知、知识库一起给他看，别再手搓周报。

## 双端分工

| 端 | 干啥 | 能不能接活 |
|---|---|---|
| Web 派活台 | 提需求、AI 澄清、指定接单人、看项目、排期、健康、知识库、验收、返工 | 不能 |
| Rust 毛玻璃本地端 | 派活 + 接活 + 本地文件 + 托盘常驻 + 系统通知 + 网盘同步 + 交付 | 能 |

Web 端是“指挥室”，本地端是“干活桌”。

浏览器里不让你偷偷接单交付，本地端会带 client device token，服务端会硬校验。想绕 UI？后端说：别闹。

## 截图先看

### 派活台：谁发的活，谁验收，谁背锅，一眼看见

![派活台](screenshots/readme/dispatch-space.png)

### 新建需求：先把话说明白，再让别人开干

![新建需求](screenshots/readme/new-requirement.png)

### 项目网盘：文件别再散落在聊天记录深处

![项目网盘](screenshots/readme/project-drive.png)

### 项目健康度：需求有没有炸，别等老板拍桌子才知道

![项目健康度](screenshots/readme/project-health.png)

## 核心功能

### AI 澄清需求

提示词全英文写，但用户可见输出会使用用户的语言。

用户扔一段“想做个管理系统”，AI 会继续问：谁用、何时要、验收标准是什么、附件在哪、谁负责、DDL 是啥。

问清楚之后生成摘要，提交人确认后才能投递。

### 多接单人

一个需求可以有：

- 1 个负责人
- 多个协作者
- 每个接单人自己的个人工作区
- 工作阶段、进度百分比、阻塞原因、清单和动态

未指定接单人时进入公开池，本地端可以接；接到的人自动成为负责人。

### DDL 与日程

投递需求必须有 DDL。

需求 DDL 会同步到日程表，本地端会做提醒：24 小时、2 小时、到期、逾期。

再也别说“我以为下周五是下下周五”，系统听了都沉默。

### 项目网盘

支持：

- 文件夹、列表、卡片视图
- 上传、下载、批量下载
- PDF / Markdown / 文本 / 代码 / HTML / Office 文档预览
- 软删除、回收站、撤回
- 文件夹留言板
- 留言经 LLM 判断：普通留言入板，需求变更生成需求草稿

### 会议纪要

会议录音或文本导入后：

1. 后台任务显示进度。
2. ASR 转写。
3. LLM 生成会议纪要。
4. LLM 判断是否有新增需求或需求变更。
5. 人工确认后进入需求草稿和澄清流程。

会议 insight 不会直接修改原需求，防止会议上某位老哥激情发言直接污染生产状态。

### 知识库：不用 embedding，也能搜

本项目不走向量库路线。

后端把项目、需求、会议、留言、工作区、网盘解析文本、交付文档生成 Markdown 语料。

搜索和 Agent 问答基于受控 grep，答案必须带证据。没搜到就说没搜到，不搞“我感觉应该是”。

### 排期、通知、健康度

- 排期看每个人任务数、估算工时、逾期、阻塞、负载。
- 通知中心有未读、已读、跳转目标。
- 本地端关键提醒弹系统通知。
- 项目健康度看逾期、阻塞、无人接单、返工率、变更数、吞吐和平均周期。

## 快速开始

### Web 端

内网地址：

```text
http://192.168.5.53:8080/
```

提需求页面是项目级路径：先进项目，再点“新建需求”。URL 大概长这样：

```text
http://192.168.5.53:8080/p/<项目ID>/new
```

### Windows 本地端一行安装

```powershell
powershell -ExecutionPolicy Bypass -c "iwr -UseBasicParsing http://192.168.5.53:8080/client/install.ps1 | iex"
```

安装后会生成：

- 桌面快捷方式 `YQGL Workbench`
- 开机启动项
- 本地配置文件
- 托盘常驻入口

右下角看不到图标？先展开系统托盘隐藏区。很多时候不是它没活，是 Windows 把它藏起来上班摸鱼。

### Linux / macOS 辅助脚本

```bash
curl -fsSL http://192.168.5.53:8080/client/install.sh | bash
```

Linux/macOS 脚本主要用于辅助安装和启动；完整毛玻璃桌面体验以 Windows Tauri 客户端为主。

### macOS 原生包

Windows 机器不能可靠地“硬搓” macOS Tauri 安装包，Apple 那套工具链得在 Mac 上干活。仓库里已经放了 GitHub Actions：

```text
.github/workflows/build-macos-client.yml
```

在 GitHub Actions 手动运行 **Build macOS Client**，会用 macOS runner 构建 Universal 包，理论上 Apple Silicon 和 Intel Mac 都能用。产物名：

```text
yqgl-client-macos-universal-unsigned
```

注意：这是未签名测试包。第一次打开可能被 macOS Gatekeeper 拦一下，内网真人测试可以右键打开；要像正经软件那样丝滑双击，需要 Apple Developer 证书签名 + notarization。苹果税，懂的都懂。

## 本地端设置

客户端首次启动会走 4 步：

1. 填服务端 IP，例如 `192.168.5.53`。
2. 填昵称。
3. 选择本地工作目录。
4. 完成设备注册。

当前项目网盘同步只开放：

- 关
- 仅下载

双向同步还在保护性内测。毕竟文件同步这东西，做得好叫效率工具，做歪了叫硬盘烟花。

## 开发启动

```powershell
# 后端
python -m uvicorn main:app --app-dir app --reload --host 127.0.0.1 --port 8080

# Web 派活台
npm run dev --workspace=web

# 本地端前端壳
npm run dev --workspace=client-tauri -- --host 127.0.0.1 --port 5174
```

## 验证命令

后端与 Web：

```powershell
python -m compileall app client scripts asr_service tts_service
python scripts\smoke_workflow.py
npm run build
```

Web E2E：

```powershell
$env:YQGL_E2E_API_PORT='19180'
$env:YQGL_E2E_WEB_PORT='16273'
npm run e2e:web
```

客户端 Web 壳：

```powershell
npm run build --workspace=client-tauri
npx tsc --noEmit -p client-tauri\web-src\tsconfig.json
```

Rust/Tauri 原生客户端：

```powershell
$env:Path = "$env:USERPROFILE\.cargo\bin;$env:Path"
cargo check --manifest-path client-tauri\src-tauri\Cargo.toml
npm run tauri:build --workspace=client-tauri
```

macOS Universal 包在 GitHub Actions 的 macOS runner 上构建：

```bash
npm run tauri:build --workspace=client-tauri -- \
  --bundles dmg,app \
  --target universal-apple-darwin \
  --no-sign
```

安装脚本 smoke：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\smoke_client_install.ps1
```

客户端截图 E2E：

```powershell
npm run dev --workspace=client-tauri -- --host 127.0.0.1 --port 5174
$env:YQGL_CLIENT_E2E='1'
$env:YQGL_USE_REMOTE='1'
cd web
npx playwright test tests/e2e/client-routes.spec.ts tests/e2e/client-spaces.spec.ts --reporter=list
```

最近一次本机验证记录：

- `python -m compileall app client scripts asr_service tts_service` 通过。
- `python scripts\smoke_workflow.py` 通过。
- `npm run build` 通过。
- `npm run e2e:web` 通过：23 passed / 2 skipped。
- 客户端专项 E2E 通过：2 passed。
- `cargo check --manifest-path client-tauri\src-tauri\Cargo.toml` 通过。
- `npm run tauri:build --workspace=client-tauri` 通过，产出 NSIS 安装包。
- 真实 Tauri exe 已启动并截图。

## 部署

常用流程：

```powershell
npm run build
python scripts\deploy.py
python scripts\deploy_web.py
python scripts\restart_all.py
python scripts\verify_systemd.py
curl http://192.168.5.53:8080/api/health
```

远端服务应该是：

- `yqgl-web` active + enabled
- `yqgl-asr` active + enabled
- `yqgl-tts` active + enabled

ASR/TTS 如果没起来，前端会友好显示服务不可用，不会把浏览器 `Unexpected end of JSON input` 这种东西甩用户脸上。

## 仓库结构

```text
app/                  FastAPI 后端、模型、路由、权限和业务服务
web/                  浏览器派活/管理端
client-tauri/         Rust/Tauri 毛玻璃本地工作台
client/               一行安装、启动脚本、旧托盘兼容脚本
shared/               双端共享 UI、类型、API client
scripts/              部署、smoke、E2E、安装验证
systemd/              yqgl-web / yqgl-asr / yqgl-tts 服务文件
screenshots/readme/   README 专用干净截图
```

## License

MIT。拿去整，别拿报错截图当宣传图。
