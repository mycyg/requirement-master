# R7 Round 6 — TypeScript + UX/interaction quality

## Verdict: NEEDS FIXES (4 × P2, 3 × P3)

Scope reminder. `git diff` since the R7-R5 base touches ZERO `*.ts/*.tsx` (HEAD=`f70f3e6`,
the only post-R5 commit `f70f3e6` changed `schema_migrations.py` + reports; `c92b906`
is a `.gitignore` tweak). The R5 base commit `8d30bc7` was rewritten by the history
scrub and is no longer reachable, but the claim holds: the TS surface is byte-identical
to R5's CLEAN pass. So **the type-safety / React-correctness verdict is unchanged: CLEAN**
(0 P0/P1, all R5 carryovers still closed — re-spot-checked the token guards in
RequirementDetail, ProjectDrive, Hub/FileAttachRail logic by reading, no regressions).

This round's findings are all from the *fresh UX/interaction-quality angle the prompt
asked for*, not from TS-correctness. They are real, user-visible blemishes a
zero-tolerance user would hit — specifically four async reads that swallow their
rejection so a server/auth/network failure renders as a **fake empty/loading state**
instead of an error. The app has NO global fetch-error surface (`json()` in
`shared/src/api/client.ts:32` throws on non-OK; there is a `ToastHost` mounted in
`App.tsx:110` but pages surface errors via local inline banners, and these four
sites have neither a `.catch` nor a toast), so the rejection dies as an unhandled
promise in the console only.

This is a genuinely high-polish UI — 28 of 32 reviewed surfaces have textbook
loading/empty/error handling, busy-disabled submits, double-submit guards, confirm
modals on destructive actions, and aria-labels. The four misses below are the same
one-line omission repeated, plus three cosmetic P3s.

---

## Loading / empty / error state audit

### P2-1 — ActivityTimeline: failed fetch = permanent fake "加载中…" (worst of the four)
`web/src/components/ActivityTimeline.tsx:35-42`
```ts
const [items, setItems] = useState<Activity[] | null>(null);
useEffect(() => { api.listActivity(reqId).then(setItems); }, [reqId]);  // no .catch
if (!items) return <div className="text-stone-500">加载中…</div>;
```
`items===null` is the loading sentinel. If `listActivity` rejects (401/404/500/offline),
`items` stays `null` forever → the "活动" tab spins on "加载中…" with no error, no retry,
no escape. This is the most noticeable because it never resolves to a terminal state.
**Fix:** add `.catch((e) => setErr(String(e)))` with an `err` state, and render an error
+ retry block (mirror the pattern already used in `DeliverablesTab.tsx:18-28`).

### P2-2 — ChatHistory: failed fetch masquerades as "无对话"
`web/src/pages/RequirementDetail.tsx:466-469`
```ts
const [msgs, setMsgs] = useState<any[]>([]);
useEffect(() => { api.listChatMessages(reqId).then(setMsgs); }, [reqId]);  // no .catch
if (msgs.length === 0) return <div className="empty-state">无对话</div>;
```
A failed load is indistinguishable from a requirement that genuinely has no chat
history — user sees "无对话" and assumes the data is gone. **Fix:** `.catch` →
error state distinct from the empty state. (Also: `msgs: any[]` is the one `any`
in the reviewed web surface — pre-existing, out of this round's scope, but worth a
`StoredChatMessage[]` follow-up since the API already returns that type.)

### P2-3 — CommentsPanel: failed initial load masquerades as "还没有评论"
`web/src/components/CommentsPanel.tsx:13-14`
```ts
const refresh = () => api.listComments(reqId).then(setItems);  // no .catch
useEffect(() => { refresh(); }, [reqId]);
```
Note this component DOES have an `err` state and renders it (line 70-75) — but only for
the `addComment` path. The initial/refresh read silently swallows. A user whose comment
list failed to load sees "还没有评论" and may re-post a duplicate comment thinking the
first never sent. **Fix:** `api.listComments(reqId).then(setItems).catch((e) => setErr(String(e)))`
— the error UI already exists, just wire it up.

### P2-4 — DriveHome: failed project list masquerades as "还没有项目"
`web/src/pages/DriveHome.tsx:8-11`
```ts
useEffect(() => { api.listProjects().then(setProjects); }, []);  // no .catch
// → renders "还没有项目，先建一个项目再用网盘。"
```
Same masking class, lower stakes (read-only index page). A logged-in user with projects
who hits a transient failure is told they have none. **Fix:** add `.catch` + error line.
(Compare the sibling `Home.tsx:22` which calls the identical API *with* a catch.)

### Everything else in this category is CLEAN
- **Dashboard** (`Dashboard.tsx`): error banner, per-bucket empty states, SSE reconnect
  with exponential backoff + visibility-pause, last-sync timestamp, connected indicator.
- **RequirementDetail / Clarify / ProjectView**: `loadErr` + **retry button** + (ProjectView)
  "回项目列表" escape; token-guarded refresh to prevent A→B navigation races.
- **CalendarPage / NewRequirement / Home / NotificationsPage / KnowledgePage / PlanningPage /
  HealthPage / ProjectMeetings / ProjectDrive**: every async action sets a `busy`/loading flag,
  disables its trigger, surfaces errors inline, and has an actionable empty state
  (most empties include a CTA, e.g. Home's "建一个开始", ProjectDrive's "拖文件进来").
- **ProjectDrive**: busy *pill with spinner*, dismissible error pill (with its own
  `aria-label="关闭错误"`), conflict-resolution prompt on upload, Firefox download fix.
- Double-submit guards present where it matters: `Clarify QuestionCard.submit` opens with
  `if (busy) return` (`Clarify.tsx:399`); every `button-primary` is `disabled={busy || !valid}`.

---

## Form validation + a11y audit

Validation is strong throughout:
- **NewRequirement** (`NewRequirement.tsx:56-97`): per-step gating (`canNext`), required-field
  messages ("先写一下要做什么。" / "截止时间是这事情存在的前提"), creates the draft only
  after the required step, disables Back/Next while `busy`.
- **ProjectStateConfirm** (`ProjectStateConfirm.tsx:51`): destructive actions require typing
  the exact project name (`canConfirm = value.trim() === project.name && !busy`), `role="dialog"
  aria-modal="true"`, labeled input, autofocus.
- **NicknameDialog / CalendarPage / CommentsPanel / KnowledgePage / WorkspaceCard**: submit
  disabled until non-empty; Enter-to-submit where natural; `WorkspaceCard` even shows a
  three-state button ("保存进度" / "保存中..." / "已保存") and a dirty-guard so an SSE refresh
  can't clobber in-flight typing (`RequirementDetail.tsx:717-731`).

a11y is largely good — icon-only buttons in ProjectDrive, AssigneeSelector (`移除 ${nick}`),
SettingsDialog (`关闭设置`), ProjectStateConfirm (`关闭`), and the TopNav (`命令面板`, `设置`,
`新手引导`, `切换外观`) all carry `aria-label`. Two gaps:

### P3-1 — Icon-only buttons with `title` but no `aria-label` (screen-reader-invisible)
The SVG icons are correctly `aria-hidden`, but two icon-only buttons rely on `title`
alone, which is not an accessible name:
- `web/src/components/SpeakButton.tsx:92-100` — the play/pause button (`title={`朗读 (${voice})`}`,
  no `aria-label`). It's used many times per page (every chat bubble, every summary).
- `web/src/pages/CalendarPage.tsx:188` — the delete-event trash button (`title="删除"`, no `aria-label`).
**Fix:** add `aria-label` matching the `title`. (ProjectDrive already does both on its
icon-only row actions — use it as the template.)

### P3-2 — No catch-all 404 route → blank page on unknown URL
`web/src/App.tsx:149-167` defines explicit routes with no trailing `<Route path="*">`.
A mistyped/stale URL that matches nothing renders the nav with an empty body — a dead-end
with no "page not found / go home" affordance. **Fix:** add a `*` route → small NotFound
with a Link to `/`.

---

## Dead UI / interaction blemishes

No dead buttons or links-to-nowhere found. All `<Link>`/`<a>` targets resolve to a defined
route or a real `/api/...` endpoint; all buttons have handlers. Two micro-notes (P3 / sub-P3):

### P3-3 — SettingsDialog edge cases (low probability)
`web/src/components/SettingsDialog.tsx`
- "保存接单状态" button (line 110-123) has **no busy/disabled guard** — double-clickable;
  the call is idempotent so harmless, but there's no in-flight feedback on a slow link
  (the `statusMsg` only appears after it returns). Minor.
- TTS voices: if the service returns `ready:true` with an empty `voices` array
  (line 56), the panel shows "加载中…" permanently (line 166) because empty-voices and
  still-loading share the same render branch. Unlikely (a live TTS service always has
  ≥1 voice) but technically a stuck state.

### Non-issues confirmed (looked, decided NOT a blemish)
- **Date formatting consistency**: two idioms coexist — `parseServerDate()` (Tauri client +
  newer web pages: NotificationsPage, PlanningPage, RequirementDetail, AssigneeSelector) and
  the inline `new Date(value + "Z")` guard (older web pages: Dashboard, CommentsPanel,
  ActivityTimeline, DeliverablesTab, ProjectView, ProjectDrive, ProjectMeetings, CalendarPage).
  Both correctly coerce naive-UTC → local. Not a bug, just stylistic drift; a cleanup to
  funnel all web pages through `parseServerDate` would be nice-to-have, not required.
  The raw `new Date(value)` calls (CalendarPage `isoLocal`, NewRequirement/Clarify ISO
  conversions, AILiveView `ev.at`) all operate on local `datetime-local` input values or
  client-stamped event times, where raw parsing is correct.
- **PlanningPage** empty `rows`: when not loading and `rows.length===0` the grid renders empty
  with no top-level "no one scheduled" message. In practice `workload` returns all users, so
  this is effectively unreachable; each row already has its own empty-requirements line. Skipped.
- **ProjectDrive grid double-click** (`ProjectDrive.tsx:533`) toggles selection on click 1 then
  previews on click 2 — slightly odd but intentional and the operator precedence is correct.

---

## Coverage

Read in full (web/src, 33 files of the React surface):
- Pages: App, Dashboard, Home, ProjectView, RequirementDetail, Clarify, NewRequirement,
  CalendarPage, KnowledgePage, PlanningPage, HealthPage, NotificationsPage, DriveHome,
  ProjectDrive, ProjectMeetings.
- Components: ActivityTimeline, AILiveView, AssigneeSelector, ClientDownloadBanner,
  CommentsPanel, DeliverablesTab, FileUpload, NicknameDialog, ProjectStateConfirm,
  SettingsDialog, SpeakButton, StatusBadge (shim), VoiceButton.
- Shared: `shared/src/api/client.ts` (error model), `shared/src/api/time.ts` (parseServerDate),
  `shared/src/api/index.ts`.
- Tauri client (`client-tauri/web-src/src`, parity spot-check): grep for `.then(setX)`
  without `.catch` → **zero** (it uses `invoke` + try/catch uniformly). The four silent
  reads are web-only.

Method: full read of every web React file; targeted greps for `new Date(`, `parseServerDate`,
`.then(` to map date handling and unguarded async reads; cross-checked each finding against
the `json()` error model and the absence of a global error toast on these paths.

Recommendation: the four P2s are each a one-line `.catch` (+ an error render where the
component lacks one — only ActivityTimeline needs new state; the other three can reuse an
existing or trivial error line). Fixing them, plus the two P3 `aria-label`s and the `*`
route, would return this surface to genuinely CLEAN. None block; all are real and worth
closing before the streak resumes.
