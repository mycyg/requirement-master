# 需求管理大师 · 部署 & 运维手册

## 一、目录布局

```
D:\需求管理大师\               # 本地工作目录
├── app/                       # FastAPI 主应用源码
├── asr_service/               # Qwen3-ASR 独立服务源码
├── tts_service/               # CosyVoice 独立服务源码
├── client/                    # Windows 托盘客户端 (Python+pystray)
├── web/                       # Vite + React 前端
├── systemd/                   # 三个 systemd unit 文件
├── scripts/                   # 部署/运维脚本（paramiko 操作 192.168.5.53）
│   ├── server_creds.py        # SSH 密码 (gitignored)
│   ├── provision.py           # 一次性引导服务器
│   ├── provision_asr.py       # 装/重装 ASR 服务
│   ├── provision_tts.py       # 装/重装 TTS 服务
│   ├── deploy.py              # 推 app/ 代码 + 重启 web
│   ├── deploy_web.py          # 推 web/dist 静态资源 + 重启 web
│   ├── restart_all.py         # 重启三服务并 health 检查
│   ├── verify_systemd.py      # 查三个 unit 的 enable/active 状态
│   └── smoke_m*.py            # 各里程碑的 e2e 烟雾测试
└── DEPLOY.md
```

服务器上：
```
/srv/yqgl/
├── app/        ← scripts/deploy.py 推上来的代码
├── venv/       ← Python 3.12 venv (主 app 用)
├── asr_service/        ← asr_service 代码
├── tts_service/        ← tts_service 代码
├── web/dist/   ← scripts/deploy_web.py 推的前端构建产物
└── data/
    ├── yqgl.db          # SQLite
    ├── uploads/         # 提需求方上传的附件
    ├── voice/           # 临时语音转写文件
    ├── outputs/         # markitdown 解析全文落盘
    ├── auto/            # AI 自动处理的工作目录
    └── deliveries/      # 交付包 zip
```

ASR / TTS 服务用的是 **uv 装的 Python 3.13** (`~/.local/share/uv/python/cpython-3.13-.../bin/python3.13`)，通过 `PYTHONUSERBASE=/home/mycyg/.local` 复用 user-site 的 torch / qwen_asr / cosyvoice 依赖（详见 memory）。

---

## 二、首次部署（已完成，备查）

```bash
# 1. 引导服务器：装 uv + Python 3.12 + 建 /srv/yqgl + 装主 app 依赖 + 装 systemd web unit
python scripts/provision.py

# 2. 准备 Python 3.13 + 验证 user-site 包齐
python scripts/setup_py313.py

# 3. ASR 服务（用 user-site torch + qwen_asr，无下载）
python scripts/provision_asr.py

# 4. TTS 服务（CosyVoice，自动 pip 装缺的小包）
python scripts/install_cosy_deps.py    # 装 inflect/rich 等到 user-site
python scripts/provision_tts.py

# 5. 主 app 代码 + 前端构建
python scripts/deploy.py        # 推 app/
cd web && npm install && npm run build && cd ..
python scripts/deploy_web.py    # 推 web/dist + 重启 web

# 6. 校验
python scripts/verify_systemd.py
```

启用 systemd 自启已在每个 provision 脚本里调过 `systemctl enable`，重启服务器后会自动跑起来。

---

## 三、常规迭代

| 改动类型 | 命令 |
|---|---|
| 改了 `app/` 后端 | `python scripts/deploy.py` |
| 改了 `web/` 前端 | `cd web && npm run build && cd .. && python scripts/deploy_web.py` |
| 改了 `asr_service/` | `python scripts/provision_asr.py` |
| 改了 `tts_service/` | `python scripts/provision_tts.py` |
| 改了 `.env` | `python scripts/deploy.py --env` |
| 改了 systemd unit | 对应 provision 脚本里有 daemon-reload + restart |

每次部署完，脚本末尾会 curl `/api/health` 自检。

---

## 四、客户端（你自己）

### 开发模式
```bash
cd D:\需求管理大师\client
pip install -r requirements.txt
python yqgl_tray.py
```

首次启动弹窗：
- 服务端 IP：默认 `192.168.5.53`
- 端口：默认 `8080`
- 请求地址：由 IP + 端口自动生成；旧 `192.168.0.x` 会自动迁到同尾号 `192.168.5.x`
- 昵称：你自己
- 同步根目录：默认 `D:\工作需求`

确认后开始托盘运行：右下角 ⚙ 形图标 = `需`字。右键菜单：
- 打开主界面 → 浏览器开 web 前端
- 打开同步目录
- 立即同步所有就绪需求
- 完成任务并上传…（弹列表选需求，然后打包+分片上传）
- 暂停/恢复同步
- 设置…
- 退出

### 打包成 .exe
```bash
cd D:\需求管理大师\client
build_exe.bat
```
产物 `client\dist\yqgl-tray.exe` 约 30MB，双击就跑，不需用户装 Python。

### 开机自启
把 `yqgl-tray.exe`（或 `launch.bat`）的快捷方式拖到：
`%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\`

---

## 五、用户日常流程

### 提需求方
1. 浏览器开 `http://192.168.5.53:8080`（或你的 `192.168.5.x` 服务地址）
2. 填昵称 → cookie 持久化
3. 新建项目（slug 用 ASCII）→ +提一个需求
4. 写描述 + 上传附件（语音输入可用）
5. 跟 AI 对话澄清，每条 AI 消息可 🔊 听
6. 总结出来后：
   - **如果 AI 判定 ai_doable=true** → 默认勾选"让 AI 试一下"→ 点投递 → 后台 AI 跑，详情页可看实时 thinking + tool_call
   - **如果勾掉** → 投递给人工，托盘客户端收到通知
7. 收到 delivered 通知 → 详情页"交付物" tab 看 LLM 写的交付文档 + 下载 zip / 单文件
8. 接受 / 申请返工

### 接单方（你）
1. 托盘弹"有新需求待接单"通知
2. 同步目录里出现 `D:\工作需求\<project>\<code>\` 含 `requirement.md` / `metadata.json` / `attachments/`
3. 你在该目录下随便写代码 / 文档
4. 写完点托盘"完成任务并上传…"→ 选这条需求 → 自动 zip + 分片上传
5. 服务端 LLM 写交付文档，状态变 delivered
6. 提需求方接受或申请返工

---

## 六、维护命令速查

```bash
# SSH 登录
ssh your-ssh-user@your.server.ip

# 三服务状态
systemctl status yqgl-web yqgl-asr yqgl-tts

# 看日志
tail -f /srv/yqgl/data/web.log
tail -f /srv/yqgl/data/asr.log
tail -f /srv/yqgl/data/tts.log

# 看数据库
sqlite3 /srv/yqgl/data/yqgl.db
# .tables / .schema requirements / select code, status from requirements;

# 重启所有
sudo systemctl restart yqgl-asr yqgl-tts yqgl-web

# 清缓存（小心，会删全部 AI 自动处理工作目录与未交付包）
# rm -rf /srv/yqgl/data/auto/*  /srv/yqgl/data/deliveries/_partial/*

# 客户端 log
type %APPDATA%\yqgl\client.log
```

---

## 七、配置 / 凭据

- 服务端 `.env`：`/srv/yqgl/app/.env`（含 LLM API key、cookie secret 等）
- 客户端配置：`%APPDATA%\yqgl\config.json`（含 `server_ip / server_port / server_url` 和签名 cookie；删了就重新走首次配置）
- LLM 接口：DeepSeek Anthropic 兼容 `https://api.deepseek.com/anthropic`，model `deepseek-v4-pro` (主) / `deepseek-v4-flash` (快)
- ASR：Qwen3-ASR-1.7B，常驻显存 ~5GB
- TTS：Fun-CosyVoice3-0.5B，常驻显存 ~3GB（3 音色 male/yujie/xiaoguang）
- 总显存预算：≤24GB（RTX 3090），主 LLM 走外网 API 不占本地

---

## 八、风险 & 已知限制

- ASR/TTS 第一次启动时模型加载需要 2~10s，期间 `/health` 返回 `ready:false`，前端调用会拿到 503/502。日常重启间隔够长基本不踩。
- 客户端 cookie 不持久（与浏览器 cookie 独立），删 `config.json` 后要重新填昵称。
- 安全：cookie 只签名不加密；适合内网。要上公网前必须加密 + HTTPS。
- LLM 失败/速率限制：聊天和 auto-process 都有 retry，但极端情况下用户会看到错误信息；重试一下即可。
