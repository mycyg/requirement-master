from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from anthropic import AsyncAnthropic

from config import settings

logger = logging.getLogger("yqgl.drive_comment_agent")
_client = AsyncAnthropic(base_url=settings.llm_base_url, api_key=settings.llm_api_key)


@dataclass
class DriveCommentClassification:
    kind: str
    reason: str
    title: str | None = None
    draft_description: str | None = None


SYSTEM = """You classify comments left on a project folder in an internal work platform.

Decide whether the comment is a normal folder comment or whether it describes a requirement change, a new requirement, or supplemental requirements.

Output exactly one JSON object and no extra text:
{
  "kind": "normal_comment" | "requirement_change",
  "reason": "...",
  "title": "...",
  "draft_description": "..."
}

Write `reason`, `title`, and `draft_description` in the user's language. If the comment is Chinese, use Chinese. If it is English, use English.

For `normal_comment`, `title` and `draft_description` may be empty strings.
For `requirement_change`, make `draft_description` complete enough to start the requirement clarification flow and include the folder context."""


def _fallback(project_name: str, folder_path: str, body: str) -> DriveCommentClassification:
    lowered = body.lower()
    requirement_words = [
        "需求", "变更", "补充", "改成", "增加", "新增", "需要", "请做", "实现",
        "requirement", "change", "add", "need", "please build", "feature",
    ]
    if any(word in lowered or word in body for word in requirement_words):
        title = body.strip().splitlines()[0][:40] or "文件夹留言需求"
        return DriveCommentClassification(
            kind="requirement_change",
            reason="这条留言看起来包含需求变动或补充，需要进入需求澄清流程。",
            title=title,
            draft_description=(
                f"项目：{project_name}\n"
                f"文件夹：{folder_path or '项目网盘根目录'}\n\n"
                f"用户在项目文件夹留言中提出：\n{body.strip()}\n\n"
                "请根据这条留言继续澄清并整理为明确需求。"
            ),
        )
    return DriveCommentClassification(kind="normal_comment", reason="这条留言是普通项目讨论，不需要生成需求。")


async def classify_drive_comment(project_name: str, folder_path: str, body: str) -> DriveCommentClassification:
    if not settings.llm_api_key:
        return _fallback(project_name, folder_path, body)
    try:
        resp = await _client.messages.create(
            model=settings.llm_model,
            max_tokens=1200,
            system=SYSTEM,
            messages=[{
                "role": "user",
                "content": (
                    f"# Project\n{project_name}\n\n"
                    f"# Folder\n{folder_path or 'Project drive root'}\n\n"
                    f"# Comment\n{body}"
                ),
            }],
        )
        text = "".join(b.text for b in resp.content if b.type == "text").strip()
        if text.startswith("```"):
            first_nl = text.find("\n")
            if first_nl != -1:
                text = text[first_nl + 1:]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()
        data = json.loads(text)
        kind = data.get("kind")
        if kind not in {"normal_comment", "requirement_change"}:
            raise ValueError(f"invalid kind: {kind}")
        return DriveCommentClassification(
            kind=kind,
            reason=str(data.get("reason") or ""),
            title=str(data.get("title") or "") or None,
            draft_description=str(data.get("draft_description") or "") or None,
        )
    except Exception as exc:
        logger.exception("drive comment classification failed")
        raise RuntimeError(f"{type(exc).__name__}: {exc}") from exc
