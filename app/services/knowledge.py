from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session, selectinload

from config import settings
from models import (
    ActivityLog,
    ChatMessage,
    Comment,
    Delivery,
    KnowledgeDocument,
    MeetingInsight,
    MeetingRecord,
    Project,
    ProjectDriveItem,
    ProjectDriveVersion,
    Requirement,
    RequirementProgressUpdate,
    User,
)
from schemas import KnowledgeSearchHit
from services.permissions import can_view_requirement_record


CORPUS_ROOT = settings.data_dir / "knowledge_corpus"


@dataclass
class SourceDoc:
    source_type: str
    source_id: str
    project_id: str | None
    requirement_id: str | None
    title: str
    source_url: str
    content: str


def _safe_name(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]+", "_", value)[:120] or "doc"


def _hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _read_json(raw: str | None) -> str:
    if not raw:
        return ""
    try:
        return json.dumps(json.loads(raw), ensure_ascii=False, indent=2)
    except Exception:
        return raw


def _requirement_visible(db: Session, req_id: str | None, user: User) -> bool:
    if not req_id:
        return True
    req = (
        db.query(Requirement)
        .join(Project, Project.id == Requirement.project_id)
        .filter(
            Requirement.id == req_id,
            Project.archived == False,  # noqa: E712
            Project.deleted_at.is_(None),
        )
        .first()
    )
    return bool(req and can_view_requirement_record(req, user))


def _source_docs(db: Session, project_id: str | None = None) -> Iterable[SourceDoc]:
    # Exclude soft-deleted projects from the index — without this, a
    # search would still surface lines from a project the admin tombstoned.
    project_q = db.query(Project).filter(
        Project.archived == False,  # noqa: E712
        Project.deleted_at.is_(None),
    )
    if project_id:
        project_q = project_q.filter(Project.id == project_id)
    for p in project_q.all():
        yield SourceDoc(
            source_type="project",
            source_id=p.id,
            project_id=p.id,
            requirement_id=None,
            title=f"项目：{p.name}",
            source_url=f"/p/{p.id}",
            content=f"# 项目：{p.name}\n\nSlug: {p.slug}\n\nOwner: {p.owner_nickname}\n\n{p.description or ''}",
        )

    req_q = (
        db.query(Requirement)
        .join(Project, Project.id == Requirement.project_id)
        .filter(Project.archived == False, Project.deleted_at.is_(None))  # noqa: E712
        .options(selectinload(Requirement.assignments), selectinload(Requirement.workspaces))
    )
    if project_id:
        req_q = req_q.filter(Requirement.project_id == project_id)
    for r in req_q.all():
        assignees = ", ".join(a.user.nickname if a.user else a.user_id for a in r.assignments)
        yield SourceDoc(
            source_type="requirement",
            source_id=r.id,
            project_id=r.project_id,
            requirement_id=r.id,
            title=f"{r.code} {r.title or '需求'}",
            source_url=f"/r/{r.id}",
            content=(
                f"# {r.code} {r.title or ''}\n\n"
                f"Status: {r.status}\nPriority: {r.priority}\nAssignees: {assignees or '公开池'}\n"
                f"Estimate: {r.estimate_hours or 'unset'}h ({r.estimate_confidence or 'unknown'})\n"
                f"Planning note: {r.planning_note or ''}\n\n"
                f"## Raw\n{r.raw_description or ''}\n\n## Summary\n{r.summary_md or ''}"
            ),
        )

    # Skip chats authored by users in requirements whose submitter is
    # soft-deleted — searching the knowledge base shouldn't surface
    # tombstoned users' clarify conversations to other users.
    # (ChatMessage has no user_id; only the submitter chats with the AI,
    # so the requirement's submitter IS the chat author.)
    from models import User
    chat_q = (
        db.query(ChatMessage)
        .join(Requirement, Requirement.id == ChatMessage.requirement_id)
        .join(Project, Project.id == Requirement.project_id)
        .outerjoin(User, User.id == Requirement.submitter_user_id)
        .filter(
            User.deleted_at.is_(None),
            Project.archived == False,  # noqa: E712
            Project.deleted_at.is_(None),
        )
    )
    if project_id:
        chat_q = chat_q.filter(Requirement.project_id == project_id)
    for m in chat_q.yield_per(500):
        yield SourceDoc(
            source_type="chat",
            source_id=m.id,
            project_id=m.requirement.project_id if m.requirement else None,
            requirement_id=m.requirement_id,
            title=f"对话：{m.requirement.code if m.requirement else m.requirement_id}",
            source_url=f"/r/{m.requirement_id}/clarify",
            content=f"# Chat {m.kind}\n\nRole: {m.role}\n\n{_read_json(m.content_json)}\n\nSelected: {m.selected_option_key or ''}\n\nOther: {m.user_other_text or ''}",
        )

    comment_q = (
        db.query(Comment, Requirement)
        .join(Requirement, Requirement.id == Comment.requirement_id)
        .join(Project, Project.id == Requirement.project_id)
        .filter(Project.archived == False, Project.deleted_at.is_(None))  # noqa: E712
    )
    if project_id:
        comment_q = comment_q.filter(Requirement.project_id == project_id)
    for c, req in comment_q.all():
        yield SourceDoc(
            source_type="comment",
            source_id=c.id,
            project_id=req.project_id,
            requirement_id=c.requirement_id,
            title=f"评论：{c.author_nickname}",
            source_url=f"/r/{c.requirement_id}",
            content=f"# 评论\n\nAuthor: {c.author_nickname}\n\n{c.body}",
        )

    activity_q = (
        db.query(ActivityLog, Requirement)
        .join(Requirement, Requirement.id == ActivityLog.requirement_id)
        .join(Project, Project.id == Requirement.project_id)
        .filter(Project.archived == False, Project.deleted_at.is_(None))  # noqa: E712
    )
    if project_id:
        activity_q = activity_q.filter(Requirement.project_id == project_id)
    for a, req in activity_q.yield_per(500):
        yield SourceDoc(
            source_type="activity",
            source_id=a.id,
            project_id=req.project_id,
            requirement_id=a.requirement_id,
            title=f"活动：{a.action}",
            source_url=f"/r/{a.requirement_id}",
            content=f"# 活动\n\nActor: {a.actor_nickname}\nAction: {a.action}\n\n{_read_json(a.detail_json)}",
        )

    update_q = db.query(RequirementProgressUpdate, Requirement).join(
        Requirement, Requirement.id == RequirementProgressUpdate.requirement_id
    ).join(Project, Project.id == Requirement.project_id).filter(Project.archived == False, Project.deleted_at.is_(None))  # noqa: E712
    if project_id:
        update_q = update_q.filter(Requirement.project_id == project_id)
    for u, req in update_q.yield_per(500):
        yield SourceDoc(
            source_type="workspace_update",
            source_id=u.id,
            project_id=req.project_id,
            requirement_id=u.requirement_id,
            title=f"工作区动态：{u.actor_nickname}",
            source_url=f"/r/{u.requirement_id}",
            content=f"# 工作区动态\n\nActor: {u.actor_nickname}\nKind: {u.kind}\nPhase: {u.phase or ''}\nProgress: {u.progress_percent or ''}\n\n{u.body}",
        )

    meeting_q = (
        db.query(MeetingRecord)
        .join(Project, Project.id == MeetingRecord.project_id)
        .filter(Project.archived == False, Project.deleted_at.is_(None))  # noqa: E712
    )
    if project_id:
        meeting_q = meeting_q.filter(MeetingRecord.project_id == project_id)
    for m in meeting_q.all():
        yield SourceDoc(
            source_type="meeting",
            source_id=m.id,
            project_id=m.project_id,
            requirement_id=m.requirement_id,
            title=f"会议：{m.title}",
            source_url=f"/p/{m.project_id}/meetings",
            content=f"# 会议：{m.title}\n\n## Transcript\n{m.transcript_text or ''}\n\n## Minutes\n{m.minutes_md or ''}",
        )
    insight_q = (
        db.query(MeetingInsight)
        .join(MeetingRecord, MeetingRecord.id == MeetingInsight.meeting_id)
        .join(Project, Project.id == MeetingRecord.project_id)
        .filter(Project.archived == False, Project.deleted_at.is_(None))  # noqa: E712
    )
    if project_id:
        insight_q = insight_q.filter(MeetingRecord.project_id == project_id)
    for i in insight_q.all():
        yield SourceDoc(
            source_type="meeting_insight",
            source_id=i.id,
            project_id=i.meeting.project_id if i.meeting else None,
            requirement_id=i.target_requirement_id,
            title=f"会议洞察：{i.title}",
            source_url=f"/p/{i.meeting.project_id}/meetings" if i.meeting else "/",
            content=f"# 会议洞察\n\nKind: {i.kind}\nStatus: {i.status}\n\n{i.title}\n\n{i.description}\n\n{i.confidence_reason or ''}",
        )

    drive_q = (
        db.query(ProjectDriveVersion)
        .join(ProjectDriveItem, ProjectDriveItem.id == ProjectDriveVersion.item_id)
        .join(Project, Project.id == ProjectDriveItem.project_id)
        .filter(
            ProjectDriveItem.deleted_at.is_(None),
            ProjectDriveVersion.id == ProjectDriveItem.current_version_id,
            Project.archived == False,  # noqa: E712
            Project.deleted_at.is_(None),
        )
    )
    if project_id:
        drive_q = drive_q.filter(ProjectDriveItem.project_id == project_id)
    for v in drive_q.yield_per(200):
        text = v.parsed_text or ""
        if v.parsed_text_path and Path(v.parsed_text_path).exists():
            try:
                text = Path(v.parsed_text_path).read_text(encoding="utf-8")[:200000]
            except Exception:
                pass
        if text:
            yield SourceDoc(
                source_type="drive_file",
                source_id=v.id,
                project_id=v.item.project_id if v.item else None,
                requirement_id=None,
                title=f"网盘文件：{v.filename}",
                source_url=f"/p/{v.item.project_id}/drive" if v.item else "/drive",
                content=f"# 网盘文件：{v.filename}\n\n{text}",
            )

    delivery_q = (
        db.query(Delivery)
        .join(Requirement, Requirement.id == Delivery.requirement_id)
        .join(Project, Project.id == Requirement.project_id)
        .filter(Project.archived == False, Project.deleted_at.is_(None))  # noqa: E712
    )
    if project_id:
        delivery_q = delivery_q.filter(Requirement.project_id == project_id)
    for d in delivery_q.yield_per(500):
        yield SourceDoc(
            source_type="delivery",
            source_id=d.id,
            project_id=d.requirement.project_id if d.requirement else None,
            requirement_id=d.requirement_id,
            title=f"交付：{d.requirement.code if d.requirement else d.requirement_id} round {d.round}",
            source_url=f"/r/{d.requirement_id}",
            content=f"# 交付\n\nSubmitter: {d.submitted_by_nickname}\nNotes: {d.notes or ''}\n\n{d.delivery_doc_md or ''}",
        )


def rebuild_knowledge_index(db: Session, project_id: str | None = None) -> int:
    CORPUS_ROOT.mkdir(parents=True, exist_ok=True)
    count = 0
    seen: set[tuple[str, str]] = set()
    for src in _source_docs(db, project_id=project_id):
        seen.add((src.source_type, src.source_id))
        content_hash = _hash(src.content)
        path = CORPUS_ROOT / _safe_name(src.source_type) / f"{_safe_name(src.source_id)}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(src.content, encoding="utf-8")
        row = (
            db.query(KnowledgeDocument)
            .filter(KnowledgeDocument.source_type == src.source_type, KnowledgeDocument.source_id == src.source_id)
            .first()
        )
        if not row:
            row = KnowledgeDocument(source_type=src.source_type, source_id=src.source_id)
            db.add(row)
        row.project_id = src.project_id
        row.requirement_id = src.requirement_id
        row.title = src.title[:256]
        row.source_url = src.source_url
        row.corpus_path = str(path)
        row.content_hash = content_hash
        row.updated_at = datetime.utcnow()
        count += 1
    # Two-pass stale cleanup: delete DB rows first, commit, THEN unlink
    # orphan files. If we unlinked before commit and the commit failed
    # (FK violation, disk full, lock timeout), search would later resurrect
    # a row whose corpus file no longer exists and every read would throw.
    # File deletes are idempotent and best-effort — losing the unlink just
    # leaves an orphan markdown in CORPUS_ROOT, which the next reindex
    # tolerates.
    stale_q = db.query(KnowledgeDocument)
    if project_id:
        stale_q = stale_q.filter(KnowledgeDocument.project_id == project_id)
    orphan_files: list[str] = []
    for row in stale_q.all():
        if (row.source_type, row.source_id) in seen:
            continue
        if row.corpus_path:
            orphan_files.append(row.corpus_path)
        db.delete(row)
    db.commit()
    for path_str in orphan_files:
        try:
            Path(path_str).unlink(missing_ok=True)
        except Exception:
            pass
    return count


def _line_snippet(lines: list[str], idx: int) -> str:
    start = max(0, idx - 1)
    end = min(len(lines), idx + 2)
    return "\n".join(line.strip() for line in lines[start:end]).strip()[:1000]


def _tokens(query: str) -> list[str]:
    raw = [query.strip()]
    raw.extend(re.findall(r"[\w\u4e00-\u9fff]{2,}", query))
    seen: set[str] = set()
    out: list[str] = []
    for item in raw:
        item = item.strip()
        if item and item.lower() not in seen:
            seen.add(item.lower())
            out.append(item)
    return out[:8]


def _hit_from_line(doc: KnowledgeDocument, line_no: int, snippet: str) -> KnowledgeSearchHit:
    return KnowledgeSearchHit(
        document_id=doc.id,
        project_id=doc.project_id,
        requirement_id=doc.requirement_id,
        source_type=doc.source_type,
        source_id=doc.source_id,
        title=doc.title,
        source_url=doc.source_url,
        line_no=line_no,
        snippet=snippet,
    )


def _rg_hits(query: str, docs: list[KnowledgeDocument], limit: int) -> list[KnowledgeSearchHit]:
    rg = shutil.which("rg")
    if not rg or not docs:
        return []
    path_map = {str(Path(doc.corpus_path).resolve()): doc for doc in docs}
    try:
        proc = subprocess.run(
            [rg, "--json", "-i", "--", query, str(CORPUS_ROOT)],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=8,
        )
    except Exception:
        return []
    hits: list[KnowledgeSearchHit] = []
    for line in proc.stdout.splitlines():
        if len(hits) >= limit:
            break
        try:
            data = json.loads(line)
        except Exception:
            continue
        if data.get("type") != "match":
            continue
        payload = data.get("data") or {}
        path = str(Path(payload.get("path", {}).get("text", "")).resolve())
        doc = path_map.get(path)
        if not doc:
            continue
        hits.append(_hit_from_line(
            doc,
            int(payload.get("line_number") or 1),
            str(payload.get("lines", {}).get("text") or "").strip(),
        ))
    return hits


def search_knowledge(
    db: Session,
    user: User,
    *,
    query: str,
    project_id: str | None = None,
    scope: str | None = None,
    limit: int = 20,
) -> list[KnowledgeSearchHit]:
    q = query.strip()
    if not q:
        return []
    # Do NOT rebuild the index on every search — that was a self-DoS
    # vector. Each search would walk every requirement, chat, comment,
    # activity, workspace_update, meeting, drive_file, delivery on disk.
    # With concurrent users searching, this hammered the disk and slowed
    # every search to seconds. Freshness is now driven by
    # `_periodic_knowledge_reindex` (5 min, in main.py lifespan) and by
    # `POST /api/knowledge/reindex` for admin-on-demand rebuilds. Write
    # paths used to also call rebuild inline; that turned every drive
    # rename into a 10s stall on large projects, so it was removed too.
    # If the corpus is missing for a few minutes after a fresh write,
    # the next search will simply miss those rows — acceptable.
    doc_q = db.query(KnowledgeDocument)
    doc_q = doc_q.outerjoin(Project, KnowledgeDocument.project_id == Project.id).filter(
        or_(
            KnowledgeDocument.project_id.is_(None),
            and_(Project.archived == False, Project.deleted_at.is_(None)),  # noqa: E712
        )
    )
    if project_id:
        doc_q = doc_q.filter(KnowledgeDocument.project_id == project_id)
    if scope:
        doc_q = doc_q.filter(KnowledgeDocument.source_type == scope)
    docs = [doc for doc in doc_q.all() if _requirement_visible(db, doc.requirement_id, user)]
    hits = _rg_hits(q, docs, limit)
    if hits:
        return hits[:limit]

    patterns = [re.compile(re.escape(token), re.IGNORECASE) for token in _tokens(q)]
    out: list[KnowledgeSearchHit] = []
    seen: set[tuple[str, int]] = set()
    for doc in docs:
        if len(out) >= limit:
            break
        path = Path(doc.corpus_path)
        if not path.exists():
            continue
        try:
            lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        except Exception:
            continue
        for idx, line in enumerate(lines):
            if len(out) >= limit:
                break
            if any(p.search(line) for p in patterns):
                key = (doc.id, idx + 1)
                if key in seen:
                    continue
                seen.add(key)
                out.append(_hit_from_line(doc, idx + 1, _line_snippet(lines, idx)))
    return out


def answer_from_hits(question: str, hits: list[KnowledgeSearchHit]) -> tuple[str, list[dict], list[dict]]:
    trace = [{"tool": "grep_corpus", "query": question, "hit_count": len(hits)}]
    if not hits:
        return (
            "没有找到可靠依据。可以换一个更具体的关键词，比如需求编号、会议标题、文件名或接单人昵称。",
            [],
            trace,
        )
    lines = [
        "我用项目知识库 grep 到这些依据，先给结论：",
        "",
        f"- 和“{question}”最相关的是：{hits[0].title}。",
        "- 下面是可核对的证据，建议点进去看原始上下文。",
        "",
        "## 证据",
    ]
    for idx, hit in enumerate(hits[:5], start=1):
        lines.append(f"{idx}. [{hit.title}]({hit.source_url}) · {hit.source_type} · 第 {hit.line_no} 行\n\n   {hit.snippet[:240]}")
    return "\n".join(lines), [hit.model_dump(mode="json") for hit in hits[:8]], trace
