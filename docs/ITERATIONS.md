# 后续可迭代点（Aurora Glass 重构 follow-up）

本文档收录在重构验证过程中发现、但本轮没修的可改进项。按优先级从高到低排列。

## 一、必修（影响功能）

### 1. Tauri release exe 默认走 devUrl，缺 dev server 时白屏 — 已记录
**症状**：直接 `cargo build --release` 出的 exe 启动后 webview 加载 `http://localhost:5174`，因为 dev server 没起，显示 "ERR_CONNECTION_REFUSED"。
**正确做法**：必须用 `cargo tauri build`（或 `npx tauri build --no-bundle`），CLI 会注入 `TAURI_ENV=production` 让 codegen 把 frontendDist 嵌入。
**长期方案**：在 README/BUILD.md 强调；CI 用 `tauri build` 而非 `cargo build`。

### 2. Tauri MSI/NSIS bundle 失败（环境问题）
- WiX MSI：candle 编译 wxs 出错（产品名含中文导致兼容性问题）
- NSIS：extract 阶段触发 "无法跨盘 rename" — Tauri 已知 bug ([tauri-apps/tauri#13125](https://github.com/tauri-apps/tauri/issues/13125))
**workaround**：在 Linux runner（GitHub Actions）跑 `tauri build`；或本地用 Inno Setup 重新打包 `target/release/yqgl-client.exe`。

### 3. WiX 中文产品名兼容性
`tauri.conf.json` `productName: "需求管理大师"` 与 WiX 3.14 candle 不兼容。可以：
- 改用 ASCII 产品名（如 `yqgl-client`）+ NSIS displayName 显示中文
- 或者 fork tauri-bundler 的 wxs 模板换 UTF-8 编码

---

## 二、可改进（不影响功能但影响体验）

### 4. 客户端 `is_complete()` / `notify::toast` 标了 `#[allow(dead_code)]`
本质是设计预留 API。**真正用上**它们能让 UX 更好：
- `is_complete()` 可在 Tauri setup 直接判断决定开自动显示 onboarding 还是 hub
- `notify::toast` 在 SSE 连接断开/恢复时 ping 一下用户

### 5. 客户端裸 fetch 已统一走 `clientFetch`（本轮已修），但还有更优解
`Inbox / Knowledge / Calendar / ProjectPulse / MyWorkload` 5 个页面用 `clientFetch`（浏览器 fetch + 注入 worker token）。更稳的做法：每个 API 都加一个 Tauri command，让 Rust 端 reqwest 走（已有 cookie store + 自动重试空间）。当前 `clientFetch` 在 cookie 过期或网络变化时不会主动重置 token cache。

### 6. NewRequirement 5 步 Stepper 缺少"返回上一步会丢数据"提示
第 1 步描述写一半切到第 2 步选人，再回第 1 步，描述会保留（state 在）。但用户**关闭浏览器**会丢草稿。可以：
- 第 1 步即创建草稿（autosave to localStorage 或调 API）
- 顶部加 "草稿已保存" 提示

### 7. Clarify 气泡虽美但没有 Markdown 渲染
AI 返回的 summary_md 是 Markdown，但目前 Bubble 直接 `whitespace-pre-wrap` 显示 raw。加 `react-markdown` 渲染更专业。

### 8. 状态切换没有 optimistic UI
点 "接这单" / "开始做" 按钮后 → 调 API → refresh → UI 更新。中间有 200-500ms 闪烁。可以 optimistic update state 立刻反映。

### 9. Dashboard 5 桶在窄屏（< 1920px）挤
2xl 才能 5 列展示，xl 是 3 列。在 13" 笔记本（1440×900）下面会折断成两行。可以引入 horizontal scroll + 滚轮支持。

### 10. ⌘K CommandMenu 只有 8 条静态命令
应该接入：
- 最近访问的项目（动态 top 5）
- 最近 N 条待接单需求（点击直跳详情）
- 我正在做的需求

### 11. 客户端 Hub 的 `list_public_pool` 等命令在客户端组件里没真实接入
`Hub.tsx` 调 `invoke("list_public_pool")` 但 fallback 路径没处理：如果后端 401（未登录）会卡 loading。需要：
- 401 → 跳 onboarding
- 网络断 → 显示离线状态 + 重试按钮

### 12. 客户端 TaskDetail 评论/活动 tab 还是 EmptyState placeholder
在 `routes/TaskDetail.tsx:165-175` 我留了 "EmptyState 待对接 /api/requirements/{id}/comments" — 应该真接入 API。

---

## 三、视觉/排版优化

### 13. 项目卡 hover 动效在低性能机上卡顿
`hover:-translate-y-0.5 hover:shadow-e3` 全局应用，每张卡都重绘。可以加 `will-change: transform` 优化。

### 14. 暗色模式下 SVG icon 颜色对比度不够
Lucide icon 默认继承 `currentColor`，但在 ink-muted 下颜色偏灰，需要提升暗色下的 `--ink-muted`。

### 15. 移动端 (< 768px) 顶导挤成两行
"看板" 下拉 + ⌘K + 主题切换 + 用户 pill 在窄屏会换行。需要做 mobile bottom-nav 或 hamburger。

### 16. 全局缺统一的"日期/时间"组件
当前各页面用 `new Date().toLocaleString("zh-CN")` slice/format 不统一。抽 `<DateTimeText>` 组件统一格式（相对时间 + 绝对时间 tooltip）。

---

## 四、测试覆盖

### 17. Playwright 只覆盖 chromium，没测 firefox / safari
Tauri 客户端用 WebView2（Chromium 内核），跟 chromium 一致；但 web 端用户可能用 Firefox / Safari。补两个 project。

### 18. 没有视觉回归测试
当前 23 张截图归档但没自动比对。可以加 `playwright-visual-regression` plugin 在 CI 跑像素 diff。

### 19. 没有 Lighthouse a11y / perf 跑通
Plan §10.1 说要跑 Lighthouse ≥ 90，本轮还没做。

### 20. 后端没有针对 `lead 可转派`（permissions.py 改动）的回归测试
应在 `app/tests/` 加：lead 用户调 `PUT /api/requirements/{id}/assignees` 成功；非 lead/submitter 调失败。

---

## 五、运维 / 部署

### 21. 没有 CI 配置
建议加 `.github/workflows/`：
- `web-build.yml`: TS check + vite build + Playwright e2e on PR
- `client-build.yml`: 在 Linux + Mac + Windows runners 跑 `tauri build` 出三平台 bundle
- `release.yml`: tag 触发自动上传 bundle 到 GitHub Releases

### 22. shared 包没发版本号 / 没 changelog
现在两端都 `"@yqgl/shared": "*"`。如果要拆出来给外部用，需要 changeset/semver。

### 23. 老 pywebview client 还在 `client/` 没清理
等 Tauri 客户端稳定后归档 `client/`。或加 README 说明 `client/` 已 deprecated。
