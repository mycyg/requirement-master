# 需求管理大师 · yqgl

> 一个 **AI 原生** 的内网需求中台：同事写需求 → LLM 反问澄清 → 推到接单人本地 → 接单人交付 → LLM 写交付文档 → 闭环。简单需求 AI 还能直接自己干完。

[English](#english-summary) · [架构](#架构) · [快速开始](#快速开始) · [路线图](#路线图)

![看板](screenshots/02_dashboard.png)

---

## 它解决什么

团队里"提需求 → 接需求 → 做需求 → 交付"这条链：
- 提需求方不会写完整需求文档 → **LLM Agent 反问澄清**，点选 + Other 补充
- 接单方收到的描述总不够清楚 → **结构化 markdown + 原始文件 + 完整对话历史** 一起推到本地
- 简单需求也得人工排队 → **LLM 自评复杂度 + 自动尝试**，AI 翻车自动转人工
- 交付了不知道怎么用 → **LLM 读交付物自动写说明文档**（包含原需求映射表）

## 功能

- 📝 **澄清式 Agent**：DeepSeek 流式 thinking + 三种动作（ask_choice / ask_open / summarize）
- 🎙️ **语音输入**：浏览器按住录音 → Qwen3-ASR 转写到输入框
- 🔊 **语音输出**：CosyVoice 3 个音色，可设置 AI 消息自动朗读
- 📦 **附件理解**：上传 PDF/Word/Excel/PPT/图片，markitdown 解析后喂给 LLM
- 🤖 **AI 自动处理**：summarize 判定 `ai_doable=true` → Anthropic SDK tool_use 自建 agent（5 个工具：list/read/write/run_bash/submit + 沙箱）→ 6 轮搞定 FizzBuzz / 单词频率统计这类小活
- 🗂️ **项目管理**：状态机 9 态，Kanban 风格 dashboard，评论 / 活动时间轴
- 🔔 **本地托盘**：Python pystray，SSE 长连接 + Windows 通知，文件同步到本地目录
- 🔄 **完整交付闭环**：本地做完 → 一键打包上传 → LLM 写交付文档 → 提需求方接受 / 申请返工

## 截图

| 主页项目列表 | 接单看板 |
|---|---|
| ![home](screenshots/01_home.png) | ![dashboard](screenshots/02_dashboard.png) |

| AI 澄清对话 | 最终汇总（含 AI 复杂度判断） |
|---|---|
| ![clarify](screenshots/03_clarify.png) | ![summary](screenshots/04_summary.png) |

## 架构

```
┌──────────── 服务器 (Ubuntu + GPU) ────────────┐
│  yqgl-web :8080     FastAPI + SPA + SSE        │
│      ├─ LLM clarify (DeepSeek streaming)       │
│      ├─ Auto-process agent (tool_use)          │
│      └─ LLM 写交付文档                          │
│                                                 │
│  yqgl-asr :8001     Qwen3-ASR-1.7B 常驻显存    │
│  yqgl-tts :8002     CosyVoice3 0.5B 常驻显存   │
│                                                 │
│  SQLite + 文件存储 + 三个 systemd unit         │
└────────────────────┬───────────────────────────┘
                     │ HTTP/SSE 局域网
       ┌─────────────┴─────────────┐
       ▼                           ▼
┌──────────────┐         ┌─────────────────────┐
│ 浏览器 SPA    │         │ 托盘客户端 (Windows) │
│ React + Vite │         │ Python pystray       │
│ Tailwind     │         │ + httpx SSE          │
└──────────────┘         │ + pywebview 看板     │
   提需求方                └─────────────────────┘
                            接单方
```

## 技术栈

| 层 | 用什么 |
|---|---|
| 后端 | Python 3.12 · FastAPI · SQLAlchemy 2.0 · SQLite · httpx · anthropic SDK |
| 前端 | Vite · React 18 · TypeScript · Tailwind · react-router |
| ASR | Qwen3-ASR-1.7B · torch+CUDA · qwen_asr Python API |
| TTS | CosyVoice 3 0.5B · 3 zero-shot 音色 |
| LLM | DeepSeek (Anthropic 兼容端点)，支持 thinking blocks + tool_use |
| 客户端 | Python · pystray · pywebview · plyer · Pillow |
| 部署 | systemd · uv (Python 版本) · pip 清华源 |
| 文件解析 | markitdown (微软出品，覆盖 PDF/Word/Excel/PPT/HTML/...) |

## 快速开始

### 服务器（Linux + NVIDIA GPU）

```bash
# 1. 准备
git clone https://github.com/<you>/yqgl.git
cd yqgl
cp scripts/server_creds.example.py scripts/server_creds.py   # 填 SSH 凭据
cp app/.env.example app/.env                                  # 填 LLM key 等

# 2. 装环境（在能 SSH 到目标机器的本地跑）
python scripts/provision.py        # 主 web 服务（FastAPI + SQLite）
python scripts/setup_py313.py      # Python 3.13 给 ASR/TTS 用
python scripts/install_cosy_deps.py
python scripts/provision_asr.py    # 启动 Qwen3-ASR
python scripts/provision_tts.py    # 启动 CosyVoice

# 3. 推前端 + 启动主服务
cd web && npm install && npm run build && cd ..
python scripts/deploy_web.py

# 4. 校验
python scripts/verify_systemd.py
curl http://your.server.ip:8080/api/health
```

详细步骤、运维命令、风险见 [DEPLOY.md](DEPLOY.md)。

### 提需求方（浏览器）

打开 `http://your.server.ip:8080`，填昵称即可用。

### 接单方（Windows 托盘）

```bash
cd client
pip install -r requirements.txt
python yqgl_tray.py    # 首次启动有配置向导
# 或打成 .exe：
# build_exe.bat
```

托盘菜单第一项 "打开接单看板"（默认双击）= 副屏 dashboard。

### 端到端冒烟测试

```bash
export YQGL_BASE=http://your.server.ip:8080
export DEEPSEEK_API_KEY=sk-...
python scripts/smoke_m3.py     # 项目+需求+上传+解析
python scripts/smoke_m4.py     # LLM 澄清
python scripts/smoke_m6.py     # submit + push
python scripts/smoke_m8.py     # 人工 delivery + LLM 文档
python scripts/smoke_m12.py    # AI 自动处理
```

## 路线图

- [x] **v0.1** —— M0~M13 全部完成，端到端跑通
- [ ] 拖拽 Kanban (dnd-kit)
- [ ] 甘特图 (frappe-gantt)
- [ ] 多接单人路由 / 任务分发
- [ ] 用户密码 + RBAC（当前只内网无密码）
- [ ] 企业微信 / 钉钉 / 飞书机器人推送
- [ ] 跨平台托盘（macOS / Linux）
- [ ] 需求模板库

## 致谢

- [Qwen3-ASR](https://huggingface.co/Qwen/Qwen3-ASR-1.7B) · 阿里通义实验室
- [CosyVoice](https://github.com/FunAudioLLM/CosyVoice) · 通义语音
- [DeepSeek](https://www.deepseek.com/) · 提供 Anthropic 兼容 LLM 端点（v4 pro / v4 flash）
- [markitdown](https://github.com/microsoft/markitdown) · 微软
- [Anthropic SDK](https://github.com/anthropics/anthropic-sdk-python)

## License

[MIT](LICENSE) — 随便用，但作者不对生产环境后果负责。

---

## English Summary

**yqgl** is an AI-native **intranet requirement management hub** built for small teams:
- Submitters describe what they need; an LLM agent asks clarifying questions (multiple choice + free text + voice).
- Structured markdown spec + original files + full chat history sync to the assignee's local folder.
- An LLM judges complexity. If "low / AI-doable", an in-process Anthropic-tool_use agent runs sandboxed (write_file / run_bash / submit) and delivers a zip — typically in a few turns. On failure, gracefully falls back to human.
- Voice in (Qwen3-ASR) and voice out (CosyVoice, 3 presets) wired throughout.
- After human delivery: zip → chunked upload → LLM auto-writes a customer-facing delivery doc with original-requirement mapping table.

Single-receiver design for now (multi-assignee routing on roadmap). All metadata in SQLite, files in plain dirs, deploys to a single Ubuntu box with GPU via systemd. Tray client is pure Python (pystray + pywebview) — no Rust/Electron needed.

Built end-to-end as a one-shot demo of "what's possible when you let the AI hold both ends of the requirement lifecycle".
