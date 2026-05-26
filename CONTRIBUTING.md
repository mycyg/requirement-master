# Contributing

欢迎 PR / issue。这个项目是为了"小团队内网需求管理"而生的，所以请先看 [README](README.md) 的设计意图：

> 不做密码 / RBAC、不做多接单人路由、不做企业微信推送（v0.1 范围）。

如果你的功能在 [roadmap](README.md#路线图) 上、或解决一个明确的实际问题、或是漏的端到端测试，PR 都很欢迎。

## 开发约定

- 后端 Python 3.12，前端 TypeScript 严格模式，Rust 不依赖（客户端是纯 Python）
- 每个新后端 router 配一个 `scripts/smoke_*.py` 冒烟脚本
- LLM prompt 改了请同时更新 [DEPLOY.md](DEPLOY.md) 风险表
- 不允许 PR 里出现真实 API key / IP / 密码

## 提 PR 之前

```bash
# 后端语法
cd app && python -c "import py_compile, pathlib; [py_compile.compile(str(p), doraise=True) for p in pathlib.Path('.').rglob('*.py')]"

# 前端类型
cd web && npx tsc -b --noEmit

# 相关冒烟（按你改了什么挑跑）
YQGL_BASE=http://your.server YQGL_DEEPSEEK_API_KEY=... python scripts/smoke_m*.py
```

## 报 issue

请带：
- 浏览器/Python 版本
- `/srv/yqgl/data/web.log` 末尾错误
- 客户端 `%APPDATA%/yqgl/client.log` 末尾错误（如果是 tray 的问题）
- 复现步骤
