from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from anthropic import AsyncAnthropic

from config import settings

logger = logging.getLogger("yqgl.meeting_agent")
_client = AsyncAnthropic(base_url=settings.llm_base_url, api_key=settings.llm_api_key)


@dataclass
class MeetingInsightDecision:
    kind: str
    title: str
    description: str
    confidence_reason: str


@dataclass
class MeetingAnalysis:
    minutes_md: str
    insights: list[MeetingInsightDecision]


SYSTEM = """You turn meeting transcripts into useful project meeting minutes.

You must:
- Write all user-facing output in the user's language.
- Detect whether the meeting contains new requirements or changes/supplements to existing requirements.
- Never directly modify a requirement. Only produce suggestions that a human can confirm.

Output exactly one JSON object and no extra text:
{
  "minutes_md": "Markdown meeting minutes...",
  "insights": [
    {
      "kind": "new_requirement" | "requirement_change" | "normal_note",
      "title": "...",
      "description": "...",
      "confidence_reason": "..."
    }
  ]
}

For normal notes, include only genuinely useful project decisions or follow-ups. Avoid noisy filler."""


def _fallback(transcript: str, *, project_name: str, linked_requirement_title: str | None = None) -> MeetingAnalysis:
    text = transcript.strip() or "ASR 没有转出可用文本。"
    title_hint = linked_requirement_title or project_name
    minutes = (
        f"## 会议纪要\n\n"
        f"### 讨论内容\n\n{text[:3000]}\n\n"
        "### 待确认事项\n\n"
        "- 请人工确认上面的内容是否需要进入需求澄清。"
    )
    keywords = ["需求", "变更", "补充", "新增", "改成", "增加", "需要", "请做", "实现", "requirement", "change", "add", "need"]
    kind = "normal_note"
    if any(word in text.lower() or word in text for word in keywords):
        kind = "requirement_change" if linked_requirement_title else "new_requirement"
    return MeetingAnalysis(
        minutes_md=minutes,
        insights=[
            MeetingInsightDecision(
                kind=kind,
                title=(text.splitlines()[0] or f"{title_hint} 会议后续")[:80],
                description=(
                    f"项目：{project_name}\n"
                    f"关联需求：{linked_requirement_title or '无'}\n\n"
                    f"会议中提到：\n{text[:4000]}\n\n"
                    "请基于会议内容进入需求评估和澄清。"
                ),
                confidence_reason="本地 fallback 根据关键词判断，建议人工确认。",
            )
        ],
    )


def _strip_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        first_nl = text.find("\n")
        if first_nl != -1:
            text = text[first_nl + 1:]
        if text.endswith("```"):
            text = text[:-3]
    return text.strip()


async def analyze_meeting(
    *,
    project_name: str,
    transcript: str,
    linked_requirement_title: str | None = None,
) -> MeetingAnalysis:
    if not settings.llm_api_key:
        return _fallback(transcript, project_name=project_name, linked_requirement_title=linked_requirement_title)
    try:
        resp = await _client.messages.create(
            model=settings.llm_model,
            max_tokens=3000,
            system=SYSTEM,
            messages=[{
                "role": "user",
                "content": (
                    f"# Project\n{project_name}\n\n"
                    f"# Linked requirement\n{linked_requirement_title or '(none)'}\n\n"
                    f"# Transcript\n{transcript}"
                ),
            }],
        )
        raw = "".join(block.text for block in resp.content if block.type == "text")
        data = json.loads(_strip_fence(raw))
        insights: list[MeetingInsightDecision] = []
        for item in data.get("insights") or []:
            kind = item.get("kind")
            if kind not in {"new_requirement", "requirement_change", "normal_note"}:
                continue
            insights.append(MeetingInsightDecision(
                kind=kind,
                title=str(item.get("title") or "会议后续")[:256],
                description=str(item.get("description") or ""),
                confidence_reason=str(item.get("confidence_reason") or ""),
            ))
        return MeetingAnalysis(
            minutes_md=str(data.get("minutes_md") or ""),
            insights=insights or _fallback(
                transcript,
                project_name=project_name,
                linked_requirement_title=linked_requirement_title,
            ).insights,
        )
    except Exception as exc:
        logger.exception("meeting analysis failed")
        return _fallback(transcript, project_name=project_name, linked_requirement_title=linked_requirement_title)
