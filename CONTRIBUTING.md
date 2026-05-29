# 贡献指南 · Contributing

欢迎 PR 和 issue。先说清楚这项目是给**小团队内网需求管理**用的，所以有些东西是**故意不做**的，别提了被拒别伤心：

**EN** — PRs and issues welcome. Heads up: this is built for **small-team, LAN-only requirement management**, so some things are **left out on purpose**. Don't take a rejection personally.

**目前不做 / Out of scope (for now):**

- 密码 / RBAC 权限体系 —— 内网信任模型，昵称即身份 / No passwords or RBAC — LAN trust model, nickname = identity
- 公网部署 —— 上公网前必须先加 HTTPS + 鉴权 / No public-internet deploy — add HTTPS + auth first
- 企业微信 / 钉钉推送 —— 通知走站内 + 桌面系统通知 / No WeCom/DingTalk push — notifications are in-app + OS-native

**欢迎的 PR / Good PRs:**

- 修 bug（尤其是并发、状态机、数据一致性那种阴间 bug）/ Bug fixes (especially concurrency / state-machine / data-consistency gremlins)
- 补端到端测试 / Missing end-to-end tests
- 解决一个**明确的**实际问题，不是「我觉得加个 X 会更好」/ A **concrete** real problem — not "I feel like adding X would be nice"

---

## 这套代码长啥样 · How the code is laid out

| 目录 / Dir | 是什么 / What |
|---|---|
| `app/` | FastAPI 后端（Python 3.12）：模型、路由、权限、业务服务 / backend |
| `web/` | 浏览器派活/管理端（React + TypeScript 严格模式）/ browser app |
| `client-tauri/` | **Rust + Tauri v2** 桌面客户端（`src-tauri/` 是 Rust，`web-src/` 是它的 React webview）/ desktop client |
| `shared/` | 双端共享的 UI / 类型 / API client / shared frontend lib |
| `scripts/` | 部署、smoke、E2E、安装验证 / deploy + test scripts |

> ⚠️ 划重点：桌面客户端是 **Rust/Tauri**，不是 Python。`client/` 目录里那些 `.py` 是早期托盘的兼容/安装脚本，别拿它当客户端主体。
> ⚠️ Important: the desktop client is **Rust/Tauri**, not Python. The `.py` files under `client/` are legacy-tray compat + install scripts — not the actual client.

---

## 改代码前的约定 · Conventions

- 后端 Python 3.12；Web 端 TypeScript **严格模式**；桌面端 Rust（Tauri v2）。
  Backend Python 3.12; web is TypeScript **strict**; desktop is Rust (Tauri v2).
- 改了状态流转 / 并发路径，**必须**用 atomic CAS（`UPDATE … WHERE status=<old>` + 查 rowcount），别用「先查再写」。
  Touching status transitions / concurrency? **Use atomic CAS** (`UPDATE … WHERE status=<old>` + check rowcount), never read-then-write.
- 后台任务（detached asyncio task）**每条路径都要落到终态**，别留僵尸 job。
  Background (detached asyncio) tasks **must reach a terminal state** on every path — no zombie jobs.
- 改了 LLM prompt，顺手在 [DEPLOY.md](DEPLOY.md) 里留一笔（模型、接口、影响）。
  Changed an LLM prompt? Note it in [DEPLOY.md](DEPLOY.md) (model, endpoint, impact).
- **PR 里绝对不准出现真实 API key / 内网 IP / 密码。** `scripts/server_creds.py` 已 gitignore，照抄 `server_creds.example.py`。
  **Never commit real API keys / LAN IPs / passwords.** `scripts/server_creds.py` is gitignored — copy `server_creds.example.py`.

---

## 提 PR 之前跑一遍 · Run before opening a PR

```bash
# 1) 后端 smoke：无需 LLM，临时 SQLite 跑完整工作流
#    backend smoke: no LLM needed, full workflow on a temp SQLite
python scripts/smoke_workflow.py

# 2) 全量构建（shared + web + client webview，含 tsc 类型检查）
#    full build (shared + web + client webview, incl. tsc typecheck)
npm run build

# 3) Web 端到端（自带临时后端）
#    web E2E (spins its own backend)
cd web && npx playwright test --project=chromium

# 4) 动了 Rust 客户端才需要 / only if you touched the Rust client
cargo check --manifest-path client-tauri/src-tauri/Cargo.toml
npm run tauri:build --workspace=client-tauri
```

改了某个里程碑模块，也可以跑对应的 `scripts/smoke_m*.py`。
Touched a specific milestone module? The matching `scripts/smoke_m*.py` exists too.

---

## 报 issue · Filing an issue

请带上 / Please include:

- 浏览器 / Python 版本 / browser & Python version
- 服务端日志末尾错误：`/srv/yqgl/data/web.log`
- 客户端日志末尾错误（桌面端/托盘问题）：`%APPDATA%/yqgl/`
- 复现步骤（越具体越好，「它就是不行」帮不上忙）/ repro steps (the more specific the better — "it just doesn't work" doesn't help)

---

写得清不清楚？不清楚就开 issue 喷我们——文档也是代码。
Clear enough? If not, open an issue and roast us — docs are code too.
