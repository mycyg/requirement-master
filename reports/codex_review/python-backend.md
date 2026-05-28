# Codex Python Backend Review

## Summary
**Needs fixes — ship-blocker on 3 items.** Codex did NOT regress the R1–R5 CAS / cancel-aware / tombstone foundation, but added several new P0/P1 bugs and a substantial REVIEW_REPORT.md fidelity problem (most bullets describe pre-existing work, not the diff). Worst offenders: (1) `auth.identify` now 409s legitimate browser re-login after cookie expiry, (2) AI auto-process failure path silently abandons jobs when project is archived mid-run, (3) project-drive endpoints synchronously rebuild the entire project knowledge corpus on every write.

## P0 — Regressions or critical bugs

### P0-1 — `auth.py:54-58` — `identify` blocks legitimate re-login
**File:** `app/routers/auth.py:42-66`

The endpoint now refuses to return a session unless the caller already presents a cookie whose user id matches the nickname being identified. With `existing_session = Depends(optional_current_user)`:
```python
existing = db.query(User).filter(User.nickname == nickname, User.deleted_at.is_(None)).first()
if existing and (not existing_session or existing_session.id != existing.id):
    raise HTTPException(409, "nickname already registered; ...")
```

**Failure modes this introduces** (all are normal day-to-day flows on a LAN/nickname app):
- Browser cleared cookies / cookie expired (`COOKIE_TTL` default 30d) → user types their nickname → 409 forever, no recovery.
- User opens the web UI from a second device with the same nickname → 409. There is no admin endpoint to reset.
- Tauri client install on a new machine for the same user → onboarding 409s out, user can't reach the dashboard.
- Anyone running `scripts/smoke_workflow.py`'s pre-existing alice/bob/carl flow now needs cookie persistence to re-run; only saved by the test's own use of `TestClient` per-user.

The error message tells the user to "ask an admin to reset", but there is no such reset endpoint anywhere in the diff.

**Suggested fix:** revert this change. Nickname-only identity is the whole point of the LAN model — `get_or_create_user` followed by `issue_cookie` is the correct behavior. If the intent was to prevent nickname squatting in a multi-tenant deployment, that needs a real auth mechanism (password/SSO), not a 409 that traps every returning user.

### P0-2 — `auto.py:280-289` — `_mark_auto_failed` silently drops failure recovery on archived project
**File:** `app/routers/auto.py:275-314`

```python
r = (
    db.query(Requirement)
    .join(Project, Project.id == Requirement.project_id)
    .filter(Requirement.id == req_id,
            Project.archived == False, Project.deleted_at.is_(None))
    .first()
)
if not r:
    return  # ← silently abandons the job
```

If a user clicks "AI auto-process" → AI runs for 30s+ → meanwhile project owner archives or admin soft-deletes the project, this function returns with no side effects:
- `BackgroundJob` stays in `running` forever (no SSE `failed` published).
- `Requirement.status` stays in `ai_processing` (terminal-looking from UI).
- No `ai_failed` activity log entry, no `requirement.updated` bus message.
- Workdir under `data/auto-agent/<req_id>/` is left behind (cleanup only runs on the success path).

Same defect at `_run_and_finalize` (`auto.py:149-160`): the success path also `return`s early if the project went away, but at least the success-without-delivery case is recoverable. The failure path leaves the requirement permanently stuck.

**Suggested fix:** the failure-recovery path must operate on the requirement regardless of project archive state. Either:
- Drop the project filter in `_mark_auto_failed` and `_run_and_finalize` (use the original `db.query(Requirement).filter(Requirement.id == req_id)`).
- Or keep the filter but also load the bare requirement / job as a fallback and at minimum mark the job `failed` with reason "project archived during AI run" plus publish the `ai.failed` SSE.

The pre-`c884b60` code did NOT filter on project state here, exactly so that admin actions during AI processing wouldn't trap state. Codex regressed this without realizing.

### P0-3 — `project_drive.py` + `projects.py` — synchronous `rebuild_knowledge_index` on hot paths
**Files:** `app/routers/project_drive.py:214-219, 766, 920, 967, 982, 1010, 1035, 1054, 1112, 1186`; `app/routers/projects.py:107, 124, 141`

`_refresh_project_knowledge` is now invoked inside the request handler for: `finalize_drive_upload`, `patch_drive_item`, `paste_drive_items` (both branches), `copy_one_drive_item`, `cut_one_drive_item`, `delete_drive_item`, `bulk_delete_drive_items`, `restore_drive_item`, `undo_drive_operation`, `create_drive_comment`, and the three project lifecycle endpoints (archive / restore / soft-delete).

What `rebuild_knowledge_index(db, project_id=X)` actually does (see `services/knowledge.py:300-335`):
1. Iterates every Requirement, ChatMessage, Comment, ActivityLog, RequirementProgressUpdate, MeetingRecord, MeetingInsight, ProjectDriveVersion, and Delivery in the project (yield_per 200-500, but still tens of thousands of rows for a mature project).
2. For each, reads the parsed-text file from disk (`v.parsed_text_path`), computes a SHA-256, writes a markdown file under `data/knowledge_corpus/`, upserts a `KnowledgeDocument` row.
3. Then a second pass deletes stale `KnowledgeDocument` rows + their corpus files.

On a project with ~500 files this is ~10s+ of foreground I/O blocking the user's "save filename" click. On the project archive path it's even worse — it has to walk the whole corpus to mark everything stale.

The R1-R5 hardening specifically introduced a **periodic background reindex** in `main.py` (`_periodic_knowledge_reindex`) and **removed reindex-on-every-search** from `services/knowledge.py` precisely to avoid this self-DoS pattern. Codex's change is the same antipattern relocated from search to write.

**Suggested fix:** remove all 13 `_refresh_project_knowledge(...)` calls. The periodic background reindex in `main.py` already keeps the corpus fresh. If freshness is critical for a specific endpoint, push the rebuild onto `BackgroundTasks` and limit it to the affected requirement/source, not the whole project.

### P0-4 — `meetings.py:438-441` — meeting-insight confirm permanently strands on non-IntegrityError
**File:** `app/routers/meetings.py:415-490`

Codex split the CAS+create into two transactions (CAS commits first, then retry-insert the requirement). This correctly fixes the pre-existing IntegrityError-loses-CAS bug, but introduces a new permanent-failure mode:

```python
db.execute(sql_update(MeetingInsight).where(...).values(status="confirmed", ...))
if cas.rowcount == 0: return early
db.commit()   # ← insight is now permanently confirmed
... 5-iteration retry on IntegrityError only ...
else:
    raise HTTPException(500, "could not allocate requirement code")
```

If the requirement insert fails for any non-IntegrityError reason (DB temporarily unavailable, disk full, unique constraint on something OTHER than `code`, OperationalError mid-flush), the insight is committed as `confirmed` with `created_requirement_id=None`. A subsequent re-click on "确认" hits:
```python
if insight.status != "pending":
    return _insight_out(insight)  # returns success, but no requirement was ever created
```
The user sees a 200 OK, the insight panel shows "confirmed", but no requirement was created. There is no UI / API path to recover.

**Suggested fix:** wrap the requirement insertion in `try/except Exception` and on failure roll the insight back to `pending` (a second CAS: status='confirmed' → 'pending') before raising. Alternatively, gate the early-return on `insight.created_requirement_id IS NOT NULL`, so a re-click on an orphan-confirmed insight re-runs the create.

## P1 — Important issues

### P1-1 — `calendar.py:120-124` — N+1 query after a sufficient SQL filter
**File:** `app/routers/calendar.py:80-122`

The list_events query already does outer-joins through `event_project`, `Requirement`, `req_project` with full visibility predicates. Then:
```python
rows = [ev for ev in q.order_by(...).limit(500).all() if _visible_event(db, ev, user)]
```
`_visible_event` (lines 68-77) does **two more queries per row**:
1. `db.query(Project).filter(Project.id == event.project_id).first()` for the project.
2. `db.query(Requirement).filter(Requirement.id == event.requirement_id).first()` then `can_view_requirement_record(req, user)` which triggers a lazy load of `req.project` (third query).

Up to 1500 extra queries per `GET /api/calendar/events`. And it's wholly redundant — the SQL `or_(..., and_(req_project.archived == False, req_project.deleted_at.is_(None), or_(<visibility>)))` already implements the same check.

**Suggested fix:** delete `_visible_event` and the post-filter. The query is already correct.

### P1-2 — `delivery_upload.py:248-249` — `os.replace` outside the try/except cleanup window
**File:** `app/routers/delivery_upload.py:247-250`

```python
db.refresh(r)
round_num = 1 + db.query(Delivery).filter(...).count()
out_path = out_dir / f"round-{round_num}.zip"
os.replace(tmp_path, out_path)        # ← if this raises (Windows file-lock), tmp_path leaks
d = Delivery(...)
try:
    db.add(d); db.commit() ...
except IntegrityError:
    db.rollback()
    out_path.unlink(missing_ok=True)
```
On Windows specifically, an antivirus scanner can briefly hold the tmp file open and make `os.replace` raise `PermissionError`. The CAS has already flipped status to `delivery_doc_pending` and there's no cleanup — the requirement is permanently stuck (no Delivery row, but status says "pending docs"). The tmp file is also leaked.

**Suggested fix:** move `os.replace` inside the try block, add a `db.rollback()` + `tmp_path.unlink(missing_ok=True)` on the bare-except / catch-all path. Or just do the file rename + record insert under one `try/except` umbrella.

### P1-3 — `decompositions.py:284` — `db.refresh(plan.requirement)` doesn't refresh the project relationship
**File:** `app/routers/decompositions.py:283-291`

```python
result = await analyze_requirement(plan.requirement, stage=plan.stage, actor=user)
db.refresh(plan.requirement)
if not requirement_project_is_active(plan.requirement):
    ...
```
`requirement_project_is_active` reads `getattr(req, "project", None)`. `db.refresh(req)` reloads the requirement's columns but does NOT eagerly reload the `project` relationship — that's the cached relationship from before the LLM call. If admin archived the project during the 30s+ LLM call, the in-memory `req.project.archived` is still `False` and the check passes incorrectly.

**Suggested fix:** `db.refresh(plan.requirement, attribute_names=["project"])` or `db.expire(plan.requirement, ["project"]); _ = plan.requirement.project` — or load fresh: `proj = db.query(Project).filter(Project.id == plan.requirement.project_id).first()` and check directly.

### P1-4 — `jobs.py:18` — view permission breaks decomposition / meeting status polling for non-creators
**File:** `app/routers/jobs.py:16-21`

New rule: only `job.created_by_user_id == user.id or is_admin(user)` can `GET /api/jobs/{id}`.

For meetings: the uploader creates the job, but other project members watching `ProjectMeetings` (which polls `getJob`) will now silently get 403s. The frontend swallows the error (`try { await api.getJob } catch { }`), so the meetings status pane never updates for non-uploaders. Recoverable but degrades UX for the most-shared meeting flow.

For decompositions: the worker is the job creator. The submitter watching `RequirementDetail?tab=decomposition` cannot poll their own decomposition job's progress.

For auto-process: the submitter is the job creator. The worker (`claimed_by_user_id`) cannot see job progress.

**Suggested fix:** broaden the visibility rule. Reasonable expansions: (a) job target is a Requirement → anyone who passes `can_view_requirement_record` can view; (b) job target is a Meeting → anyone in the project. Or attach a `viewer_user_ids` column when the job is created. At minimum, document the new restriction in REVIEW_REPORT.md so frontends know to hide the polling spinner.

### P1-5 — `knowledge.py:308-335` — stale-doc cleanup deletes corpus files outside transaction
**File:** `app/services/knowledge.py:308-335`

```python
for row in stale_q.all():
    if (row.source_type, row.source_id) in seen: continue
    if row.corpus_path:
        try: Path(row.corpus_path).unlink(missing_ok=True)
        except Exception: pass
    db.delete(row)
db.commit()
```
If `db.commit()` fails (e.g., concurrent insert wins a unique-constraint race or the DB connection drops), the corpus markdown files are already deleted from disk but the `KnowledgeDocument` rows still reference them. The next search will hit `ENOENT` on read.

**Suggested fix:** delete the rows first, commit, then in a second pass walk the corpus directory for orphaned files. Or skip the file deletion entirely and let a periodic GC sweep handle it.

### P1-6 — `project_drive.py:993` — `_require_manage_item` missing for `copy_one_drive_item`
**File:** `app/routers/project_drive.py:982-993`

```python
def copy_one_drive_item(item_id, target_parent_id, ...):
    item = _require_item(db, item_id)
    _require_folder(db, item.project_id, target_parent_id)
    copied = _copy_item(db, item, target_parent_id, user)
```
No `_require_manage_item`. The bulk `paste_drive_items` also skips the check in the `copy` branch (line 939). This is *probably* the intended design (anyone with view access can copy), but the bulk-delete now requires manage. Inconsistency: a user can copy a file they cannot delete, including copying it to root and then operating on the copy. If "manage" is the right gate for write operations, copy should match.

**Suggested fix:** decide policy explicitly and document it. If copy is intentionally open to viewers, add a comment; if not, add `_require_manage_item` to both copy entry points.

### P1-7 — `meetings.py:156` — `can_view_requirement_record` called during meeting-upload init can mask validation
**File:** `app/routers/meetings.py:154-157`

```python
if payload.requirement_id:
    req = db.query(Requirement).filter(Requirement.id == payload.requirement_id,
                                       Requirement.project_id == project_id).first()
    if not req or not can_view_requirement_record(req, user):
        raise HTTPException(400, "requirement_id must belong to this project")
```
The error message says "must belong to this project" but is now also raised for "you can't see this private draft requirement" — those are very different errors. A user uploading a meeting linked to *their own* draft requirement (`status='draft'`, submitter is the meeting uploader) is OK because `can_view_requirement_record` short-circuits on `is_submitter`. But if they reference a *teammate's* draft they own meeting-uploader access to, the error is misleading.

Also, `can_view_requirement_record` calls `requirement_project_is_active` which needs `req.project` loaded — there's no `joinedload`, so it lazy-loads.

**Suggested fix:** split the message into 404 "requirement not found in this project" vs 403 "you cannot link a private requirement"; or just keep the old behavior (existence check only) since the uploader is already enforced to be the meeting owner downstream.

## P2 — Style / minor

- **`reminders.py:48`**: the diff only adds `Project.archived == False` and tweaks a comment. The `Project.deleted_at.is_(None)` filter is from prior work but the REVIEW_REPORT.md claim "suppress soft-deleted projects" implies Codex added both. Just confusing attribution.
- **`notifications.py:98-104`**: outer-join + `or_(Notification.project_id.is_(None), and_(...))` is fine, but `Project` is joined on `Notification.project_id` without an alias; if `Notification` ever grows another `project_id` reference it'll silently break. Use `aliased(Project)` for safety like `calendar.py` does.
- **`planning.py:42`**: `.join(Project)` then `selectinload(Requirement.project)` issues a second project query for each row's `selectinload`. The join is for filtering; the selectinload is for output. Consider `contains_eager(Requirement.project)` to reuse the join.
- **`requirements.py:200`**: same `selectinload(Requirement.assignments).selectinload(RequirementAssignment.user)` with an unrelated `Project` join — fine, but no `contains_eager(Requirement.project)` despite the join; `_enrich`'s `r.project.slug` later forces a re-fetch per row anyway. Pre-existing N+1, not Codex's fault but adjacent to his changes.
- **`workspaces.py:124-125`**: `item.workspace.requirement` is a chain of two lazy loads inside `_require_item`; if the parent `_require_req` succeeded the relationships should already be eagerloaded. Consider `joinedload(RequirementWorkspaceItem.workspace).joinedload(RequirementWorkspace.requirement)`.
- **`auth.py:48-50`**: `existing_session: User | None` type-hinted parameter is good, but the new branch lacks a comment explaining why the 409 exists. Future readers won't know if this was intentional.
- **`project_drive.py:91-92`**: `_can_manage_project` uses `project.owner_nickname == user.nickname`. Nicknames can change semantics on admin tombstone (`_deleted_<id>` prefix). Better to compare `project.owner_user_id == user.id` if the model has it; otherwise nickname comparison is fine but should be noted.
- **`decompositions.py:264, 270, 286, 291`**: duplicate `update_job(...)` + `plan.status = "dismissed"` + `db.commit()` + `await publish_job(job)` blocks. Extract a helper `_cancel_decomposition_for_archive(db, plan, job, message)` to reduce 4 lines × 2 sites.
- **`smoke_workflow.py:53-55`**: the new `intruder` `TestClient` block confirms the 409 — which means the smoke test is locking in the P0-1 regression. After fixing P0-1, this assertion needs to change accordingly (or be deleted).

## REVIEW_REPORT.md fidelity check

The "本轮已修复" section (33 bullets) mostly describes work from earlier `c884b60` and prior commits, not Codex's actual diff. Verification:

| Claim | In Codex diff (`c884b60..main`)? |
|---|---|
| 摘要生成后改为 `summary_ready` (cancel-aware guard) | ❌ Pre-existing (chat.py:188 was already CAS-guarded). Codex only added a project-active filter to the same query. |
| 持久化 `claimed_by_user_id / claimed_by_nickname` | ❌ Pre-existing — `app/models.py` is **unchanged** in the diff. |
| 收紧通用状态接口 (allowed transitions, role gates) | ❌ Pre-existing in `update_status` (the `allowed` dict and CAS were already there). |
| 移除 `run_bash` AI tool | ❌ `app/services/auto_agent.py` not in the diff stat. |
| 拒绝默认 `COOKIE_SECRET` / 通配 CORS / `COOKIE_SECURE` | ❌ `app/config.py` / `app/main.py` not modified. |
| AI 后台异常自动回退 `ready` + 推送状态 | ❌ Pre-existing in `_mark_auto_failed`. Codex actually **regressed** this (P0-2). |
| `delivery_doc_pending` 状态流 + SSE 刷新 | ❌ Pre-existing — the CAS + `_finalize_doc` flow was there. Codex only added IntegrityError handling. |
| 托盘客户端 `raise_for_status` per chunk | ❌ Tauri client diff (out of scope). |
| 附件上传 chunk 校验 / chunk 完整性 | ❌ Pre-existing in `attachments.py` (only `Project` import added). |
| 服务启动清理 24h `_partial` 残留 | ❌ `app/main.py` `_periodic_partial_cleanup` is pre-existing. |
| 交付 ZIP 路径/条目/解压大小/压缩比校验 | ❌ `services/delivery_doc.py` (`inspect_zip_entries`) not in diff. |
| 需求列表 join 项目 slug + 提交人 nickname | ❌ Pre-existing — `_display_nickname` and the `selectinload` were already there. |
| 需求编号唯一约束冲突重试 | ❌ Pre-existing in `meetings.confirm_meeting_insight`. Codex restructured the commit ordering. |
| 澄清页从 summary 恢复 | ❌ Frontend change. Out of scope of these Python files. |
| 提交/澄清/AI/验收 提交人权限校验 | ❌ Pre-existing in `requirements.update_status` and `auto.trigger_auto`. |
| 附件草稿/接单可见性 | ❌ Pre-existing in `services/permissions.py:can_view_requirement_assets`. |
| 公私划分 (PRIVATE_REQUIREMENT_STATUSES) | ❌ Pre-existing constant. |
| 交付 ZIP 包提交人/接单人权限校验 | ❌ Pre-existing. |
| 上传 chunk 绑定发起用户 | ❌ Pre-existing in `delivery_upload.py:meta['user_id']` check. |
| 同步 ACK 仅提交人/接单人 | ❌ Pre-existing — `can_ack_requirement_sync` exists in baseline. |
| 澄清 SSE 并发锁 (`_chat_running` set) | ❌ Pre-existing `_chat_running: set[str]`. |
| AI 自动交付文档语言匹配 | ❌ `_auto_delivery_doc` unchanged in diff. |
| `scripts/smoke_workflow.py` 覆盖 | ✅ Codex extended this — added the 409 intruder check (which locks in P0-1) and the archive→404 sub-test. |
| (implicit) `requirement_project_is_active` checks on all routers | ✅ Genuinely Codex's work. |
| (implicit) `_validate_links` requirement-visibility in calendar | ✅ Genuinely Codex's work. |
| (implicit) `_require_manage_item` permission in drive | ✅ Genuinely Codex's work. |
| (implicit) Two-phase commit in `confirm_meeting_insight` | ✅ Codex (but introduced P0-4). |
| (implicit) `IntegrityError` handling in `delivery_upload.finalize` | ✅ Codex. |
| (implicit) `auth.identify` 409 gate | ✅ Codex (regression — see P0-1). |
| (implicit) `_refresh_project_knowledge` on drive writes | ✅ Codex (regression — see P0-3). |
| (implicit) `jobs.get_job` creator-only view | ✅ Codex (see P1-4). |

Verdict: **~75% of bullets in "本轮已修复" describe work that was already in `c884b60`**. The genuinely new work is the ~7 items at the end of the table, of which 3 are regressions. The report is misleading the reader into thinking Codex did a sweeping pass when the actual contribution is narrower (and partly net-negative).

## Positive changes worth keeping

- **`requirement_project_is_active` helper + propagation** across attachments, comments, chat, sync, workspaces, requirements, decompositions, planning, reminders, notifications, calendar, meetings. Clean factoring, replaces the ad-hoc `proj.deleted_at` checks. Add the `archived` arm too is a useful tightening (archive previously only hid from list_projects, not from per-requirement reads).
- **`sync.py:_active_requirement_query`**: nicely extracted helper, keeps `submit`/`sync_manifest`/`sync_ack` consistent.
- **`reminders.py:48` + `notifications.py:27, 67, 99-104`**: closes the gap where soft-deleted-project notifications/reminders kept firing.
- **`delivery_upload.py:209, 247`**: writing the zip to a `.tmp` first and `os.replace`-ing into `round-N.zip` AFTER CAS is the right ordering (subject to P1-2 cleanup tightening).
- **`smoke_workflow.py:74-98`**: the archived-project-seals-children sub-test is a genuinely useful regression guard for `requirement_project_is_active`. The `intruder` 409 assertion should be deleted with P0-1.
- **`meetings.confirm_meeting_insight` two-phase commit**: the *idea* of committing the CAS before the side-effect insert is right; just needs the failure-recovery in P0-4 to be production-safe.
- **`knowledge.py` stale-doc cleanup**: the second pass that deletes `KnowledgeDocument` rows whose `(source_type, source_id)` no longer appears is a legitimate fix for corpus drift. Just decouple from request handlers (P0-3).
- **`knowledge.py` `yield_per`**: switching from `.limit(5000).all()` to `.yield_per(N)` is a real memory win for projects with >5k chat messages / activity rows.
- **`project_drive._require_manage_item`**: tightens drive write authority. Worth keeping with the copy-policy clarification (P1-6).
