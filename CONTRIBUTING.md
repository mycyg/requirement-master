<div align="right"><a href="CONTRIBUTING.en.md">English</a> · <b>中文</b></div>

# 贡献指南

欢迎 PR 和 issue。但先把丑话说前头：这项目是给**小团队内网需求管理**用的，有些东西是**故意不做**的，提了被拒别上头。

## 故意不做的

- **密码 / RBAC 权限体系** —— 内网信任模型，昵称即身份。
- **公网部署** —— 上公网之前，先把 HTTPS 和鉴权补上再说。
- **企业微信 / 钉钉推送** —— 通知走站内 + 桌面系统通知，不接第三方。

## 很欢迎的 PR

- 修 bug，尤其是**并发、状态机、数据一致性**那种阴间 bug。
- 补端到端测试。
- 解决一个**明确的实际问题**——不是「我觉得加个 X 会更好看」。

---

## 代码长啥样

| 目录 | 是什么 |
|---|---|
| `app/` | FastAPI 后端（Python 3.12）：模型、路由、权限、业务服务 |
| `web/` | 浏览器派活/管理端（React + TypeScript 严格模式） |
| `client-tauri/` | **Rust + Tauri v2** 桌面客户端。`src-tauri/` 是 Rust 本体，`web-src/` 是它的 React webview |
| `shared/` | 双端共享的 UI / 类型 / API client |
| `scripts/` | 部署、smoke、E2E、安装验证 |

> ⚠️ **桌面客户端是 Rust/Tauri，不是 Python。** `client/` 目录里那些 `.py` 是早期托盘的兼容/安装脚本，别拿它当客户端主体来读。

---

## 动手前的几条规矩

- 后端 Python 3.12；Web 端 TypeScript **严格模式**；桌面端 Rust（Tauri v2）。
- 改了**状态流转 / 并发路径**，必须用原子 CAS（`UPDATE … WHERE status=<旧值>` + 查 rowcount），别写「先查再写」，会有竞态。
- 后台任务（detached asyncio task）**每条路径都要落到终态**，别留僵尸 job。
- 改了 LLM prompt，顺手在 [DEPLOY.md](DEPLOY.md) 里留一笔（模型、接口、影响）。
- **PR 里绝对不准出现真实 API key / 内网 IP / 密码。** `scripts/server_creds.py` 已经 gitignore，照着 `server_creds.example.py` 填本地的。

---

## 提 PR 之前跑一遍

```bash
# 1) 后端 smoke：不用 LLM，临时 SQLite 跑完整工作流
python scripts/smoke_workflow.py

# 2) 全量构建（shared + web + 客户端 webview，含 tsc 类型检查）
npm run build

# 3) Web 端到端（自带临时后端）
cd web && npx playwright test --project=chromium

# 4) 动了 Rust 客户端才需要
cargo check --manifest-path client-tauri/src-tauri/Cargo.toml
npm run tauri:build --workspace=client-tauri
```

改了某个里程碑模块，也有对应的 `scripts/smoke_m*.py` 可以单独跑。

---

## 报 issue 请带上

- 浏览器 / Python 版本
- 服务端日志末尾的报错：`/srv/yqgl/data/web.log`
- 客户端日志末尾的报错（桌面端/托盘问题）：`%APPDATA%/yqgl/`
- 复现步骤——越具体越好，「它就是不行」这种帮不上忙。

---

> English version 👉 [CONTRIBUTING.en.md](CONTRIBUTING.en.md)
> 文档写得不清楚？开 issue 喷我们，文档也是代码。
