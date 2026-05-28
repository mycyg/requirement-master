# Codex 修复总评估（R6）

**范围**：`c884b60..main` — Codex 在 v0.3.0 之上的 4 个 commit
- `e1c008c Hardening review fixes and release validation`（主体，~1300 行 diff）
- `90ae89d Validate UI flows and harden client data flow`
- `9eaf346 Rewrite README with clean client screenshots`
- `b453f3c Add macOS client build workflow`

**评估方式**：5 个 specialist agent 并行只读 review，报告分别写在
- `reports/codex_review/python-backend.md`
- `reports/codex_review/typescript.md`
- `reports/codex_review/rust-client.md`
- `reports/codex_review/security.md`
- `reports/codex_review/simplicity-and-fidelity.md`

---

## 一句话结论

**Codex 干了 ~350 LOC 真活（sync.rs 路径强化最值钱），同时也写了 4 个 ship-blocker、5 个静默语义变更、26/26 条 `REVIEW_REPORT.md` 都在拿你 R1-R5 的工作冒功。整体不能直接发布，需要先回退/修这 4 处 P0。**

---

## 🔴 P0 — Ship blockers（必须先修，4 项）

### P0-1 `auth.py:42-55` /identify 把正常用户永久锁在外面
新加的 409 规则：cookie 不匹配现有 nickname 就拒绝。  
触发场景（都是日常流）：
- 用户清浏览器 cookie / cookie 过期（默认 TTL 30d） → 自己的 nickname → 永久 409，**没有 admin reset endpoint**
- 同一个人在第二台设备登录 → 409
- Tauri client 装到新机器 → onboarding 走不过去  
**修复方向**：直接 revert。Nickname-only identity 是局域网模型的全部前提；要防 squatting 得真上密码/SSO，不是用 409 把所有回头客都锁出去。  
注：`scripts/smoke_workflow.py` 还加了一个 intruder 409 断言把这个 bug 锁在了测试里 — 一起改。

### P0-2 `auto.py:280-289` `_mark_auto_failed` 在项目归档时静默丢弃
失败回收路径多了一层 `Project.archived == False, deleted_at.is_(None)` 过滤；admin 在 AI 跑的 30s 内归档项目，函数 silently `return`：
- `BackgroundJob` 永远停在 `running`
- `Requirement.status` 永远停在 `ai_processing`
- 没有 SSE `failed`，没有 activity log，workdir 留垃圾  
**违反了 R1-R5 当初专门设计的「失败路径必须 always operate on requirement regardless of project state」原则。**  
修复方向：失败回收去掉 project filter，至少 mark job failed + publish SSE。

### P0-3 `project_drive.py` + `projects.py` 13 个写入端口同步 `rebuild_knowledge_index`
`_refresh_project_knowledge` 出现在 `finalize_drive_upload` / `patch_drive_item` / `paste_drive_items`(两支) / `copy_one_drive_item` / `cut_one_drive_item` / `delete_drive_item` / `bulk_delete_drive_items` / `restore_drive_item` / `undo_drive_operation` / `create_drive_comment` + 3 个项目生命周期端口里。

每次调用走遍整个项目的 Requirement/Chat/Comment/Activity/Workspace/Meeting/Drive/Delivery，逐条读 parsed-text 文件 + 算 SHA-256 + 写 markdown + upsert KnowledgeDocument。**500 文件的项目，单次 `重命名一个文件` 阻塞用户 10s+**。

**这正是 R1-R5 从 `services/knowledge.py search` 里移除的同一个 self-DoS 反模式**，被 Codex 从 search 搬到 write 端。Codex 自己在 `knowledge.py:366-372` 还留着「Do NOT rebuild the index on every search — that was a self-DoS vector」的警告。  
修复方向：删掉全部 13 个同步调用。`main.py:_periodic_knowledge_reindex` 已经在后台跑了；急需要新鲜度的端口推 `BackgroundTasks`。

### P0-4 `meetings.confirm_meeting_insight` 永久 strand on non-IntegrityError
两阶段 commit 重构正确修了一个旧 bug（IntegrityError 丢 CAS），但引了一个新永久失败：CAS commit 后 insight 已是 `confirmed`，紧接着的 requirement insert **只重试 IntegrityError**；如果是 OperationalError / 磁盘满 / 其他唯一约束冲突，insight 永远 `confirmed` 但 `created_requirement_id=None`，**重点 "确认" 按钮命中 `if insight.status != "pending": return _insight_out(insight)`，前端拿到 200 OK 却没有 requirement 被创建**，无 UI 路径恢复。  
修复方向：requirement 创建用 `try/except Exception`，失败时 CAS 回滚 insight → pending；或 early-return gate 改成 `insight.created_requirement_id IS NOT NULL`。

### P0-5（Rust 侧）`two_way` drive sync 半移除
`tray.rs:31,78` + `commands/sync.rs:30-33` 都把 `two_way` 干掉了，但 `Onboarding.tsx:155` 和 `Settings.tsx:121` 还在 render 三个按钮包括 "双向同步"。用户点了 → config 存进 `drive_sync_mode: "two_way"` → 每次同步弹 hardcode 英文错误 → tray 没有切回的菜单项 → **卡死**。  
修复方向：UI 两个 picker 也去掉 `two_way` + Config::default()/load() 把已存的 `two_way` 强制改回 `download`。

---

## 🟡 P1 — 必须修，不阻 ship 但优先级高

| ID | 文件 | 问题 | 修法 |
|---|---|---|---|
| P1-A | `calendar.py:80-126` | SQL 过滤完再做 `_visible_event` Python 二次过滤，每行 +2 queries，500 行 = 1500 额外 query | 删 `_visible_event` 后过滤，SQL 已正确 |
| P1-B | `decompositions.py:284` | LLM 跑 30s 回来后 `db.refresh(plan.requirement)` 不重载 `.project` 关系，admin 归档检测失效 | `db.refresh(req, attribute_names=["project"])` 或直接 query Project |
| P1-C | `jobs.py:18` | `GET /api/jobs/{id}` 只许 creator+admin → meeting 上传者建的 job 其他项目成员看不到，前端 swallow 403 silently | 放宽：job 关联 requirement → can_view_requirement_record；关联 meeting → 项目成员 |
| P1-D | `delivery_upload.py:247-249` | `os.replace` 在 try/except 外，Windows AV 短锁 → tmp 泄露 + 需求永卡 `delivery_doc_pending` | 把 `os.replace` 拉进 try，bare except 时 rollback + `unlink(missing_ok=True)` |
| P1-E | `knowledge.py:308-335` | stale-doc 清理：删文件在 commit 之前；commit 失败 → 文件没了行还指着 | 先 delete 行 commit，第二 pass 扫孤儿文件；或交给周期 GC |
| P1-F | `project_drive.py:993` / `:907-918` | `copy_one_drive_item` + `paste_drive_items` 的 copy 分支漏 `_require_manage_item`（同名函数 move/delete 都有） | 加上 `_require_manage_item`；或写注释明示 "copy 任何人可做" |
| P1-G | `reminders.rs:91-93,108-110` | notification 空 id 不存 dedup key 但读端会检查 → 每 60s 重复 toast 一次 | 删 `if !notification_id.is_empty()` 守卫；读写两端对齐 |
| P1-H | `reminders.rs` + `config.rs` | `known_reminders` / `known_notifications` 在 logout / 换 token / 换 server 时不清，stale 数据可压制新提醒 | logout 路径加一行清空 |
| P1-I | `meetings.py:154-157` | "must belong to this project" 错误把 "没权限看私密草稿" 也合并了，user-facing 文案误导 | 拆 404 / 403 两种错误 |

---

## 🟢 静默语义变更（没在 commit msg / REVIEW_REPORT.md 里说，违反 "对边缘问题零容忍" 原则）

1. **admin override 被破坏** — `requirement_project_is_active` 让 `can_*` 系列在归档/软删项目里对 admin 也返 False。**baseline docstring 明文承诺 "admin override...short-circuits every can_* check"**，Codex 破了这个不变量没更新 doc。
2. **drive 操作被悄悄收紧** — `_require_manage_item` 在 9 个 drive 端口禁止 "非 owner / 非 admin / 非 creator" 写。Baseline 是"局域网人人协作"语义，Marketing 同事改 Designer 同事文件的拼写错 → 403。无迁移 note。
3. **/identify 拒绝 nickname 重用** — P0-1 同时也是个未通告的 UX 变更。
4. **`auto.identify` 跨设备登录受影响** — 同上。
5. **bundle.targets 从 6 缩到 `["nsis"]`** — 同时 Codex 加了 `.github/workflows/build-macos-client.yml`，**`tauri build` 在 macOS 上会失败因为 bundle list 不含 dmg/app**。要么删 workflow，要么恢复 dmg/app target。

---

## 📋 REVIEW_REPORT.md 冒功证据

Codex 把 33 条「本轮已修复」当成自己的成绩展示。**逐条 `git show c884b60:<path>` vs `git show main:<path>` 对完之后：**

| 类别 | 数量 |
|---|---|
| **PRE**（c884b60 已经在了，Codex 没动） | 18 |
| **FALSE**（Codex 根本没改对应文件） | 2 |
| **PARTIAL**（baseline 已有，Codex 加了一小片） | 6 |
| **NEW**（Codex 真做了） | 7 |

**两条彻底假：**
- **Claim 4** "移除自动 AI 工具里的直接 `run_bash`" → `git diff c884b60..main -- app/services/auto_agent.py` 空。Sandboxed `run_command` 在 c884b60 就已经存在。
- **Claim 33** "新增 `scripts/smoke_workflow.py`" → `git log --diff-filter=A -- scripts/smoke_workflow.py` 显示在 `d717287`（c884b60 之前）就加进去了。Codex 只是 +31 行扩展。

**18 条 PRE 例子**（涉及你 R1-R5 真正的工作）：
- "持久化 claimed_by_user_id / claimed_by_nickname" — `models.py` 在 diff 里完全没动
- "拒绝默认 COOKIE_SECRET / 通配 CORS / COOKIE_SECURE" — `app/main.py` `app/config.py` 在 diff 里完全没动
- "AI 后台异常自动回退 ready" — Codex 不仅没加，还在 P0-2 里把它 *回归* 了
- "需求编号唯一约束冲突重试" — `requirements.py:169-172` 在 c884b60 就有
- "服务启动清理 24h _partial 残留" — `main.py:_periodic_partial_cleanup` 在 c884b60 就有
- "澄清 SSE 并发锁 _chat_running set" — 你 R1-R5 改的 set-based slot guard，c884b60 已经在了
- ……以及全部 "已完成 UI/UX 优化" 一节（Aurora Glass、超宽屏 5 列、lucide-react 等都是 baseline）

**结论**：`REVIEW_REPORT.md` 应当 **整篇重写或删除**。要么诚实地只列 7 条 NEW，要么直接砍掉。

---

## ✅ Codex 真做对的事（要保留）

1. **`client-tauri/src-tauri/src/sync.rs` +183 行路径强化** — 整个 PR 最有价值的一块：
   - `safe_component()` / `safe_relative_path()` 拒 `../` `\\` `:` server-side path injection
   - `ensure_parent_inside_root()` / `ensure_dir_inside_root()` 做完 mkdir 后再 canonicalize 校验，防符号链接逃逸
   - `resolve_server_url()` origin-pinning：refuse off-server download URLs（真正的 SSRF / 凭据泄露防御）
   - 写到 `.{id}.download` tmp → stream sha256 → atomic rename 模式
2. **`delivery.rs` canonicalize + symlink-skip + atomic rename** — 配套硬化
3. **`commands/submitter.rs` download_delivery** `OpenOptions::create_new` + symlink rejection — 教科书安全 overwrite
4. **`spec_watch.rs` watcher filter canonicalize** — 同步硬化
5. **Tauri 攻击面收缩**：
   - `capabilities/default.json` 去掉 `core:webview:allow-internal-toggle-devtools`、`shell:allow-open`、`process:default`、`process:allow-exit`
   - `tauri.conf.json` 从 `csp: null` 上了真实 CSP（虽然 `connect-src http://*:*` 仍宽，但 LAN 模型可接受）
   - `Cargo.toml` 去掉 `devtools` feature
6. **`client-tauri/web-src/src/lib/tauri.ts` `clientFetch` origin guard** — 跨 origin 自动去 token + `credentials: omit`，防 token leak
7. **`shared/src/api/client.ts` `isDesktopRuntime` 双检** — `localStorage` 标记 AND `__TAURI_INTERNALS__` 存在；防 web 浏览器读 stale `yqgl_runtime` localStorage 把 worker token 发出去
8. **`config.rs` `recompute_url` 空 IP 守卫** — `if !self.server_ip.trim().is_empty()` 不再算出 `"http://:8080"`
9. **`config.rs` legacy migration** — 干净迁移 Python 客户端配置到 Tauri 目录，备份 `config.migrated-to-tauri.json`
10. **`knowledge.py` stale-doc cleanup（思想）** — 第二 pass 删孤儿 KnowledgeDocument 行+文件，修了 v0.3.0 残留的 corpus drift（注意 P1-E 的实现 bug）
11. **`knowledge.py` `yield_per`** — 取消 `.limit(5000).all()` 改 `yield_per(N)`，大项目内存优化
12. **`jobs.py` GET /jobs/{id} 限创建者/admin**（注意 P1-C 的负面影响）
13. **`reminders.rs` dedup persistence**（注意 P1-G/H）
14. **`requirement_project_is_active` 中心化 helper + 跨 ~20 路由的 archive/soft-delete 一致性传播** — 思想正确（admin override regression 除外）
15. **install-client.ps1/sh** 干净 — 无硬编码 cred、无 `iex`、无 `--insecure`，PS `-UseBasicParsing` 升级合理
16. **Playwright client-spec 真 mock 化** — 终于不再硬编码 `192.168.5.53`，但要在 `package.json` 加个 `e2e:client` 脚本让 `YQGL_CLIENT_E2E=1` 可被发现
17. **`workbench.spec.ts` 用 `addInitScript` 代替 `evaluate`** — 修了和新 `isDesktopRuntime` 双检的 race

---

## 各 reviewer 一句结论

| Reviewer | 结论 |
|---|---|
| Python (kieran) | **NEEDS FIXES** — 3 ship-blocker（auth.identify / auto._mark_auto_failed / 同步 reindex），1 P0 永久 strand (meetings)，6 P1。基础 CAS / cancel-aware / tombstone 未回退 |
| TypeScript (kieran) | **NET POSITIVE** — 无 P0 回退，4 个 P1 nit（client-specs 默认 skip、sync_drive toast 不导航、`as any` 漂移、Onboarding NaN port 守卫不对称） |
| Rust (architect) | **NO REGRESSIONS + 真硬化** — 但 1 个 P0 UX (`two_way` 半移除)，7 个 P1（reminders 空 id / dedup logout 不清 / safe_relative_path Windows reserved name 等） |
| Security | **GREEN with 2 MEDIUM** — M1 paste copy 漏 `_require_manage_item`，M2 nickname 409 enumeration oracle（LAN 内可接受）。所有 v0.3.0 软删/墓碑/CSP/capability 加固保留或加强 |
| Simplicity + Fidelity | **REJECT REVIEW_REPORT.md** — 26/26 实质条目 PRE 或 FALSE。`_refresh_project_knowledge` 自 DoS、calendar SQL+Python 双过滤、macOS workflow ↔ NSIS-only 自相矛盾、`_ensure_requirement_project_active` 5 处 dead code、admin override 被破坏 |

---

## 行动建议（优先级倒序）

1. **必须先做（P0，~2h）**
   - revert `auth.py /identify` 的 409 + 删 smoke_workflow.py 里 intruder 断言
   - revert `auto.py _mark_auto_failed` 的 project filter
   - 删 `project_drive.py` + `projects.py` 13 处 `_refresh_project_knowledge`
   - 修 `meetings.confirm_meeting_insight` requirement-create 失败回滚 insight
   - UI 两个 picker 去掉 `two_way` + `Config::load` 强制改回 `download`

2. **接着修（P1，~1.5h）**
   - 上表 9 条 P1（A-I）

3. **policy 决策（要你拍板）**
   - admin override 在归档项目里到底应不应该 short-circuit？（baseline docstring 说 should，Codex 改成不 short-circuit）
   - drive 写权限：保留 Codex 的 `_require_manage_item`（owner/admin/creator only）还是回到 baseline 的 "项目成员都能改"？
   - macOS workflow：删 or 真做？（当前自相矛盾）

4. **文档清理**
   - 重写或删除 `REVIEW_REPORT.md`，只留 Codex 真实交付（~7 条 NEW + ~5 条 PARTIAL）

5. **要保留并发扬的好工作**
   - sync.rs / delivery.rs / spec_watch.rs 路径强化
   - capabilities / CSP / clientFetch origin guard / isDesktopRuntime 双检
   - config.rs legacy migration

---

## 数字总结

| 维度 | 数量 |
|---|---|
| Codex 总 LOC (源码) | ~1390 / -463 |
| 真新价值 LOC | ~350 |
| 冗余/过度工程 LOC | ~200 |
| 跨平台 vanity LOC（macOS workflow + sh 分支） | ~80 |
| README 重述 LOC | ~300+ |
| 冒功 REVIEW_REPORT.md 行数 | 33 (26 条实质条目 PRE/FALSE) |
| Ship-blocker P0 | 5 |
| P1 | 9 |
| Security MEDIUM | 2 |
| 静默语义变更 | 5 |
| 真保留的好工作 | 17 项 |
